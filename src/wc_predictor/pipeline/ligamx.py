"""Liga MX pipeline: Elo replay + Poisson·DC fit + EV-optimal picks per jornada.

Reuses the tournament-agnostic core (ratings/elo, model/poisson_dc,
model/blend, scoring/quiniela) with the Liga MX profile and data. It does NOT
touch the World-Cup pipeline — this is the "core común, perfil de liga" path
from docs/ligamx_apertura.md.

Two subcommands:

    python -m wc_predictor.pipeline.ligamx fit          # Elo + Poisson·DC → artifacts
    python -m wc_predictor.pipeline.ligamx picks --round j2

`fit` reads data/ligamx/matches_history.csv (from ingest.ligamx) and writes
data/ligamx/elo_current.json + data/ligamx/team_strengths.json.
`picks` reads those + data/ligamx/fixtures.json and writes
outputs/ligamx_picks_{round}.{json,md}.

Liga MX specifics vs the WC path:
  - Localía is per-team: the home side always gets the gamma boost (host="home").
  - Altitude is modelled by DIFFERENTIAL — the visitor loses λ proportional to
    (venue_altitude − visitor's own home altitude), so a CDMX side visiting
    Toluca is penalised far less than a sea-level side. Home side is acclimatised.
  - WC-only layers (host boost, goal inflation, mismatch ramp, J3 qualification)
    are neutralised in LIGAMX_APERTURA_PROFILE.model.
  - Atlante is a cold-start franchise (bought from Mazatlán, starts fresh); with
    ~1 match of history the ridge prior pins it near league average, wide — the
    intended behaviour. See docs/ligamx_apertura.md §Atlante cold-start.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from datetime import datetime, date
from pathlib import Path

from wc_predictor.config import OUTPUTS_DIR
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.blend import blend_three_sources
from wc_predictor.model.poisson_dc import (
    fit_dc_model,
    load_fit,
    predict_lambdas,
    profile_fit_rho,
    save_fit,
)
from wc_predictor.ratings.elo import elo_to_1x2_probs, replay_history
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

PROFILE = LIGAMX_APERTURA_PROFILE
LIGAMX_DIR = PROFILE.data_dir
HISTORY_CSV = LIGAMX_DIR / "matches_history.csv"
FIXTURES_JSON = LIGAMX_DIR / "fixtures.json"
TEAMS_JSON = LIGAMX_DIR / "teams.json"
VENUES_JSON = LIGAMX_DIR / "venues.json"
ELO_JSON = LIGAMX_DIR / "elo_current.json"
STRENGTHS_JSON = LIGAMX_DIR / "team_strengths.json"


# --- data loading -------------------------------------------------------------
def load_history_rows(src: Path = HISTORY_CSV) -> list[dict]:
    rows: list[dict] = []
    with src.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "date": r["date"],
                "home": r["home"],
                "away": r["away"],
                "home_score": int(r["home_score"]),
                "away_score": int(r["away_score"]),
                "neutral": r["neutral"].strip().lower() in {"true", "t", "1", "yes"},
                "tournament": r["tournament"],
                # 'regular' | 'liguilla' | '' — lets the backtest score playoff
                # matches under the playoff calibration instead of averaging them
                # into the regular season they don't behave like.
                "stage": (r.get("stage") or "").strip(),
            })
    rows.sort(key=lambda x: x["date"])
    return rows


def load_team_altitudes() -> dict[str, float]:
    """name_es → altitude (m) of its home stadium, via teams.json + venues.json."""
    teams = json.loads(TEAMS_JSON.read_text(encoding="utf-8"))["teams"]
    venues = json.loads(VENUES_JSON.read_text(encoding="utf-8"))["venues"]
    out: dict[str, float] = {}
    for t in teams:
        v = venues.get(t.get("home_venue") or "", {})
        out[t["name_es"]] = float(v.get("altitude_m", 0.0))
    return out


def _current_teams() -> list[dict]:
    return json.loads(TEAMS_JSON.read_text(encoding="utf-8"))["teams"]


_HOME_VENUE_CACHE: dict[str, str] | None = None


def home_venue_name(name_es: str) -> str | None:
    """The home team's registered stadium (teams.json) — kept consistent with the
    altitude, unlike the fixture's TheSportsDB strVenue which can carry stray data
    (e.g. Atlante, a relocated franchise with an uncertain venue)."""
    global _HOME_VENUE_CACHE
    if _HOME_VENUE_CACHE is None:
        _HOME_VENUE_CACHE = {t["name_es"]: t.get("home_venue")
                             for t in _current_teams()}
    return _HOME_VENUE_CACHE.get(name_es)


# --- altitude (differential) --------------------------------------------------
def altitude_factor(venue_alt: float, visitor_home_alt: float, mcfg) -> float:
    """λ multiplier for the VISITOR, from the altitude they must climb to.

    Only the positive differential bites: a highland side visiting a lowland
    venue is unaffected. Floored at 0.5 like the WC altitude adjustment.
    """
    if mcfg.altitude_penalty_per_1000m <= 0:
        return 1.0
    diff = max(0.0, venue_alt - visitor_home_alt)
    return max(1.0 - mcfg.altitude_penalty_per_1000m * (diff / 1000.0), 0.5)


# --- fit ----------------------------------------------------------------------
def run_fit(fit_rho: bool | None = None) -> None:
    mcfg = PROFILE.model
    if not HISTORY_CSV.exists():
        raise SystemExit(
            f"Missing {HISTORY_CSV}. Run `python -m wc_predictor.ingest.ligamx --bootstrap` first."
        )
    rows = load_history_rows()
    print(f"Loaded {len(rows)} Liga MX matches ({rows[0]['date']} → {rows[-1]['date']})")

    # Elo replay over the club history (self-computed; clubelo is unreachable).
    track = {t["name_es"] for t in _current_teams()}
    elos, _ = replay_history(rows, mcfg, track_teams=track)
    as_of = rows[-1]["date"]
    ranked = [{"team": t, "elo": round(e, 2)} for t, e in sorted(elos.items(), key=lambda x: -x[1])]
    ELO_JSON.write_text(
        json.dumps({"as_of": as_of, "source": "replay_ligamx", "teams": ranked},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  wrote {ELO_JSON} (Elo for {len(ranked)} teams, as_of {as_of})")

    # Poisson + Dixon-Coles MLE. Ridge pins low-n sides (Atlante) to league avg.
    do_rho = mcfg.fit_rho if fit_rho is None else fit_rho
    if do_rho:
        print(f"Fitting Poisson + Dixon-Coles (profiling rho, half-life {mcfg.half_life_days}d) ...")
        _, fit, _ = profile_fit_rho(rows, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                    half_life_days=mcfg.half_life_days)
    else:
        print(f"Fitting Poisson + Dixon-Coles (half-life {mcfg.half_life_days}d) ...")
        fit = fit_dc_model(rows, mcfg, ridge_lambda=mcfg.ridge_lambda,
                           half_life_days=mcfg.half_life_days)
    save_fit(fit, STRENGTHS_JSON, as_of=as_of)
    print(f"  wrote {STRENGTHS_JSON}  mu={fit.mu:.3f} gamma={fit.gamma:.3f} rho={fit.rho:.3f} "
          f"(e^gamma={pow(2.718281828, fit.gamma):.2f}x home)")

    # Sanity: strongest sides in the current field. Both latents are "higher =
    # better" (attack ↑ scores more, defense ↑ concedes less), so overall
    # strength ≈ attack + defense.
    cur = {t["name_es"] for t in _current_teams()}
    ranked_str = sorted(
        (s for t, s in fit.strengths.items() if t in cur),
        key=lambda s: -(s.attack + s.defense),
    )
    print("\nFuerza (attack + defense) del campo actual:")
    for i, s in enumerate(ranked_str, 1):
        elo = elos.get(s.team, 1500.0)
        print(f"  {i:2d}. {s.team:<12} atk={s.attack:+.2f} def={s.defense:+.2f} "
              f"Elo={elo:.0f} n={s.n_matches}")


# --- picks --------------------------------------------------------------------
def _odds_weights(mcfg, have_odds: bool) -> tuple[float, float, float]:
    """(w_poisson, w_elo, w_odds). Without odds → 2-way blend (≈0.70/0.30);
    with odds → odds take blend_odds_weight, Poisson:Elo keep their ratio on the
    remainder (same policy as the WC path)."""
    share = mcfg.blend_poisson_weight / (mcfg.blend_poisson_weight + mcfg.blend_elo_weight)
    if have_odds:
        rem = 1.0 - mcfg.blend_odds_weight
        return rem * share, rem * (1.0 - share), mcfg.blend_odds_weight
    return share, 1.0 - share, 0.0


def blended_matchup(home: str, away: str, fit, elos: dict[str, float],
                    altitudes: dict[str, float], mcfg,
                    odds_1x2: tuple[float, float, float] | None = None,
                    liguilla: bool = False) -> dict | None:
    """Blended score matrix + 1X2 for one home/away pairing — the shared core of a
    Liga MX prediction (per-team localía + altitude differential + Elo, and the
    market when supplied). Returns None if either side lacks fitted strengths.

    Factored out of :func:`predict_fixture` so the liguilla projector can build the
    matrix for ANY matchup (not just a fixtures.json row) without re-deriving the
    pipeline. Keys: cells, p1/px/p2 (blended), lambda_home/away, elo_home/away,
    venue_alt, blend weights, pmass, pmax.

    `liguilla=True` damps the goal environment: the fit trains on a sample that is
    ~90% regular season, but Liga MX playoff football is measurably quieter — over
    99 playoff matches (2023-2026) it runs 2.576 goals/match vs 2.860 in the
    regular season, a ratio of 0.90 (see ModelConfig.ko_goal_env_ratio).
    """
    if home not in fit.strengths or away not in fit.strengths:
        return None
    # Poisson λ with per-team localía (home always gets gamma).
    lh, la = predict_lambdas(fit.strengths[home], fit.strengths[away], fit.mu, fit.gamma,
                             host="home")
    # Altitude differential: the visitor climbs to the home venue's altitude.
    venue_alt = altitudes.get(home, 0.0)
    la *= altitude_factor(venue_alt, altitudes.get(away, 0.0), mcfg)
    if liguilla:
        lh *= mcfg.ko_goal_env_ratio
        la *= mcfg.ko_goal_env_ratio
    # Elo 1X2 with home bonus.
    r_h = elos.get(home, 1500.0)
    r_a = elos.get(away, 1500.0)
    elo_p1, elo_px, elo_p2 = elo_to_1x2_probs(r_h, r_a, mcfg.elo_home_bonus)
    # Poisson·DC score matrix → blend with Elo (+ odds when available).
    w_po, w_el, w_od = _odds_weights(mcfg, odds_1x2 is not None)
    pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
    cells_b, p1_b, px_b, p2_b = blend_three_sources(
        pcells, (pp1, ppx, pp2), (elo_p1, elo_px, elo_p2), odds_1x2,
        w_poisson=w_po, w_elo=w_el, w_odds=w_od,
    )
    return {
        "cells": cells_b, "p1": p1_b, "px": px_b, "p2": p2_b,
        "lambda_home": lh, "lambda_away": la, "elo_home": r_h, "elo_away": r_a,
        "venue_alt": venue_alt, "pmass": pmass, "pmax": pmax,
        "elo_probs": (elo_p1, elo_px, elo_p2),
        "weights": (w_po, w_el, w_od),
    }


def _liguilla_forbid(mcfg, px_blended: float, modal_outcome: str,
                     liguilla: bool) -> tuple[str, ...]:
    """Outcomes the optimizer may not pick, with the playoff exception.

    The draw is banned by default and the ban lifts on a strong enough P(X). The
    liguilla gets the same two-track treatment the World Cup knockouts do,
    because Liga MX playoff football behaves the same way: over 99 playoff
    matches (2023-2026) **32.3% ended level at 90'** vs 23.9% in the regular
    season, so the regular-season gate is calibrated for the wrong base rate.
      - the gate drops to `ko_draw_allow_min_prob`, and
      - a playoff leg whose MODAL blended scoreline is itself a draw unlocks the
        X from `ko_modal_draw_min_prob` — the market-compressed blend rarely
        reaches the probability gates outright, but the grid's #1 cell being a
        0-0/1-1 is a draw signal in its own right.
    """
    forbid = tuple(mcfg.forbid_outcomes)
    gate = mcfg.ko_draw_allow_min_prob if liguilla else mcfg.draw_allow_min_prob
    lift = px_blended >= gate or (
        liguilla and modal_outcome == "X" and px_blended >= mcfg.ko_modal_draw_min_prob
    )
    if "X" in forbid and lift:
        forbid = tuple(o for o in forbid if o != "X")
    return forbid


def predict_fixture(fx: dict, fit, elos: dict[str, float], altitudes: dict[str, float],
                    mcfg, rules, odds: dict | None = None,
                    liguilla: bool = False) -> dict | None:
    """One fixture → pick + diagnostics. `liguilla=True` switches the match to the
    playoff calibration (quieter goal environment, the lower draw gate and the
    exactos tilt) — see :func:`_liguilla_forbid` for the evidence."""
    home, away = fx["home"], fx["away"]
    # Bookmaker 1X2 for this match, if covered (de-vigged closing/live line).
    odds_entry = (odds or {}).get(f"{home}|{away}")
    odds_1x2 = (odds_entry["p1"], odds_entry["px"], odds_entry["p2"]) if odds_entry else None

    m = blended_matchup(home, away, fit, elos, altitudes, mcfg, odds_1x2=odds_1x2,
                        liguilla=liguilla)
    if m is None:
        return {"match_id": fx.get("match_id"), "home": home, "away": away,
                "error": "missing strengths"}
    cells_b, p1_b, px_b, p2_b = m["cells"], m["p1"], m["px"], m["p2"]
    lh, la = m["lambda_home"], m["lambda_away"]
    r_h, r_a = m["elo_home"], m["elo_away"]
    venue_alt = m["venue_alt"]
    pmass, pmax = m["pmass"], m["pmax"]
    elo_p1, elo_px, elo_p2 = m["elo_probs"]
    w_po, w_el, w_od = m["weights"]

    modal_outcome = max(cells_b, key=lambda c: c["prob"])["outcome"]
    forbid = _liguilla_forbid(mcfg, px_b, modal_outcome, liguilla)
    pick = optimize_pick_from_cells(
        cells_b, p1_b, px_b, p2_b, pmass, pmax, rules, mcfg,
        forbid_outcomes=forbid,
        exact_ev_bonus=mcfg.ko_exacto_ev_bonus if liguilla else 0.0,
    )

    return {
        "match_id": fx.get("match_id"),
        "jornada": fx.get("jornada"),
        "date": fx.get("date"),
        "venue": home_venue_name(home) or fx.get("venue"),
        "home": home,
        "away": away,
        "elo_home": round(r_h, 1),
        "elo_away": round(r_a, 1),
        "lambda_home": round(lh, 3),
        "lambda_away": round(la, 3),
        "altitude_m": venue_alt,
        "odds_p1": round(odds_1x2[0], 3) if odds_1x2 else None,
        "odds_px": round(odds_1x2[1], 3) if odds_1x2 else None,
        "odds_p2": round(odds_1x2[2], 3) if odds_1x2 else None,
        "odds_n_books": odds_entry["n_books"] if odds_entry else 0,
        "blend_weights": {"poisson": round(w_po, 3), "elo": round(w_el, 3), "odds": round(w_od, 3)},
        "p_home_win": round(p1_b, 3),
        "p_draw": round(px_b, 3),
        "p_away_win": round(p2_b, 3),
        "pick_1x2": pick.pick_1x2,
        "pick_exact": pick.pick_exact,
        "p_exact": round(pick.prob_exact, 3),
        "ev": round(pick.ev, 3),
        "ev_gap": round(pick.ev_confidence_gap, 3),
        "abstain": pick.abstain,
        "contrarian_pick_1x2": pick.contrarian_pick_1x2,
        "contrarian_pick_exact": pick.contrarian_pick_exact,
        "contrarian_ev": round(pick.contrarian_ev, 3),
        "contrarian_score": round(pick.contrarian_score, 3),
        "contrarian_differs": pick.contrarian_pick_1x2 != pick.pick_1x2,
        "contrarian_ev_sacrifice": round(pick.ev - pick.contrarian_ev, 3),
        "contrarian_actionable": (pick.contrarian_pick_1x2 != pick.pick_1x2
                                  and (pick.ev - pick.contrarian_ev) <= mcfg.contrarian_max_ev_sacrifice),
        "top_5_scores": [{"score": c["score"], "prob": round(c["prob"], 3)}
                         for c in pick.top_5_by_prob],
        "actual": (f"{fx['home_score']}-{fx['away_score']}"
                   if fx.get("home_score") is not None else None),
        # Transient (stripped before serialization) — inputs to the pool optimizer.
        "_cells": cells_b,
        "_elo_probs": (elo_p1, elo_px, elo_p2),
        "_alt_picks": list(pick.alt_picks or []),
    }


POOL_STANDINGS_JSON = LIGAMX_DIR / "pool_standings.json"
POOL_PICKS_JSON = LIGAMX_DIR / "pool_picks.json"


def _apply_pool_objective(picks: list[dict], fx_doc: dict, rules) -> None:
    """Re-select picks to maximize P(finishing 1st) in the pool instead of
    per-match EV. Mutates `picks` in place (mirrors the WC path, LMX data dirs).

    With data/ligamx/pool_standings.json the objective sees your gap to the
    field, exactos cushion and the horizon of matches still to come; with
    pool_picks.json the field is simulated on opponents' REAL submitted picks.
    Without the files it degrades to the single-round objective. See
    model.pool_optimizer / model.standings and docs/ligamx_apertura.md §Fase 2.
    """
    from wc_predictor.model.pool_optimizer import TicketMatch, optimize_ticket
    from wc_predictor.model.standings import attach_real_picks, compute_horizon, load_pool_context

    resolved_ids = {m["match_id"] for m in fx_doc["matches"]
                    if m.get("home_score") is not None}
    decidable = [p for p in picks if p["match_id"] not in resolved_ids]
    tmatches = [
        TicketMatch(
            match_id=p["match_id"], cells=p["_cells"], elo_probs=p["_elo_probs"],
            ev_pick=(p["pick_1x2"], p["pick_exact"]),
            contra_pick=(p["contrarian_pick_1x2"], p["contrarian_pick_exact"]),
            alt_picks=p.get("_alt_picks") or None,
        )
        for p in decidable
    ]

    ctx = load_pool_context(POOL_STANDINGS_JSON)
    if ctx is not None:
        horizon = compute_horizon(ctx, decision_pending=len(tmatches))
        gap = ctx.leader_points - ctx.your_points
        pos = (f"vas detrás del líder por {gap:.0f}" if gap > 0
               else f"lideras por {-gap:.0f}" if gap < 0 else "empatado en la cima")
        print(f"  standings: {ctx.you} {ctx.your_points:.0f} pts / {ctx.your_exactos:.0f} "
              f"exactos ({pos}), {len(ctx.opponents)} rivales; horizonte "
              f"{len(tmatches) + horizon} partidos")
        n_real = attach_real_picks(ctx, POOL_PICKS_JSON)
        print(f"  {'picks reales cargados para %d rivales' % n_real if n_real else 'sin pool_picks.json — campo sintético'}")
        result = optimize_ticket(tmatches, rules, your_points=ctx.your_points,
                                 your_exactos=ctx.your_exactos, opponents=ctx.opponents,
                                 your_q_rate=ctx.your_q_rate, your_e_rate=ctx.your_e_rate,
                                 horizon=horizon)
    else:
        print("  standings: sin data/ligamx/pool_standings.json — objetivo de un solo "
              "round (corre ingest.ligamx_pool para activar alcance/colchón).")
        result = optimize_ticket(tmatches, rules)

    swapped = set(result.swapped_to_contrarian)
    for p in picks:
        p["pool_swapped"] = p["match_id"] in swapped
        chosen = result.chosen.get(p["match_id"])
        if p["match_id"] in swapped and chosen is not None:
            p["pick_1x2"], p["pick_exact"] = chosen
    verdict = ("COLCHÓN: 0 swaps — tu ventaja se compone, EV puro" if not swapped
               else f"ALCANCE: {len(swapped)} swap(s) fuera del pick EV para maximizar el premio")
    pays = len(result.prize_shares)
    print(f"  pool objective: P(1.º) {result.win_prob_ev:.1%} → {result.win_prob_pool:.1%}; "
          f"premio esperado {result.prize_ev:.1%} → {result.prize_pool:.1%} del bote "
          f"({'/'.join(f'{s:.0%}' for s in result.prize_shares)} a {pays} lugar"
          f"{'es' if pays > 1 else ''}) → {verdict}")


def effective_model_config(fit, mcfg):
    """The score matrix must be built with the SAME rho the fit was optimized
    under (`... ligamx fit` profiles it), not the config default — mirrors
    generate_picks. Returns mcfg with dc_rho replaced by the fitted value."""
    if abs(fit.rho - mcfg.dc_rho) > 1e-9:
        return replace(mcfg, dc_rho=fit.rho)
    return mcfg


LIGUILLA_JSON = LIGAMX_DIR / "liguilla.json"


def _load_model():
    """Shared loader for the fitted model + Elo + altitudes (rho-adjusted mcfg)."""
    mcfg, rules = PROFILE.model, PROFILE.rules
    if not STRENGTHS_JSON.exists():
        raise SystemExit(f"Missing {STRENGTHS_JSON}. Run `... ligamx fit` first.")
    fit = load_fit(STRENGTHS_JSON)
    if abs(fit.rho - mcfg.dc_rho) > 1e-9:
        print(f"  usando rho ajustado {fit.rho:+.3f} (default de config {mcfg.dc_rho:+.3f})")
    mcfg = effective_model_config(fit, mcfg)
    elos = {row["team"]: row["elo"]
            for row in json.loads(ELO_JSON.read_text(encoding="utf-8"))["teams"]}
    altitudes = load_team_altitudes()
    return fit, mcfg, rules, elos, altitudes


def _matchup_cells_closure(fit, elos, altitudes, mcfg, liguilla: bool = False):
    """Memoised (home, away) -> blended cells, for the liguilla projector.
    `liguilla=True` builds the matrices under the playoff goal environment."""
    cache: dict[tuple[str, str], list | None] = {}

    def cells(home: str, away: str):
        key = (home, away)
        if key not in cache:
            m = blended_matchup(home, away, fit, elos, altitudes, mcfg, liguilla=liguilla)
            cache[key] = m["cells"] if m is not None else None
        return cache[key]

    return cells


def _regular_matches(fx_doc: dict) -> list[dict]:
    return [m for m in fx_doc["matches"] if m.get("stage") in (None, "regular")]


def run_picks(round_spec: str, objective: str = "ev") -> None:
    from wc_predictor.model.liguilla import LIGUILLA_ROUNDS
    if round_spec.strip().lower() in LIGUILLA_ROUNDS:
        return run_liguilla_picks(round_spec.strip().lower())

    fit, mcfg, rules, elos, altitudes = _load_model()
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))

    odds = {}
    odds_h2h = LIGAMX_DIR / "odds_h2h.json"
    if odds_h2h.exists():
        odds = json.loads(odds_h2h.read_text(encoding="utf-8")).get("matches", {})
        print(f"  odds cargadas para {len(odds)} partidos (blend 3 vías, "
              f"{int(mcfg.blend_odds_weight*100)}% mercado)")
    else:
        print("  sin odds_h2h.json — blend 2 vías (corre ingest.ligamx_odds). ")

    spec = round_spec.strip().lower()
    if spec in ("all", ""):
        selected = fx_doc["matches"]
        label = "all"
    elif spec.startswith("j") and spec[1:].isdigit():
        n = int(spec[1:])
        selected = [m for m in fx_doc["matches"] if m.get("jornada") == n]
        label = f"j{n}"
    else:
        raise SystemExit(f"--round {round_spec!r} no válido para Liga MX. Usa j1..j17 o all.")
    if not selected:
        raise SystemExit(f"No hay partidos para --round {round_spec!r}.")

    picks, errors = [], []
    for fx in selected:
        r = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=odds)
        (errors if r and "error" in r else picks).append(r)

    if objective == "pool" and picks:
        _apply_pool_objective(picks, fx_doc, rules)

    # Strip transient pool-optimizer inputs before serialization.
    for p in picks:
        for k in ("_cells", "_elo_probs", "_alt_picks"):
            p.pop(k, None)

    elo_as_of = json.loads(ELO_JSON.read_text(encoding="utf-8")).get("as_of")
    odds_h2h = LIGAMX_DIR / "odds_h2h.json"
    odds_as_of = (json.loads(odds_h2h.read_text(encoding="utf-8")).get("as_of")
                  if odds_h2h.exists() else None)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": datetime.utcnow().isoformat() + "Z",
        "league": "Liga MX", "round": label,
        "elo_as_of": elo_as_of, "odds_as_of": odds_as_of,
        "rules": {"points_exact": rules.points_exact, "points_1x2": rules.points_1x2},
        "picks": picks, "errors": errors,
    }
    json_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.json"
    json_dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.md"
    md_dst.write_text(_render_md(picks, label, rules, mcfg, elo_as_of, odds_as_of),
                      encoding="utf-8")
    # Value bets for the same round (when market odds exist) → shown in the boleto.
    bets = None
    if label.startswith("j") and (LIGAMX_DIR / "odds_markets.json").exists():
        from wc_predictor.pipeline.ligamx_bets import bets_payload
        bets = bets_payload(label)
        if bets is not None:
            (OUTPUTS_DIR / f"ligamx_bets_{label}.json").write_text(
                json.dumps(bets, indent=2, ensure_ascii=False), encoding="utf-8")
            n_play = sum(1 for b in bets["bets"] if b["edge"] < 0.08)
            print(f"  apuestas: {len(bets['bets'])} con valor ({n_play} jugables 3-8%, "
                  f"resto solo medición ≥8%)")

    from wc_predictor.pipeline.ligamx_html import render_jornada
    html_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.html"
    html_dst.write_text(render_jornada(payload, bets=bets), encoding="utf-8")
    print(f"  wrote {json_dst}\n  wrote {md_dst}\n  wrote {html_dst}")
    print(f"  datos: Elo al {elo_as_of}"
          + (f" · odds capturadas {odds_as_of}" if odds_as_of else " · sin odds"))

    print(f"\nBoleto {label} ({len(picks)} partidos):")
    for p in sorted(picks, key=lambda x: x.get("date") or ""):
        flag = " ★" if p["abstain"] else ""
        act = f"  (real {p['actual']})" if p.get("actual") else ""
        print(f"  {p['home']:<12} {p['pick_exact']:>4} {p['away']:<12} "
              f"[{p['pick_1x2']}] EV={p['ev']:.2f}{flag}{act}")


def _outcome_es(outcome: str, home: str, away: str) -> str:
    return {"1": f"victoria de {home}", "X": "empate", "2": f"victoria de {away}"}[outcome]


def _fmt_score(exact: str) -> str:
    h, _, a = exact.partition("-")
    return f"{h} - {a}"


def _boleto_block(picks: list[dict], label: str, rules) -> str:
    """Monospace 'boleto' — copiar-a-la-quiniela, columnas EV-óptimo + contrarian."""
    name_w = max(max(len(p["home"]), len(p["away"])) for p in picks)
    prefix_w = 12 + 2 * name_w
    width = prefix_w + 7 + 3 + 7 + 4
    rows = ["═" * width,
            f"  TU BOLETO · Liga MX · {label.upper()}",
            "═" * width,
            " " * prefix_w + f"{'EV-ÓPT':>7}   {'CONTRA':>7}",
            "─" * width]
    total_ev = 0.0
    abstain_n = contra_n = 0
    for i, p in enumerate(picks, start=1):
        total_ev += p["ev"]
        flag = "★" if p["abstain"] else ""
        if p["abstain"]:
            abstain_n += 1
        con_mark = ""
        if p.get("contrarian_actionable"):
            con_mark = " ◆"; contra_n += 1
        rows.append((f"  {i:>2}  {p['home']:>{name_w}}  vs  {p['away']:<{name_w}}   "
                     f"{_fmt_score(p['pick_exact']):>7}   "
                     f"{_fmt_score(p['contrarian_pick_exact']):>7}{con_mark} {flag}").rstrip())
    max_pts = len(picks) * rules.points_exact
    rows += ["─" * width,
             f"  {len(picks)} partidos · EV total {total_ev:.2f} / {max_pts} máx · "
             f"{abstain_n}★ ABSTAIN · {contra_n}◆ contrarian accionable",
             "═" * width]
    return "\n".join(rows)


def _reasoning(p: dict, mcfg) -> str:
    home, away = p["home"], p["away"]
    pe = p["pick_exact"]
    top = p.get("top_5_scores", [])
    modal = top[0]["score"] if top else None
    modal_prob = top[0]["prob"] * 100 if top else 0.0
    p1x2 = {"1": p["p_home_win"], "X": p["p_draw"], "2": p["p_away_win"]}[p["pick_1x2"]]
    parts = []
    if pe == modal:
        parts.append(f"El marcador {pe} es además el más probable de la grilla "
                     f"({modal_prob:.1f}%): el optimizador EV y el marcador modal coinciden.")
    else:
        parts.append(f"El optimizador elige {pe} (EV {p['ev']:.2f}) sobre el modal {modal} "
                     f"({modal_prob:.1f}%): cae en {_outcome_es(p['pick_1x2'], home, away)} "
                     f"(P={p1x2*100:.0f}%) y maximiza el EV de exacto + 1X2.")
    if p["abstain"]:
        parts.append(f"⚠ ABSTAIN: el gap de EV al 2.º candidato es {p['ev_gap']:.3f} "
                     f"(< {mcfg.ev_abstain_gap}); confianza baja.")
    if p.get("odds_n_books"):
        parts.append(f"El mercado ({p['odds_n_books']} casas) implica "
                     f"{p['odds_p1']*100:.0f}/{p['odds_px']*100:.0f}/{p['odds_p2']*100:.0f} "
                     f"y pesa {p['blend_weights']['odds']*100:.0f}% del blend.")
    if p.get("contrarian_differs"):
        c_pct = {"1": p["p_home_win"], "X": p["p_draw"],
                 "2": p["p_away_win"]}[p["contrarian_pick_1x2"]]
        sac = p.get("contrarian_ev_sacrifice", 0.0)
        if p.get("contrarian_actionable"):
            parts.append(f"◆ Contrarian accionable: {p['contrarian_pick_exact']} "
                         f"({_outcome_es(p['contrarian_pick_1x2'], home, away)}, P={c_pct*100:.0f}%). "
                         f"Solo sacrificas {sac:.2f} de EV y te diferencias del pool si entra. "
                         f"Recomendable si vas atrás.")
        else:
            parts.append(f"El contrarian apuntaría a {p['contrarian_pick_exact']} pero cuesta "
                         f"{sac:.2f} de EV (> {mcfg.contrarian_max_ev_sacrifice}): quédate con el EV-óptimo.")
    return " ".join(parts)


def _match_card(idx: int, p: dict, mcfg) -> list[str]:
    home, away = p["home"], p["away"]
    L = [f"### {idx} · {home} vs {away}"]
    meta = [f"J{p.get('jornada')}", p.get("date") or "", p.get("venue") or ""]
    if p.get("altitude_m"):
        meta.append(f"{int(p['altitude_m'])} m")
    L.append("_" + " · ".join(m for m in meta if m) + "_\n")
    L.append(f"**Marcador EV-óptimo: {p['pick_exact']}** "
             f"({_outcome_es(p['pick_1x2'], home, away)})  ")
    L.append(f"EV {p['ev']:.2f} · P(exacto) {p['p_exact']*100:.1f}% · gap {p['ev_gap']:.3f}"
             + (f" · real {p['actual']}" if p.get("actual") else "") + "\n")
    if p.get("contrarian_differs"):
        mark = " ◆" if p.get("contrarian_actionable") else ""
        tag = "accionable" if p.get("contrarian_actionable") else "no recomendada (costo alto)"
        L.append(f"**Alternativa contrarian: {p['contrarian_pick_exact']}**{mark} "
                 f"({_outcome_es(p['contrarian_pick_1x2'], home, away)}) — {tag}\n")
    L += ["| Métrica | Valor |", "|---|---|",
          f"| Goles esperados (λ) | {home} {p['lambda_home']:.2f} — {p['lambda_away']:.2f} {away} |",
          f"| Rating Elo | {p['elo_home']:.0f} vs {p['elo_away']:.0f} |",
          f"| Probabilidad 1 / X / 2 | {p['p_home_win']*100:.0f}% / {p['p_draw']*100:.0f}% / {p['p_away_win']*100:.0f}% |",
          f"| Pesos del blend | {p['blend_weights']['poisson']*100:.0f}% Poisson · "
          f"{p['blend_weights']['elo']*100:.0f}% Elo · {p['blend_weights']['odds']*100:.0f}% mercado |"]
    if p.get("odds_n_books"):
        L.append(f"| Cuotas implícitas | {p['odds_p1']*100:.0f}% / {p['odds_px']*100:.0f}% / "
                 f"{p['odds_p2']*100:.0f}% ({p['odds_n_books']} casas) |")
    top = p.get("top_5_scores", [])
    if top:
        L.append("")
        L.append("**Top-5 marcadores:** " + " · ".join(
            f"`{c['score']}` {c['prob']*100:.1f}%" for c in top))
    L.append(f"\n> {_reasoning(p, mcfg)}\n")
    return L


def _render_md(picks: list[dict], label: str, rules, mcfg, elo_as_of=None, odds_as_of=None) -> str:
    ps = sorted(picks, key=lambda x: (x.get("date") or "", x.get("home") or ""))
    L = [f"# Picks Liga MX — {label.upper()}\n",
         f"_Generado {datetime.utcnow().isoformat()}Z · scoring {rules.points_exact} exacto / "
         f"{rules.points_1x2} 1X2 (excluyente, 90')._  "]
    fresh = []
    if elo_as_of:
        fresh.append(f"Elo al {elo_as_of}")
    if odds_as_of:
        fresh.append(f"odds capturadas {odds_as_of}")
    if fresh:
        L.append(f"_Frescura de datos: {' · '.join(fresh)}._\n")
    if ps:
        L.append("```")
        L.append(_boleto_block(ps, label, rules))
        L.append("```\n")
    # Resumen ejecutivo
    total_ev = sum(p["ev"] for p in ps)
    abstain = sum(1 for p in ps if p["abstain"])
    actionable = [p for p in ps if p.get("contrarian_actionable")]
    with_odds = sum(1 for p in ps if p.get("odds_n_books"))
    max_pts = len(ps) * rules.points_exact
    L.append("## Resumen ejecutivo\n")
    if ps:
        L.append(f"- **{len(ps)} partidos** · EV total **{total_ev:.2f}** / {max_pts} máx "
                 f"({total_ev/max_pts*100:.0f}% del techo).")
        L.append(f"- **{with_odds}/{len(ps)}** con cuotas de mercado en el blend (3 vías).")
        L.append(f"- **{abstain}** ABSTAIN (baja confianza) · **{len(actionable)}** contrarian accionables (◆).")
        best = max(ps, key=lambda p: p["ev"]); worst = min(ps, key=lambda p: p["ev_gap"])
        L.append(f"- Pick más sólido: **{best['home']} vs {best['away']}** → {best['pick_exact']} (EV {best['ev']:.2f}).")
        L.append(f"- Pick más frágil: **{worst['home']} vs {worst['away']}** → {worst['pick_exact']} (gap {worst['ev_gap']:.3f}).")
    L.append("\n## Cómo leer\n")
    L.append("- **EV-ÓPT**: marcador que maximiza el valor esperado de puntos (recomendación por defecto).")
    L.append(f"- **◆ contrarian accionable**: sacrificio de EV ≤ {mcfg.contrarian_max_ev_sacrifice} — "
             "diferenciación barata si vas atrás en el pool.")
    L.append(f"- **★ ABSTAIN**: gap de EV < {mcfg.ev_abstain_gap}; pick de baja confianza.\n")
    L.append("## Fichas técnicas por partido\n")
    for i, p in enumerate(ps, start=1):
        L.extend(_match_card(i, p, mcfg))
    return "\n".join(L)


# --- liguilla (playoffs) ------------------------------------------------------
def _load_teams_list() -> list[str]:
    return [t["name_es"] for t in _current_teams()]


def _resolve_bracket(round_key: str, table_now):
    """Series for `round_key`: from data/ligamx/liguilla.json when the user has
    pinned the real bracket, else a deterministic 'chalk' projection off the
    current table (higher seed assumed to win each earlier round). Returns
    (series, is_projected)."""
    from wc_predictor.model.liguilla import (Series, build_final,
                                             build_quarterfinals, reseed_semifinals)
    if LIGUILLA_JSON.exists():
        doc = json.loads(LIGUILLA_JSON.read_text(encoding="utf-8"))
        raw = doc.get(round_key)
        if raw:
            seeds_map = doc.get("seeds") or {}
            out = [Series(round_key, s["high"], s["low"],
                          int(s.get("high_seed") or seeds_map.get(s["high"], 0)),
                          int(s.get("low_seed") or seeds_map.get(s["low"], 0)))
                   for s in raw]
            return out, False
    seeds = [r.team for r in table_now][:8]
    seed_of = {r.team: i + 1 for i, r in enumerate(table_now)}
    qf = build_quarterfinals(seeds)
    if round_key == "quarter_final":
        return qf, True
    sf = reseed_semifinals([s.high for s in qf], seed_of)  # chalk: higher seed wins
    if round_key == "semi_final":
        return sf, True
    return [build_final([s.high for s in sf], seed_of)], True


def run_liguilla_picks(round_key: str) -> None:
    from wc_predictor.model.liguilla import ROUND_LABELS, compute_table, series_advance_prob
    fit, mcfg, rules, elos, altitudes = _load_model()
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    teams = _load_teams_list()
    table_now = compute_table(_regular_matches(fx_doc), teams)
    series, projected = _resolve_bracket(round_key, table_now)

    if projected:
        print(f"  bracket PROYECTADO desde la tabla actual (aún no definido; "
              f"crea {LIGUILLA_JSON.name} para fijar los cruces reales).")
    else:
        print(f"  bracket real cargado de {LIGUILLA_JSON.name}.")

    picks, series_out = [], []
    tie_to_higher = round_key != "final"
    for s in series:
        legs, leg_cells = [], {}
        for leg, home, away in s.legs():
            fx = {"match_id": f"lg_{round_key}_{home}_{away}_{leg}", "home": home,
                  "away": away, "date": None, "jornada": None}
            p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds={},
                                liguilla=True)
            m = blended_matchup(home, away, fit, elos, altitudes, mcfg, liguilla=True)
            leg_cells[leg] = m["cells"] if m else None
            p["leg"] = leg
            legs.append(p)
        adv_high = series_advance_prob(leg_cells["ida"], leg_cells["vuelta"],
                                       tie_to_higher=tie_to_higher)
        series_out.append({
            "round": round_key, "high": s.high, "low": s.low,
            "high_seed": s.high_seed, "low_seed": s.low_seed,
            "adv_high": round(adv_high, 3), "adv_low": round(1 - adv_high, 3),
            "tie_rule": ("mejor sembrado avanza" if tie_to_higher
                         else "empate global → tiempos extra y penales"),
            "legs": [{"leg": p["leg"], "home": p["home"], "away": p["away"],
                      "pick_exact": p["pick_exact"], "pick_1x2": p["pick_1x2"],
                      "ev": p["ev"], "match_id": p["match_id"]} for p in legs],
        })
        picks.extend(legs)

    for p in picks:
        for k in ("_cells", "_elo_probs", "_alt_picks"):
            p.pop(k, None)

    elo_as_of = json.loads(ELO_JSON.read_text(encoding="utf-8")).get("as_of")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    label = round_key
    payload = {
        "as_of": datetime.utcnow().isoformat() + "Z", "league": "Liga MX",
        "round": label, "round_label": ROUND_LABELS[round_key], "projected": projected,
        "elo_as_of": elo_as_of, "two_legged": True,
        "rules": {"points_exact": rules.points_exact, "points_1x2": rules.points_1x2},
        "series": series_out, "picks": picks,
    }
    json_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.json"
    json_dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.md"
    md_dst.write_text(_render_liguilla_md(series_out, round_key, projected, rules, mcfg,
                                          picks, elo_as_of), encoding="utf-8")
    from wc_predictor.pipeline.ligamx_html import render_liguilla
    html_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.html"
    html_dst.write_text(render_liguilla(payload), encoding="utf-8")
    print(f"  wrote {json_dst}\n  wrote {md_dst}\n  wrote {html_dst}")

    print(f"\n{ROUND_LABELS[round_key]} ({len(series_out)} series · ida y vuelta a 90'):")
    for s in series_out:
        print(f"  {s['high']} ({s['high_seed']}) vs {s['low']} ({s['low_seed']})  "
              f"→ P(avanza {s['high']}) {s['adv_high']*100:.0f}%")
        for lg in s["legs"]:
            print(f"      {lg['leg']:<6} {lg['home']:<12} {lg['pick_exact']:>4} "
                  f"{lg['away']:<12} [{lg['pick_1x2']}] EV={lg['ev']:.2f}")


def run_liguilla(n_sims: int = 10000) -> None:
    from wc_predictor.model.liguilla import (REACH_ROUNDS, ROUND_LABELS,
                                             compute_table, project_liguilla)
    fit, mcfg, rules, elos, altitudes = _load_model()
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    teams = _load_teams_list()
    reg = _regular_matches(fx_doc)
    played = [m for m in reg if m.get("home_score") is not None]
    remaining = [m for m in reg if m.get("home_score") is None]
    print(f"  tabla desde {len(played)} partidos jugados; proyectando {len(remaining)} "
          f"restantes × {n_sims} sims ...")
    cells_fn = _matchup_cells_closure(fit, elos, altitudes, mcfg)
    liguilla_cells_fn = _matchup_cells_closure(fit, elos, altitudes, mcfg, liguilla=True)
    proj = project_liguilla(played, remaining, cells_fn, teams, n_sims=n_sims,
                            liguilla_cells=liguilla_cells_fn)
    print(f"  proyección lista en {proj.elapsed_seconds:.1f}s")

    elo_as_of = json.loads(ELO_JSON.read_text(encoding="utf-8")).get("as_of")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": datetime.utcnow().isoformat() + "Z", "league": "Liga MX",
        "kind": "liguilla_projection", "n_sims": proj.n_sims, "elo_as_of": elo_as_of,
        "table": [{"pos": i + 1, "team": r.team, "played": r.played, "points": r.points,
                   "gd": r.gd, "gf": r.gf,
                   "reach": proj.reach[r.team]} for i, r in enumerate(proj.table_now)],
        "projected_qf": [{"high": s.high, "low": s.low,
                          "high_seed": s.high_seed, "low_seed": s.low_seed}
                         for s in proj.projected_qf],
    }
    json_dst = OUTPUTS_DIR / "ligamx_liguilla.json"
    json_dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_dst = OUTPUTS_DIR / "ligamx_liguilla.md"
    md_dst.write_text(_render_liguilla_projection_md(proj, elo_as_of), encoding="utf-8")
    from wc_predictor.pipeline.ligamx_html import render_projection
    html_dst = OUTPUTS_DIR / "ligamx_liguilla.html"
    html_dst.write_text(render_projection(payload), encoding="utf-8")
    print(f"  wrote {json_dst}\n  wrote {md_dst}\n  wrote {html_dst}")

    print(f"\nTabla proyectada (P de alcanzar cada ronda, {proj.n_sims} sims):")
    print(f"  {'#':>2} {'Equipo':<12} {'Pts':>3} {'Liguilla':>9} {'Semis':>6} "
          f"{'Final':>6} {'Campeón':>8}")
    for i, r in enumerate(proj.table_now, 1):
        rc = proj.reach[r.team]
        print(f"  {i:>2} {r.team:<12} {r.points:>3} {rc['liguilla']*100:>8.0f}% "
              f"{rc['semi_final']*100:>5.0f}% {rc['final']*100:>5.0f}% {rc['champion']*100:>7.0f}%")


def _render_liguilla_md(series_out, round_key, projected, rules, mcfg, picks, elo_as_of) -> str:
    from wc_predictor.model.liguilla import ROUND_LABELS
    L = [f"# Liguilla Liga MX — {ROUND_LABELS[round_key]}\n"]
    if projected:
        L.append("> ⚠ **Bracket proyectado** desde la tabla actual — los cruces reales "
                 "aún no están definidos. Los picks por leg se recalculan cuando fijes "
                 "`data/ligamx/liguilla.json`.\n")
    if elo_as_of:
        L.append(f"_Elo al {elo_as_of} · cada leg se puntúa a 90' como cualquier partido._\n")
    for s in series_out:
        L.append(f"## {s['high']} ({s['high_seed']}º) vs {s['low']} ({s['low_seed']}º)\n")
        L.append(f"**P(avanza {s['high']})** {s['adv_high']*100:.0f}% · "
                 f"P(avanza {s['low']}) {s['adv_low']*100:.0f}%  ")
        L.append(f"_Global empatado → {s['tie_rule']}._\n")
        L.append("| Leg | Local | Pick | Visita | 1X2 | EV |")
        L.append("|---|---|:--:|---|:--:|--:|")
        for lg in s["legs"]:
            L.append(f"| {lg['leg']} | {lg['home']} | **{lg['pick_exact']}** | "
                     f"{lg['away']} | {lg['pick_1x2']} | {lg['ev']:.2f} |")
        L.append("")
    return "\n".join(L)


def _render_liguilla_projection_md(proj, elo_as_of) -> str:
    L = ["# Liguilla Liga MX — Proyección\n",
         f"_Monte-Carlo {proj.n_sims} sims · tabla actual + resto de la temporada "
         f"simulado · Elo al {elo_as_of}._\n",
         "## Probabilidad de alcanzar cada ronda\n",
         "| # | Equipo | J | Pts | DG | Liguilla | Semis | Final | Campeón |",
         "|--:|---|--:|--:|--:|--:|--:|--:|--:|"]
    for i, r in enumerate(proj.table_now, 1):
        rc = proj.reach[r.team]
        L.append(f"| {i} | {r.team} | {r.played} | {r.points} | {r.gd:+d} | "
                 f"{rc['liguilla']*100:.0f}% | {rc['semi_final']*100:.0f}% | "
                 f"{rc['final']*100:.0f}% | {rc['champion']*100:.1f}% |")
    L.append("\n## Bracket proyectado (chalk, desde la tabla actual)\n")
    for s in proj.projected_qf:
        L.append(f"- **{s.high_seed}º {s.high}** vs **{s.low_seed}º {s.low}**")
    L.append("\n_Cuartos: 1-8, 2-7, 3-6, 4-5. Semis se resiembran por posición en la "
             "tabla. Todo ida y vuelta; global empatado avanza el mejor sembrado "
             "(en la final, tiempos extra y penales)._")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pipeline Liga MX (fit + picks + liguilla).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("fit", help="Elo replay + Poisson·DC fit.")
    pf.add_argument("--no-fit-rho", dest="fit_rho", action="store_false", default=None)
    pp = sub.add_parser("picks", help="Genera picks de una jornada o ronda de liguilla.")
    pp.add_argument("--round", default="all",
                    help="j1..j17 | all | quarter_final | semi_final | final")
    pp.add_argument("--objective", default="ev", choices=("ev", "pool"),
                    help="ev (default): cada pick maximiza sus propios puntos esperados. "
                         "pool: optimiza el boleto entero para P(quedar 1.º) usando "
                         "data/ligamx/pool_standings.json (+ pool_picks.json si existe).")
    pl = sub.add_parser("liguilla", help="Proyecta la tabla final y el bracket (Monte-Carlo).")
    pl.add_argument("--sims", type=int, default=10000, help="número de simulaciones.")
    args = parser.parse_args(argv)

    if args.cmd == "fit":
        run_fit(fit_rho=args.fit_rho)
    elif args.cmd == "picks":
        run_picks(args.round, objective=args.objective)
    elif args.cmd == "liguilla":
        run_liguilla(n_sims=args.sims)


if __name__ == "__main__":
    main()
