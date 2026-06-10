"""Tune the odds blend weight against settled matches + their captured closing line.

The production `blend_odds_weight` (0.55) is a literature default — closing odds
are near-efficient, so they "should" dominate — but it was never measured on real
results, because no free historical dataset of *international* 1X2 odds exists.

Once the tournament is under way that changes: every played fixture leaves behind
(a) its actual 90-minute score in `fixtures.json` and (b) the frozen closing line
in `data/raw/odds_closing_line.json`. This command pairs the two and, for a grid
of candidate odds weights, replays the exact production blend
(Poisson+DC + Elo + odds, see `pipeline.generate_picks.predict_match`) and reports
two things per weight:

  - quiniela POINTS the EV-no-draw optimizer would have banked (the bottom line);
  - 1X2 calibration (Brier / log-loss).

It recommends the weight that maximizes points (ties broken by Brier) and shows it
against the current config. Nothing is written back automatically — update
`ModelConfig.blend_odds_weight` by hand once enough matches have settled.

    python -m wc_predictor.pipeline.tune_odds_weight
    python -m wc_predictor.pipeline.tune_odds_weight --round j1   # restrict to a jornada

Before the tournament (no settled match has a closing line yet) it prints
"no settled matches with a captured closing line yet" and exits 0 — safe to wire
into a post-jornada cron.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, HISTORICAL_DIR, OUTPUTS_DIR, PROCESSED_DIR, WC_DIR
from wc_predictor.ingest.odds import load_cached_odds, load_closing_line_odds
from wc_predictor.model.adjustments import (
    MatchContext,
    apply_context_adjustments,
    apply_wc_lambdas,
)
from wc_predictor.model.blend import blend_three_sources
from wc_predictor.model.calibration import actual_outcome, brier_score, log_loss
from wc_predictor.model.poisson_dc import load_fit, predict_lambdas
from wc_predictor.ratings.elo import elo_to_1x2_probs
from wc_predictor.scoring.quiniela import (
    build_score_matrix,
    optimize_pick_from_cells,
    score_actual,
)
from wc_predictor.pipeline.generate_picks import (
    _host_role,
    _load_elos,
    _load_fixtures,
    _load_venues,
    resolve_round_filter,
)


def default_weight_grid() -> list[float]:
    """Candidate odds weights from 0.00 (ignore the market) to 0.95 in 0.05 steps."""
    return [round(0.05 * i, 2) for i in range(0, 20)]


def build_match_record(fixture: dict, fit, venues: dict, elos: dict, odds: dict, mcfg):
    """Mirror predict_match's λ pipeline for a SETTLED fixture that has a closing line.

    Returns a record with the Poisson cells/marginals, the Elo and odds 1X2
    triplets, and the actual result — everything the weight sweep needs — or None
    if the match isn't usable (not played, no odds, or strengths missing). The
    jornada-3 qualification damping is intentionally omitted: the closing line
    already prices motivation, and we want a clean read on the odds weight.
    """
    h, a = fixture["home"], fixture["away"]
    if fixture.get("home_score") is None or fixture.get("away_score") is None:
        return None
    if h not in fit.strengths or a not in fit.strengths:
        return None
    odds_entry = odds.get(f"{h}|{a}")
    if not odds_entry:
        return None

    host = _host_role(fixture, venues)
    lh, la = predict_lambdas(fit.strengths[h], fit.strengths[a], fit.mu, fit.gamma, host=host)
    lh, la = apply_wc_lambdas(lh, la, mcfg)
    venue_rec = venues.get(fixture.get("venue") or "", {})
    ctx = MatchContext(
        home=h, away=a, venue=fixture.get("venue") or "",
        venue_country=venue_rec.get("country", ""),
        venue_altitude_m=float(venue_rec.get("altitude_m", 0.0)),
        is_neutral=host is None,
    )
    lh, la = apply_context_adjustments(lh, la, ctx, mcfg)

    r_h, r_a = elos.get(h, 1500.0), elos.get(a, 1500.0)
    home_adv_elo = mcfg.elo_home_bonus if host == "home" else (-mcfg.elo_home_bonus if host == "away" else 0.0)
    elo_1x2 = elo_to_1x2_probs(r_h, r_a, home_adv_elo)

    pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
    ah, av = int(fixture["home_score"]), int(fixture["away_score"])
    return {
        "match": f"{h} vs {a}",
        "poisson_cells": pcells,
        "poisson_1x2": (pp1, ppx, pp2),
        "elo_1x2": elo_1x2,
        "odds_1x2": (odds_entry["p1"], odds_entry["px"], odds_entry["p2"]),
        "pmass": pmass, "pmax": pmax,
        "actual_h": ah, "actual_a": av,
        "actual_outcome": actual_outcome(ah, av),
    }


def score_weight_grid(records: list[dict], w_grid: list[float], poisson_share: float,
                      rules, mcfg) -> list[dict]:
    """For each candidate odds weight, replay the 3-way blend over `records` and
    return points + calibration. Pure function (no I/O), so it is unit-testable.

    The Poisson:Elo pair keeps `poisson_share` of the (1 - w_odds) remainder, exactly
    as `generate_picks._odds_weights` splits it in production.
    """
    out: list[dict] = []
    for w_odds in w_grid:
        w_poisson = (1.0 - w_odds) * poisson_share
        w_elo = (1.0 - w_odds) * (1.0 - poisson_share)
        blended_1x2: list[tuple[float, float, float]] = []
        actuals: list[str] = []
        total_pts = exact_hits = outcome_hits = 0
        for rec in records:
            cells_b, p1_b, px_b, p2_b = blend_three_sources(
                rec["poisson_cells"], rec["poisson_1x2"], rec["elo_1x2"], rec["odds_1x2"],
                w_poisson=w_poisson, w_elo=w_elo, w_odds=w_odds,
            )
            pick = optimize_pick_from_cells(
                cells_b, p1_b, px_b, p2_b, rec["pmass"], rec["pmax"], rules, mcfg,
                forbid_outcomes=mcfg.forbid_outcomes,
            )
            pts = score_actual(rec["actual_h"], rec["actual_a"],
                               pick.pick_1x2, pick.pick_exact, rules)
            total_pts += pts
            if pts == rules.points_exact:
                exact_hits += 1
            if pts >= rules.points_1x2:
                outcome_hits += 1
            blended_1x2.append((p1_b, px_b, p2_b))
            actuals.append(rec["actual_outcome"])
        n = len(records)
        out.append({
            "w_odds": w_odds,
            "points": total_pts,
            "max_points": n * rules.points_exact,
            "pts_per_match": total_pts / n if n else 0.0,
            "exact_hits": exact_hits,
            "outcome_hits": outcome_hits,
            "brier": brier_score(blended_1x2, actuals) if n else float("nan"),
            "log_loss": log_loss(blended_1x2, actuals) if n else float("nan"),
            "n": n,
        })
    return out


def recommend(grid_rows: list[dict]) -> dict:
    """Pick the weight that maximizes points, breaking ties by lower Brier."""
    return max(grid_rows, key=lambda r: (r["points"], -r["brier"]))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tune the odds blend weight on settled matches.")
    parser.add_argument("--round", default="all",
                        help="Restrict to a round/jornada (all | group_stage | j1..j3 | "
                             "md1..md17 | knockout stage). Default: all settled matches.")
    args = parser.parse_args(argv)
    round_filter, round_label = resolve_round_filter(args.round)

    rules = DEFAULT_CONFIG.rules
    mcfg = DEFAULT_CONFIG.model

    fit_src = PROCESSED_DIR / "team_strengths.json"
    if not fit_src.exists():
        raise SystemExit(f"Missing {fit_src}. Run `python -m wc_predictor.pipeline.fit_model` first.")
    fit = load_fit(fit_src)
    if abs(fit.rho - mcfg.dc_rho) > 1e-9:
        mcfg = replace(mcfg, dc_rho=fit.rho)

    venues = _load_venues()
    fixtures_doc = _load_fixtures()
    elos = _load_elos()
    odds = load_closing_line_odds() or load_cached_odds()
    if not odds:
        raise SystemExit("No captured odds (closing line or snapshot). Run "
                         "`python -m wc_predictor.pipeline.snapshot_odds` first.")

    selected = [fx for fx in fixtures_doc["matches"] if round_filter(fx)]
    records = [r for r in (build_match_record(fx, fit, venues, elos, odds, mcfg)
                           for fx in selected) if r is not None]

    if not records:
        print(f"No settled matches with a captured closing line yet (round '{round_label}'). "
              "Nothing to tune — re-run after a jornada has been played and its scores "
              "ingested into fixtures.json.")
        return

    poisson_share = mcfg.blend_poisson_weight / (mcfg.blend_poisson_weight + mcfg.blend_elo_weight)
    grid = default_weight_grid()
    rows = score_weight_grid(records, grid, poisson_share, rules, mcfg)
    best = recommend(rows)
    current = min(rows, key=lambda r: abs(r["w_odds"] - mcfg.blend_odds_weight))

    print(f"\nOdds-weight tuning · round '{round_label}' · {len(records)} settled matches "
          f"with a closing line\n")
    print(f"  {'w_odds':>6}  {'points':>7}  {'/match':>7}  {'exact':>6}  {'1X2':>5}  "
          f"{'Brier':>7}  {'logloss':>8}")
    print(f"  {'-'*56}")
    for r in rows:
        mark = ""
        if r["w_odds"] == best["w_odds"]:
            mark += "  <- best points"
        if abs(r["w_odds"] - mcfg.blend_odds_weight) < 1e-9:
            mark += "  (current config)"
        print(f"  {r['w_odds']:>6.2f}  {r['points']:>7d}  {r['pts_per_match']:>7.3f}  "
              f"{r['exact_hits']:>6d}  {r['outcome_hits']:>5d}  {r['brier']:>7.4f}  "
              f"{r['log_loss']:>8.4f}{mark}")

    print(f"\n  Recommended odds weight: {best['w_odds']:.2f} "
          f"({best['points']}/{best['max_points']} pts, Brier {best['brier']:.4f}).")
    print(f"  Current config blend_odds_weight={mcfg.blend_odds_weight:.2f} "
          f"({current['points']}/{current['max_points']} pts, Brier {current['brier']:.4f}).")
    delta = best["points"] - current["points"]
    if best["w_odds"] != round(mcfg.blend_odds_weight, 2) and delta > 0:
        print(f"  → Switching would have banked +{delta} pts over {len(records)} matches. "
              f"Consider setting ModelConfig.blend_odds_weight = {best['w_odds']:.2f}.")
    else:
        print("  → Current weight is at/above the empirical optimum on this sample; leave it.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUTPUTS_DIR / f"odds_weight_tune_{round_label}.json"
    with dst.open("w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "round": round_label,
            "n_matches": len(records),
            "current_weight": mcfg.blend_odds_weight,
            "recommended_weight": best["w_odds"],
            "grid": rows,
        }, f, indent=2)
    print(f"\n  wrote {dst}")


if __name__ == "__main__":
    main()
