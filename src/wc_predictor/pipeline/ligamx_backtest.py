"""Walk-forward backtest for the Liga MX model — honest out-of-sample quiniela points.

For each weekly batch of test matches, the model is re-fit on ONLY the matches
played strictly before that batch (Elo replay + Poisson·DC), then predicts the
batch and scores it under the pool rules (2 exact / 1 result / 0, draws
forbidden — same as production). No look-ahead: a match never trains on itself
or the future.

Odds are NOT in this backtest (no free historical Liga MX odds feed), so it
measures the model's BASE skill — the Poisson+Elo blend — vs trivial baselines.
The live pipeline adds the market on top (the strongest single predictor).

Run:
    python -m wc_predictor.pipeline.ligamx_backtest                 # default: test on matches >= 2025-07-01
    python -m wc_predictor.pipeline.ligamx_backtest --since 2026-01-01
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime

from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import fit_dc_model
from wc_predictor.pipeline.ligamx import load_history_rows, load_team_altitudes, predict_fixture
from wc_predictor.ratings.elo import replay_history
from wc_predictor.scoring.quiniela import score_actual

PROFILE = LIGAMX_APERTURA_PROFILE


def _iso_week(d: str) -> str:
    y, w, _ = datetime.strptime(d, "%Y-%m-%d").date().isocalendar()
    return f"{y}-W{w:02d}"


def _baseline_points(rows: list[dict], rules) -> dict[str, float]:
    """Trivial baselines for comparison, scored on the same test matches."""
    pts = {"always_1_0": 0, "always_home_win_1x2": 0}
    for r in rows:
        hs, as_ = r["home_score"], r["away_score"]
        pts["always_1_0"] += score_actual(hs, as_, "1", "1-0", rules)
        # 1X2 home pick with a generic 1-0 exact (only the 1X2 point can land)
        pts["always_home_win_1x2"] += score_actual(hs, as_, "1", "9-9", rules)
    return pts


def run(since: str) -> None:
    mcfg, rules = PROFILE.model, PROFILE.rules
    rows = load_history_rows()
    altitudes = load_team_altitudes()

    test = [r for r in rows if r["date"] >= since]
    if not test:
        raise SystemExit(f"No hay partidos de prueba desde {since}.")
    batches: dict[str, list[dict]] = defaultdict(list)
    for r in test:
        batches[_iso_week(r["date"])] = batches[_iso_week(r["date"])] + [r]

    print(f"Backtest walk-forward: {len(test)} partidos de prueba desde {since}, "
          f"{len(batches)} semanas (refit por semana).")

    total_pts = exactos = n = 0
    covered = 0
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        if len(train) < 100:
            continue  # not enough history to fit yet
        elos, _ = replay_history(train, mcfg)
        fit = fit_dc_model(train, mcfg, ridge_lambda=mcfg.ridge_lambda)
        for r in batch:
            if r["home"] not in fit.strengths or r["away"] not in fit.strengths:
                continue
            fx = {"match_id": None, "home": r["home"], "away": r["away"], "home_score": None}
            p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=None)
            if "error" in p:
                continue
            pts = score_actual(r["home_score"], r["away_score"],
                               p["pick_1x2"], p["pick_exact"], rules)
            total_pts += pts
            exactos += 1 if pts >= rules.points_exact else 0
            n += 1
            covered += 1

    base = _baseline_points(test[:covered] if covered else test, rules)
    print(f"\nResultado ({n} partidos puntuados):")
    print(f"  MODELO (Poisson+Elo, sin odds):  {total_pts} pts · {total_pts/n:.3f} pts/partido · "
          f"{exactos} exactos ({exactos/n*100:.0f}%)")
    print(f"  baseline always 1-0:             {base['always_1_0']} pts · {base['always_1_0']/n:.3f} pts/partido")
    print(f"  baseline home-win 1X2:           {base['always_home_win_1x2']} pts · "
          f"{base['always_home_win_1x2']/n:.3f} pts/partido")
    edge = (total_pts - base["always_1_0"]) / max(base["always_1_0"], 1) * 100
    print(f"\n  ventaja del modelo vs 1-0: {edge:+.1f}%")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backtest walk-forward Liga MX.")
    parser.add_argument("--since", default="2025-07-01",
                        help="fecha de inicio de la ventana de prueba (YYYY-MM-DD).")
    args = parser.parse_args(argv)
    run(args.since)


if __name__ == "__main__":
    main()
