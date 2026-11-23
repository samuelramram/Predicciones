"""Backtest walk-forward de las PIERNAS DE LIGUILLA (ida y vuelta a 90').

La liguilla del pool se puntúa por pierna, igual que el rol regular, pero su
física es otra (menos goles, un tercio de empates) y hasta nov 2026 el pipeline
picaba esas piernas SIN mercado (``odds={}``). Este módulo compara políticas de
pick sobre las piernas de liguilla con momios de cierre de Football-Data
(2023→hoy), con fit walk-forward (solo partidos anteriores a la semana), y
reporta puntos/exactos por política con z PAREADO contra la base.

Políticas (todas con ``predict_fixture(..., liguilla=True)`` salvo ``regular``):
  sin_mercado    lo que corría producción antes: blend sin odds
  mercado        blend con el 1X2 de cierre al peso de producción (0.9)
  sin_gate       + la X la decide el EV (sin el veto P(X) ≥ 0.33)
  sin_gate_ev    + ranking por EV puro (sin el bonus al exacto)
  shift_X        + ``liguilla_market_draw_shift`` = X sobre el P(X) del mercado
  regular        mercado con la calibración de rol regular (referencia)

Run:
    python -m wc_predictor.pipeline.ligamx_liguilla_backtest
    python -m wc_predictor.pipeline.ligamx_liguilla_backtest --shifts 0.02,0.04
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict
from dataclasses import replace

from wc_predictor.ingest import ligamx_fd_odds as fd
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import profile_fit_rho
from wc_predictor.pipeline.ligamx import (effective_model_config, load_history_rows,
                                          load_team_altitudes, predict_fixture)
from wc_predictor.pipeline.ligamx_backtest import _iso_week
from wc_predictor.ratings.elo import replay_history

PROFILE = LIGAMX_APERTURA_PROFILE


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def leg_points(pick: str, h: int, a: int) -> tuple[int, int]:
    """(puntos, exacto) con las reglas del pool: 2 exacto / 1 resultado."""
    ph, pa = map(int, pick.split("-"))
    if (ph, pa) == (h, a):
        return 2, 1
    return (1 if _sign(ph - pa) == _sign(h - a) else 0), 0


def policies(mcfg, shifts: list[float]) -> dict[str, tuple[object, bool, bool]]:
    """name → (mcfg, use_odds, liguilla)."""
    no_gate = replace(mcfg, ko_draw_allow_min_prob=0.0)
    out = {
        "sin_mercado": (mcfg, False, True),
        "mercado": (mcfg, True, True),
        "sin_gate": (no_gate, True, True),
        "sin_gate_ev": (replace(no_gate, ko_exacto_ev_bonus=0.0), True, True),
    }
    for s in shifts:
        out[f"shift_{s:.2f}"] = (replace(no_gate, liguilla_market_draw_shift=s), True, True)
        out[f"shift_{s:.2f}_ev"] = (replace(no_gate, liguilla_market_draw_shift=s,
                                            ko_exacto_ev_bonus=0.0), True, True)
    out["regular"] = (mcfg, True, False)
    return out


def run(shifts: list[float], since: str = "2023-01-01") -> dict:
    mcfg, rules = PROFILE.model, PROFILE.rules
    rows = load_history_rows()
    alt = load_team_altitudes()
    idx = fd.index(fd.load())
    legs = [r for r in rows if r.get("stage") == "liguilla" and r["date"] >= since]
    batches: dict[str, list[dict]] = defaultdict(list)
    for r in legs:
        batches[_iso_week(r["date"])].append(r)

    pols = policies(mcfg, shifts)
    res: dict[str, list[tuple[int, int, str]]] = {k: [] for k in pols}
    actual: list[str] = []
    skipped = 0
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        elos, _ = replay_history(train, mcfg)
        _, fit, _ = profile_fit_rho(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                    half_life_days=mcfg.half_life_days, verbose=False)
        for r in batch:
            h, a = r["home"], r["away"]
            o = fd.lookup(idx, h, a, r["date"])
            if o is None or h not in fit.strengths or a not in fit.strengths:
                skipped += 1
                continue
            odds = {f"{h}|{a}": {"p1": o["fair_p1"], "px": o["fair_px"],
                                 "p2": o["fair_p2"], "n_books": 1}}
            hs, as_ = int(r["home_score"]), int(r["away_score"])
            actual.append(f"{hs}-{as_}")
            fx = {"match_id": None, "home": h, "away": a, "home_score": None}
            for name, (cfg, use_odds, lig) in pols.items():
                wcfg = effective_model_config(fit, cfg)
                p = predict_fixture(fx, fit, elos, alt, wcfg, rules,
                                    odds=odds if use_odds else {}, liguilla=lig)
                pts, ex = leg_points(p["pick_exact"], hs, as_)
                res[name].append((pts, ex, p["pick_exact"]))
    return {"res": res, "actual": actual, "skipped": skipped}


def paired_z(a: list[int], b: list[int]) -> float:
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    if n < 2:
        return 0.0
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    return 0.0 if var == 0 else m / math.sqrt(var / n)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shifts", default="0.02,0.04",
                    help="corrimientos de P(X) del mercado a probar (coma)")
    ap.add_argument("--since", default="2023-01-01")
    args = ap.parse_args(argv)
    shifts = [float(x) for x in args.shifts.split(",") if x.strip()]
    out = run(shifts, since=args.since)
    res, n = out["res"], len(out["actual"])
    draws = sum(1 for s in out["actual"] if s.split("-")[0] == s.split("-")[1])
    print(f"\nPiernas de liguilla con momios: {n} (sin momio/fuerzas: {out['skipped']}); "
          f"empates a 90': {draws} ({draws / max(n, 1):.1%})")
    base = [p for p, _, _ in res["mercado"]]
    print(f"\n{'política':<16}{'pts':>5}{'exactos':>9}{'picks X':>9}{'Δ vs mercado':>14}{'z':>7}")
    for name, rows in res.items():
        pts = [p for p, _, _ in rows]
        ex = sum(e for _, e, _ in rows)
        nx = sum(1 for *_, pk in rows if pk.split("-")[0] == pk.split("-")[1])
        z = paired_z(pts, base)
        print(f"{name:<16}{sum(pts):>5}{ex:>9}{nx:>9}{sum(pts) - sum(base):>+14}{z:>7.2f}")


if __name__ == "__main__":
    main()
