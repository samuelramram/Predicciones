"""Backtest the Poisson + DC model on past World Cup tournaments.

For each tournament we:
  1. Filter training data to ONLY what was available before tournament_start.
  2. Fit Poisson + DC on that subset.
  3. Predict each tournament match.
  4. Score with the pool's quiniela rules (`score_actual`).
  5. Compare against naive baselines to see whether the EV-optimal optimizer
     actually delivers more points than simpler strategies, and how the
     score-distribution bias (1-0 over-prediction) translates to actual points.

Strategies compared:
  ev_optimal       — our production model.
  modal_poisson    — pick the single most-probable score from the matrix.
  always_1_0       — always pick 1-0/0-1/0-0 for favorite/underdog/even by λ.
  always_2_1       — always pick 2-1/1-2/1-1.
  outcome_only_21  — pick 1X2 by λ; nominal exact score 2-1/1-2/1-1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from wc_predictor.config import ModelConfig, QuinielaRules
from wc_predictor.model.bivariate_poisson import (
    bp_score_matrix,
    fit_bivariate_poisson,
    predict_bivariate_lambdas,
)
from wc_predictor.model.blend import blend_poisson_with_elo
from wc_predictor.model.calibration import (
    actual_outcome,
    brier_score,
    log_loss,
    reliability_table,
)
from wc_predictor.model.poisson_dc import fit_dc_model, predict_lambdas
from wc_predictor.ratings.elo import elo_to_1x2_probs, replay_history
from wc_predictor.scoring.quiniela import (
    build_score_matrix,
    optimize_pick,
    optimize_pick_from_cells,
    score_actual,
)


BLEND_WEIGHTS_ELO = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.70)  # finer sweep of Elo weight


Strategy = Callable[[float, float, ModelConfig, QuinielaRules], tuple[str, str]]


def strategy_ev_optimal(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    pick = optimize_pick(lh, la, rules, mcfg)
    return pick.pick_1x2, pick.pick_exact


def strategy_modal_poisson(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    cells, _, _, _, _, _ = build_score_matrix(lh, la, mcfg)
    best = max(cells, key=lambda c: c["prob"])
    return best["outcome"], best["score"]


def strategy_ev_no_draw(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    """EV-optimal among (1, 2) only — never picks X. Motivated by the empirical
    finding that the model's draw-pick calibration is poor: it picks the right
    NUMBER of draws across a tournament but not the right MATCHES."""
    cells, p1, _, p2, _, _ = build_score_matrix(lh, la, mcfg)
    best_1 = max((c for c in cells if c["outcome"] == "1"), key=lambda c: c["prob"], default=None)
    best_2 = max((c for c in cells if c["outcome"] == "2"), key=lambda c: c["prob"], default=None)

    def _ev(p_exact: float, p_outcome: float) -> float:
        if rules.exclusive:
            return rules.points_exact * p_exact + rules.points_1x2 * (p_outcome - p_exact)
        return rules.points_exact * p_exact + rules.points_1x2 * p_outcome

    ev_1 = _ev(best_1["prob"], p1) if best_1 else -1.0
    ev_2 = _ev(best_2["prob"], p2) if best_2 else -1.0
    if ev_1 >= ev_2 and best_1:
        return "1", best_1["score"]
    return "2", best_2["score"] if best_2 else "0-0"


def _favorite_pick(lh: float, la: float, favorite_score: str, underdog_score: str, draw_score: str) -> tuple[str, str]:
    if lh > la:
        return "1", favorite_score
    if la > lh:
        return "2", underdog_score
    return "X", draw_score


def strategy_always_1_0(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    return _favorite_pick(lh, la, "1-0", "0-1", "0-0")


def strategy_always_2_1(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    return _favorite_pick(lh, la, "2-1", "1-2", "1-1")


def strategy_outcome_only_21(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    """Same as always_2_1 — the model is purely outcome-aware (no exact attempt)."""
    return _favorite_pick(lh, la, "2-1", "1-2", "1-1")


def strategy_contrarian(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    """Pool-leverage strategy: picks the outcome maximizing ev / p_outcome.

    In a 30-person pool the relevant objective is finishing first, not maximising
    individual expected points. When the EV-optimal pick is the consensus choice
    (high p_outcome), a hit gives no relative edge over opponents who also picked
    it. The contrarian strategy sacrifices a small amount of individual EV for
    significantly higher uniqueness — if the under-picked outcome hits, the player
    leaps ahead of most of the field.

    Formula: contrarian_score = ev / p_outcome (draws not forbidden here; the
    combinator chooses freely among whatever outcomes were not excluded upstream).
    """
    pick = optimize_pick(lh, la, rules, mcfg)
    return pick.contrarian_pick_1x2, pick.contrarian_pick_exact


def strategy_contrarian_no_draw(lh: float, la: float, mcfg: ModelConfig, rules: QuinielaRules) -> tuple[str, str]:
    """Contrarian strategy with draws forbidden (mirrors the production constraint)."""
    pick = optimize_pick(lh, la, rules, mcfg, forbid_outcomes=("X",))
    return pick.contrarian_pick_1x2, pick.contrarian_pick_exact


STRATEGIES: dict[str, Strategy] = {
    "ev_optimal": strategy_ev_optimal,
    "ev_no_draw": strategy_ev_no_draw,
    "modal_poisson": strategy_modal_poisson,
    "always_1_0": strategy_always_1_0,
    "always_2_1": strategy_always_2_1,
    "outcome_only_21": strategy_outcome_only_21,
    "contrarian": strategy_contrarian,
    "contrarian_no_draw": strategy_contrarian_no_draw,
}


@dataclass
class StrategyResult:
    strategy: str
    n_matches: int
    total_points: int
    pts_per_match: float
    exact_hits: int
    outcome_hits: int  # 1X2 hits (includes exact hits + 1X2-only)
    pick_dist: dict[str, int]


@dataclass
class ModelCalibration:
    """Probabilistic 1X2 calibration metrics for a single model (not strategy)."""
    model_name: str
    brier: float
    log_loss: float
    n: int


@dataclass
class TournamentBacktest:
    tournament: str
    year: int
    training_cutoff: str
    n_training: int
    n_matches: int
    by_strategy: dict[str, StrategyResult]
    by_model_calibration: dict[str, ModelCalibration]
    per_match: list[dict]


def _filter_tournament(rows: list[dict], tournament: str, year: int) -> list[dict]:
    return sorted(
        [
            r for r in rows
            if r["tournament"] == tournament
            and datetime.fromisoformat(r["date"]).date().year == year
        ],
        key=lambda r: r["date"],
    )


def run_tournament_backtest(
    all_rows: list[dict],
    tournament: str,
    year: int,
    rules: QuinielaRules,
    mcfg: ModelConfig,
    training_years: int = 5,
    verbose: bool = True,
) -> TournamentBacktest:
    tournament_matches = _filter_tournament(all_rows, tournament, year)
    if not tournament_matches:
        raise ValueError(f"No {tournament} matches in {year}")

    tournament_start = datetime.fromisoformat(tournament_matches[0]["date"]).date()
    training_cutoff = tournament_start - timedelta(days=1)
    training_start = date(training_cutoff.year - training_years, training_cutoff.month, training_cutoff.day)

    training_rows = [
        r for r in all_rows
        if training_start <= datetime.fromisoformat(r["date"]).date() <= training_cutoff
    ]
    if verbose:
        print(f"\n=== {tournament} {year} ===")
        print(f"  tournament: {len(tournament_matches)} matches, {tournament_start} → {tournament_matches[-1]['date']}")
        print(f"  training:   {len(training_rows)} matches, {training_start} → {training_cutoff}")

    fit_pois = fit_dc_model(training_rows, mcfg, as_of=training_cutoff,
                            half_life_days=730, ridge_lambda=mcfg.ridge_lambda,
                            verbose=False)
    fit_biv = fit_bivariate_poisson(training_rows, mcfg, as_of=training_cutoff,
                                    half_life_days=730, ridge_lambda=mcfg.ridge_lambda,
                                    verbose=False)

    # Elo replay on the same training window (uses raw matches dating to 1872; the
    # cutoff filters via training_rows already, but Elo benefits from full history).
    elo_rows_all = sorted(
        [r for r in all_rows if datetime.fromisoformat(r["date"]).date() <= training_cutoff],
        key=lambda r: r["date"],
    )
    elos, _ = replay_history(elo_rows_all, mcfg)

    if verbose:
        print(f"  poisson:    mu={fit_pois.mu:.3f}, gamma={fit_pois.gamma:.3f}, {fit_pois.n_teams} teams")
        print(f"  bivariate:  mu={fit_biv.mu:.3f}, gamma={fit_biv.gamma:.3f}, "
              f"lambda3={fit_biv.lambda3:.3f}, {fit_biv.n_teams} teams")
        print(f"  elo:        replayed {len(elo_rows_all)} matches → {len(elos)} teams")

    # Bivariate variants are only computed for these strategies below; creating a
    # biv_ key for every STRATEGIES entry (e.g. biv_contrarian) would leave it with
    # zero scored matches → a ZeroDivisionError when the summary divides by n_matches.
    BIV_STRATEGIES = (
        "biv_ev_optimal", "biv_ev_no_draw", "biv_modal_poisson",
        "biv_always_1_0", "biv_always_2_1", "biv_outcome_only_21",
    )
    by_strategy: dict[str, list[dict]] = {s: [] for s in STRATEGIES}
    by_strategy.update({s: [] for s in BIV_STRATEGIES})
    for w_elo in BLEND_WEIGHTS_ELO:
        by_strategy[f"blend_w{int(w_elo*100):02d}_ev_optimal"] = []
        by_strategy[f"blend_w{int(w_elo*100):02d}_ev_no_draw"] = []
    by_strategy["elo_only_outcome_21"] = []

    # Per-model 1X2 probability streams for calibration (Brier / log-loss).
    # Each list parallels `actuals_1x2`.
    actuals_1x2: list[str] = []
    probs_by_model: dict[str, list[tuple[float, float, float]]] = {
        "poisson_dc": [],
        "bivariate": [],
        "elo_only": [],
    }
    for w_elo in BLEND_WEIGHTS_ELO:
        probs_by_model[f"blend_w{int(w_elo*100):02d}"] = []

    per_match: list[dict] = []

    for m in tournament_matches:
        home, away = m["home"], m["away"]
        if home not in fit_pois.strengths or away not in fit_pois.strengths:
            continue
        host = "home" if not m["neutral"] else None
        lh, la = predict_lambdas(fit_pois.strengths[home], fit_pois.strengths[away],
                                 fit_pois.mu, fit_pois.gamma, host=host)
        l1, l2 = predict_bivariate_lambdas(fit_biv.strengths[home], fit_biv.strengths[away],
                                           fit_biv.mu, fit_biv.gamma, host=host)
        bv_matrix = bp_score_matrix(l1, l2, fit_biv.lambda3, max_goals=8)

        actual_h, actual_a = int(m["home_score"]), int(m["away_score"])
        actual_score = f"{actual_h}-{actual_a}"
        actual_1x2 = actual_outcome(actual_h, actual_a)
        actuals_1x2.append(actual_1x2)

        # Poisson-DC marginals (recomputed from lambdas via the score matrix)
        pcells_calib, pp1_c, ppx_c, pp2_c, _, _ = build_score_matrix(lh, la, mcfg)
        probs_by_model["poisson_dc"].append((pp1_c, ppx_c, pp2_c))
        # Bivariate marginals
        probs_by_model["bivariate"].append((bv_matrix["p_1"], bv_matrix["p_x"], bv_matrix["p_2"]))

        match_row = {
            "date": m["date"], "home": home, "away": away,
            "host": host, "actual_score": actual_score, "actual_outcome": actual_1x2,
            "lambda_home": round(lh, 2), "lambda_away": round(la, 2),
            "bv_l1": round(l1, 2), "bv_l2": round(l2, 2), "bv_l3": round(fit_biv.lambda3, 3),
            "by_strategy": {},
        }

        # Poisson-DC strategies (existing strategies use lh, la)
        for name, strat in STRATEGIES.items():
            pick_1x2, pick_exact = strat(lh, la, mcfg, rules)
            pts = score_actual(actual_h, actual_a, pick_1x2, pick_exact, rules)
            by_strategy[name].append({"pick_1x2": pick_1x2, "pick_exact": pick_exact, "points": pts})
            match_row["by_strategy"][name] = {"pick_1x2": pick_1x2, "pick_exact": pick_exact, "points": pts}

        # Bivariate strategies: use the bivariate score matrix with the EV optimizer
        biv_ev_all = optimize_pick_from_cells(
            bv_matrix["cells"], bv_matrix["p_1"], bv_matrix["p_x"], bv_matrix["p_2"],
            bv_matrix["captured_mass"], bv_matrix["max_goals"], rules, mcfg,
        )
        biv_ev_no_draw = optimize_pick_from_cells(
            bv_matrix["cells"], bv_matrix["p_1"], bv_matrix["p_x"], bv_matrix["p_2"],
            bv_matrix["captured_mass"], bv_matrix["max_goals"], rules, mcfg,
            forbid_outcomes=("X",),
        )
        modal_cell = max(bv_matrix["cells"], key=lambda c: c["prob"])
        biv_picks = {
            "biv_ev_optimal": (biv_ev_all.pick_1x2, biv_ev_all.pick_exact),
            "biv_ev_no_draw": (biv_ev_no_draw.pick_1x2, biv_ev_no_draw.pick_exact),
            "biv_modal_poisson": (modal_cell["outcome"], modal_cell["score"]),
            "biv_always_1_0": _favorite_pick(l1, l2, "1-0", "0-1", "0-0"),
            "biv_always_2_1": _favorite_pick(l1, l2, "2-1", "1-2", "1-1"),
            "biv_outcome_only_21": _favorite_pick(l1, l2, "2-1", "1-2", "1-1"),
        }
        for name, (p1x2, pe) in biv_picks.items():
            pts = score_actual(actual_h, actual_a, p1x2, pe, rules)
            by_strategy[name].append({"pick_1x2": p1x2, "pick_exact": pe, "points": pts})
            match_row["by_strategy"][name] = {"pick_1x2": p1x2, "pick_exact": pe, "points": pts}

        # Elo-blend strategies: rescale the Poisson-DC cell distribution to match
        # log-pool(P_poisson, P_elo) marginals, then run the EV optimizer.
        r_h = elos.get(home, 1500.0)
        r_a = elos.get(away, 1500.0)
        home_adv_elo = mcfg.elo_home_bonus if host == "home" else 0.0
        if host == "away":
            # Mirror: if away team is the host, pass the bonus on their side
            home_adv_elo = -mcfg.elo_home_bonus
        elo_p1, elo_px, elo_p2 = elo_to_1x2_probs(r_h, r_a, home_adv_elo)
        probs_by_model["elo_only"].append((elo_p1, elo_px, elo_p2))

        # Pure Elo baseline (outcome by Elo, nominal 2-1/1-2/1-1 exact)
        if elo_p1 >= elo_px and elo_p1 >= elo_p2:
            elo_pick = ("1", "2-1")
        elif elo_p2 >= elo_px:
            elo_pick = ("2", "1-2")
        else:
            elo_pick = ("X", "1-1")
        pts = score_actual(actual_h, actual_a, elo_pick[0], elo_pick[1], rules)
        by_strategy["elo_only_outcome_21"].append(
            {"pick_1x2": elo_pick[0], "pick_exact": elo_pick[1], "points": pts}
        )
        match_row["by_strategy"]["elo_only_outcome_21"] = {
            "pick_1x2": elo_pick[0], "pick_exact": elo_pick[1], "points": pts
        }

        # Poisson cells from the existing fit (recompute since we don't carry them above)
        pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
        for w_elo in BLEND_WEIGHTS_ELO:
            cells_b, p1_b, px_b, p2_b = blend_poisson_with_elo(
                pcells, pp1, ppx, pp2, elo_p1, elo_px, elo_p2,
                w_poisson=1.0 - w_elo, w_elo=w_elo,
            )
            probs_by_model[f"blend_w{int(w_elo*100):02d}"].append((p1_b, px_b, p2_b))
            pick_ev = optimize_pick_from_cells(cells_b, p1_b, px_b, p2_b, pmass, pmax, rules, mcfg)
            pick_nd = optimize_pick_from_cells(cells_b, p1_b, px_b, p2_b, pmass, pmax, rules, mcfg,
                                                forbid_outcomes=("X",))
            for tag, pk in (("ev_optimal", pick_ev), ("ev_no_draw", pick_nd)):
                name = f"blend_w{int(w_elo*100):02d}_{tag}"
                pts = score_actual(actual_h, actual_a, pk.pick_1x2, pk.pick_exact, rules)
                by_strategy[name].append({"pick_1x2": pk.pick_1x2, "pick_exact": pk.pick_exact, "points": pts})
                match_row["by_strategy"][name] = {
                    "pick_1x2": pk.pick_1x2, "pick_exact": pk.pick_exact, "points": pts,
                }

        match_row["elo_p1"] = round(elo_p1, 3)
        match_row["elo_px"] = round(elo_px, 3)
        match_row["elo_p2"] = round(elo_p2, 3)
        match_row["elo_home"] = round(r_h, 1)
        match_row["elo_away"] = round(r_a, 1)

        per_match.append(match_row)

    summaries: dict[str, StrategyResult] = {}
    for name, entries in by_strategy.items():
        total = sum(e["points"] for e in entries)
        exact = sum(1 for e in entries if e["points"] == rules.points_exact)
        outcome = sum(1 for e in entries if e["points"] >= rules.points_1x2)
        dist = {"1": 0, "X": 0, "2": 0}
        for e in entries:
            dist[e["pick_1x2"]] += 1
        summaries[name] = StrategyResult(
            strategy=name, n_matches=len(entries),
            total_points=total,
            pts_per_match=total / len(entries) if entries else 0.0,
            exact_hits=exact, outcome_hits=outcome, pick_dist=dist,
        )

    # Calibration metrics per model (Brier + log-loss on 1X2 marginals).
    calibrations: dict[str, ModelCalibration] = {}
    for model_name, probs in probs_by_model.items():
        if not probs:
            continue
        calibrations[model_name] = ModelCalibration(
            model_name=model_name,
            brier=brier_score(probs, actuals_1x2),
            log_loss=log_loss(probs, actuals_1x2),
            n=len(probs),
        )

    if verbose:
        print(f"\n  Strategy        Total   /match   Exact   Outcome    1/X/2 picks")
        print(f"  {'-'*70}")
        for name, s in sorted(summaries.items(), key=lambda x: -x[1].total_points)[:8]:
            print(f"  {name:<16} {s.total_points:>5d}   {s.pts_per_match:>5.2f}   "
                  f"{s.exact_hits:>3d}/{s.n_matches:<3d}  {s.outcome_hits:>3d}/{s.n_matches:<3d}  "
                  f"{s.pick_dist['1']}/{s.pick_dist['X']}/{s.pick_dist['2']}")
        print(f"\n  Calibration (lower=better; random uniform Brier=0.667, log-loss=1.099):")
        for name, c in sorted(calibrations.items(), key=lambda x: x[1].brier):
            print(f"  {name:<16} Brier={c.brier:.4f}   log-loss={c.log_loss:.4f}   n={c.n}")

    return TournamentBacktest(
        tournament=tournament, year=year,
        training_cutoff=training_cutoff.isoformat(),
        n_training=len(training_rows), n_matches=len(tournament_matches),
        by_strategy=summaries, by_model_calibration=calibrations, per_match=per_match,
    )
