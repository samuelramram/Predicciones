"""Walk-forward backtest for the Liga MX model — honest out-of-sample quiniela points.

For each weekly batch of test matches, the model is re-fit on ONLY the matches
played strictly before that batch (Elo replay + Poisson·DC, profiling rho the
same way production `ligamx fit` does), then predicts the batch and scores it
under the pool rules (2 exact / 1 result / 0 — same as production). No
look-ahead: a match never trains on itself or the future.

The baselines are scored on EXACTLY the matches the model scored (early weeks
without enough training history, or teams missing strengths, are excluded from
both sides), so the reported edge is an apples-to-apples comparison.

Odds are NOT in this backtest (no free historical Liga MX odds feed), so it
measures the model's BASE skill — the Poisson+Elo blend — vs trivial baselines.
The live pipeline adds the market on top (the strongest single predictor).

Run:
    python -m wc_predictor.pipeline.ligamx_backtest                 # default: test on matches >= 2025-07-01
    python -m wc_predictor.pipeline.ligamx_backtest --since 2026-01-01
    python -m wc_predictor.pipeline.ligamx_backtest --no-fit-rho    # fixed config rho (faster)

`run()` also accepts an mcfg override and returns the stats dict, so calibration
sweeps (draw gate, Elo K, blend weights) can A/B hyperparameters against the
same walk-forward harness production uses.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime

from wc_predictor.config import ModelConfig
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import fit_dc_model, profile_fit_rho
from wc_predictor.pipeline.ligamx import (effective_model_config, load_history_rows,
                                          load_team_altitudes, predict_fixture)
from wc_predictor.ratings.elo import replay_history
from wc_predictor.scoring.quiniela import score_actual

PROFILE = LIGAMX_APERTURA_PROFILE


def _iso_week(d: str) -> str:
    y, w, _ = datetime.strptime(d, "%Y-%m-%d").date().isocalendar()
    return f"{y}-W{w:02d}"


def baseline_points(rows: list[dict], rules) -> dict[str, int]:
    """Trivial baselines scored on the given rows — callers MUST pass the same
    rows the model was scored on (see run) for the comparison to be honest."""
    pts = {"always_1_0": 0, "always_home_win_1x2": 0}
    for r in rows:
        hs, as_ = r["home_score"], r["away_score"]
        pts["always_1_0"] += score_actual(hs, as_, "1", "1-0", rules)
        # 1X2 home pick with a generic 9-9 exact (only the 1X2 point can land)
        pts["always_home_win_1x2"] += score_actual(hs, as_, "1", "9-9", rules)
    return pts


def run(since: str, mcfg: ModelConfig | None = None, quiet: bool = False) -> dict:
    """Walk-forward backtest. Returns {n, points, exactos, pts_per_match,
    baselines, edge_vs_1_0_pct}. `mcfg` overrides the profile's model config
    (calibration sweeps); rules always come from the profile."""
    mcfg = mcfg or PROFILE.model
    rules = PROFILE.rules
    rows = load_history_rows()
    altitudes = load_team_altitudes()

    test = [r for r in rows if r["date"] >= since]
    if not test:
        raise SystemExit(f"No hay partidos de prueba desde {since}.")
    batches: dict[str, list[dict]] = defaultdict(list)
    for r in test:
        batches[_iso_week(r["date"])].append(r)

    if not quiet:
        print(f"Backtest walk-forward: {len(test)} partidos de prueba desde {since}, "
              f"{len(batches)} semanas (refit por semana, "
              f"{'rho perfilado' if mcfg.fit_rho else f'rho fijo {mcfg.dc_rho:+.2f}'}).")

    total_pts = exactos = 0
    scored_rows: list[dict] = []
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        if len(train) < 100:
            continue  # not enough history to fit yet
        elos, _ = replay_history(train, mcfg)
        if mcfg.fit_rho:
            _, fit, _ = profile_fit_rho(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                        verbose=False)
        else:
            fit = fit_dc_model(train, mcfg, ridge_lambda=mcfg.ridge_lambda, verbose=False)
        # Same rho contract as production picks: matrix built with the fitted rho.
        wk_mcfg = effective_model_config(fit, mcfg)
        for r in batch:
            if r["home"] not in fit.strengths or r["away"] not in fit.strengths:
                continue
            fx = {"match_id": None, "home": r["home"], "away": r["away"], "home_score": None}
            p = predict_fixture(fx, fit, elos, altitudes, wk_mcfg, rules, odds=None)
            if "error" in p:
                continue
            pts = score_actual(r["home_score"], r["away_score"],
                               p["pick_1x2"], p["pick_exact"], rules)
            total_pts += pts
            exactos += 1 if pts >= rules.points_exact else 0
            scored_rows.append(r)

    n = len(scored_rows)
    if n == 0:
        raise SystemExit("El backtest no puntuó ningún partido (¿historial muy corto?).")
    base = baseline_points(scored_rows, rules)
    edge = (total_pts - base["always_1_0"]) / max(base["always_1_0"], 1) * 100

    if not quiet:
        print(f"\nResultado ({n} partidos puntuados; baselines sobre esos MISMOS partidos):")
        print(f"  MODELO (Poisson+Elo, sin odds):  {total_pts} pts · {total_pts/n:.3f} pts/partido · "
              f"{exactos} exactos ({exactos/n*100:.0f}%)")
        print(f"  baseline always 1-0:             {base['always_1_0']} pts · {base['always_1_0']/n:.3f} pts/partido")
        print(f"  baseline home-win 1X2:           {base['always_home_win_1x2']} pts · "
              f"{base['always_home_win_1x2']/n:.3f} pts/partido")
        print(f"\n  ventaja del modelo vs 1-0: {edge:+.1f}%")

    return {
        "n": n,
        "points": total_pts,
        "exactos": exactos,
        "pts_per_match": total_pts / n,
        "baselines": base,
        "edge_vs_1_0_pct": edge,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backtest walk-forward Liga MX.")
    parser.add_argument("--since", default="2025-07-01",
                        help="fecha de inicio de la ventana de prueba (YYYY-MM-DD).")
    parser.add_argument("--no-fit-rho", dest="fit_rho", action="store_false", default=True,
                        help="usa el rho fijo de config en vez de perfilarlo por semana.")
    args = parser.parse_args(argv)
    mcfg = PROFILE.model
    if not args.fit_rho:
        from dataclasses import replace
        mcfg = replace(mcfg, fit_rho=False)
    run(args.since, mcfg=mcfg)


if __name__ == "__main__":
    main()
