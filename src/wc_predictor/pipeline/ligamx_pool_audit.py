"""Auditoría del pool: ¿suerte o estrategia? Puntos ESPERADOS vs reales por jugador.

Cuando el boleto va mal, la pregunta honesta no es "¿cuántos puntos saqué?" sino
"¿qué tan buenos eran mis picks ANTES de patear?". Este módulo califica el boleto
REAL de cada jugador del pool (``pool_picks.json``) con una vara que no es el
modelo: la **línea justa de cierre del mercado**.

Por partido:
  1. Walk-forward (igual que ``liga_backtest``): fit solo con partidos anteriores
     → matriz de marcadores del modelo.
  2. Esa matriz se re-pesa por resultado para que su 1X2 sea el del MERCADO
     (la forma de los marcadores sale del modelo; el 1X2, del mercado).
  3. Puntos esperados de un pick = P(su resultado) + P(su marcador exacto)
     (reglas del pool: 1 por resultado, 2 por exacto, excluyente).

``suerte = reales − esperados``. Un jugador muy por encima de sus esperados va
con viento a favor; uno muy por debajo, en contra. Es la prueba que separa
"pico mal" de "me tocó la varianza".

``--policies`` además simula el resto del torneo (Monte-Carlo) desde la tabla
actual con varias políticas para tu boleto. Los rivales juegan sus picks REALES
re-muestreados, así se conserva cómo se correlacionan contigo. Responde: ¿conviene
desviarse del EV (p.ej. picar más empates) estando abajo?

Medido tras J11 (79 partidos): Claudio tenía el boleto de MAYOR valor esperado del
pool (46.6, 0.590/partido) y sacó 34 (−12.6); Aldo, 44.7 esperados → 47 reales.
Todas las políticas de empates bajaron P(premio) contra EV puro (verdad = mercado
y verdad = modelo). Ver CLAUDE.md §Auditoría del pool.

Run:
    python -m wc_predictor.pipeline.ligamx_pool_audit
    python -m wc_predictor.pipeline.ligamx_pool_audit --policies --sims 10000
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

import numpy as np

from wc_predictor.ingest import ligamx_fd_odds as fd
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import profile_fit_rho
from wc_predictor.pipeline.ligamx import (FIXTURES_JSON, LIGAMX_DIR, POOL_PICKS_JSON,
                                          POOL_STANDINGS_JSON, effective_model_config,
                                          load_history_rows, load_team_altitudes,
                                          predict_fixture)
from wc_predictor.pipeline.ligamx_backtest import _iso_week
from wc_predictor.ratings.elo import replay_history

PROFILE = LIGAMX_APERTURA_PROFILE
SOURCE_TRACKER_JSON = LIGAMX_DIR / "source_tracker.json"
_OIDX = {1: 0, 0: 1, -1: 2}


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def outcome(score: str) -> int:
    """'2-1' → 1 (local), 0 (empate), -1 (visita)."""
    h, a = map(int, score.split("-"))
    return _sign(h - a)


def market_reweight(cells: list[tuple[str, float]], market: tuple[float, float, float]
                    ) -> dict[str, float]:
    """Score distribution with the model's SHAPE and the market's 1X2."""
    mass = [0.0, 0.0, 0.0]
    for s, p in cells:
        mass[_OIDX[outcome(s)]] += p
    out = {s: p * market[_OIDX[outcome(s)]] / mass[_OIDX[outcome(s)]]
           for s, p in cells if mass[_OIDX[outcome(s)]] > 0}
    tot = sum(out.values())
    return {s: p / tot for s, p in out.items()}


def expected_points(pick: str, dist: dict[str, float]) -> float:
    """Pool rules (2 exact / 1 result, exclusive) = P(result) + P(exact)."""
    o = outcome(pick)
    return sum(p for s, p in dist.items() if outcome(s) == o) + dist.get(pick, 0.0)


def realized_points(pick: str, actual: str) -> int:
    if pick == actual:
        return 2
    return 1 if outcome(pick) == outcome(actual) else 0


def _tracker_market() -> dict[tuple[str, str], tuple[float, float, float]]:
    """Fallback market line when Football-Data hasn't published the match yet."""
    if not SOURCE_TRACKER_JSON.exists():
        return {}
    doc = json.loads(SOURCE_TRACKER_JSON.read_text(encoding="utf-8"))
    out = {}
    for e in doc.get("entries", []):
        m = e.get("market") or {}
        if m.get("p1") is not None:
            out[(e["home"], e["away"])] = (m["p1"], m["px"], m["p2"])
    return out


def season_matches(pool_match_ids: set[str]) -> list[dict]:
    """Walk-forward model cells + market line for every played pool match."""
    mcfg, rules = PROFILE.model, PROFILE.rules
    fx = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))["matches"]
    by_pair = {(m["home"], m["away"]): m["match_id"] for m in fx if m["match_id"] in pool_match_ids}
    rows = load_history_rows()
    alt = load_team_altitudes()
    odds_idx = fd.index(fd.load())
    tracker = _tracker_market()

    batches: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if (r["home"], r["away"]) in by_pair and r["date"] >= "2026-07-01":
            batches[_iso_week(r["date"])].append(r)

    out = []
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        elos, _ = replay_history(train, mcfg)
        _, fit, _ = profile_fit_rho(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                    half_life_days=mcfg.half_life_days, verbose=False)
        wcfg = effective_model_config(fit, mcfg)
        for r in batch:
            h, a = r["home"], r["away"]
            if h not in fit.strengths or a not in fit.strengths:
                continue
            o = fd.lookup(odds_idx, h, a, r["date"])
            market = ((o["fair_p1"], o["fair_px"], o["fair_p2"]) if o else tracker.get((h, a)))
            if market is None:
                continue
            odds = {f"{h}|{a}": {"p1": market[0], "px": market[1], "p2": market[2], "n_books": 1}}
            pred = predict_fixture({"match_id": None, "home": h, "away": a, "home_score": None},
                                   fit, elos, alt, wcfg, rules, odds=odds)
            cells = [(c["score"], c["prob"]) for c in pred["_cells"]]
            out.append({"match_id": by_pair[(h, a)], "home": h, "away": a,
                        "actual": f"{r['home_score']}-{r['away_score']}",
                        "ev_pick": pred["pick_exact"], "p_blend": (pred["p_home_win"], pred["p_draw"], pred["p_away_win"]),
                        "market": market, "cells": cells})
    return out


def audit(matches: list[dict], picks: dict[str, dict[str, str]]) -> list[dict]:
    rows = []
    for name, pp in picks.items():
        e = r = n = nx = 0
        for m in matches:
            pk = pp.get(m["match_id"])
            if not pk:
                continue
            dist = market_reweight(m["cells"], m["market"])
            e += expected_points(pk, dist)
            r += realized_points(pk, m["actual"])
            n += 1
            nx += outcome(pk) == 0
        if n:
            rows.append({"name": name, "n": n, "expected": e, "real": r, "luck": r - e,
                         "exp_per_match": e / n, "draw_picks": nx})
    rows.sort(key=lambda x: -x["exp_per_match"])
    return rows


def _policy_pick(policy: str, m: dict) -> str:
    if policy == "EV":
        return m["ev_pick"]
    if policy.startswith("X"):  # 1-1 cuando P(empate) del blend ≥ umbral
        return "1-1" if m["p_blend"][1] >= float(policy[1:]) else m["ev_pick"]
    if policy == "modal":
        return max(m["cells"], key=lambda c: c[1])[0]
    raise ValueError(policy)


def simulate_policies(matches: list[dict], picks: dict[str, dict[str, str]], standings: dict,
                      policies: list[str], horizon: int, sims: int, seed: int = 7) -> list[dict]:
    """Rest-of-tournament Monte-Carlo: resample played matches (with every rival's
    REAL pick on them), draw the score from the market-reweighted matrix, add to
    the current table. Common random numbers across policies."""
    you = standings["you"]
    start = {p["name"]: (p["points"], p["exactos"]) for p in standings["players"]}
    rivals = [n for n in start if n != you]
    base = []
    for m in matches:
        have = [picks.get(n, {}).get(m["match_id"]) for n in rivals]
        filled = [p for p in have if p]
        if len(filled) < 5:
            continue
        mode = Counter(filled).most_common(1)[0][0]
        dist = market_reweight(m["cells"], m["market"])
        base.append({**m, "rival_picks": [p or mode for p in have],
                     "scores": list(dist), "probs": np.array(list(dist.values()))})
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(base), size=(sims, horizon))
    sampled = np.empty((sims, horizon), dtype=object)
    for i, b in enumerate(base):
        mask = idx == i
        if mask.any():
            sampled[mask] = rng.choice(b["scores"], size=int(mask.sum()), p=b["probs"])

    def key(pts, ex):
        return pts * 1000 + ex

    rk = np.array([[key(*start[n]) for n in rivals]] * sims, dtype=float)
    memo: dict = {}
    for s in range(sims):
        for h in range(horizon):
            i, sc = idx[s, h], sampled[s, h]
            if (i, sc) not in memo:
                memo[(i, sc)] = np.array([key(realized_points(p, sc), p == sc)
                                          for p in base[i]["rival_picks"]], dtype=float)
            rk[s] += memo[(i, sc)]
    srt = np.sort(rk, axis=1)
    top1, top2 = srt[:, -1], srt[:, -2]
    shares = PROFILE.rules.prize_shares
    out = []
    for pol in policies:
        mine = np.full(sims, key(*start[you]), dtype=float)
        pm: dict = {}
        for s in range(sims):
            for h in range(horizon):
                i, sc = idx[s, h], sampled[s, h]
                if (i, sc) not in pm:
                    pk = _policy_pick(pol, base[i])
                    pm[(i, sc)] = key(realized_points(pk, sc), pk == sc)
                mine[s] += pm[(i, sc)]
        p1 = np.mean(mine > top1) + 0.5 * np.mean(mine == top1)
        p2 = np.mean((mine < top1) & (mine > top2)) + 0.5 * np.mean((mine < top1) & (mine == top2))
        prize = shares[0] * p1 + (shares[1] * p2 if len(shares) > 1 else 0.0)
        out.append({"policy": pol, "draw_picks": sum(outcome(_policy_pick(pol, b)) == 0 for b in base),
                    "exp_points": float((mine // 1000).mean() - start[you][0]),
                    "p1": float(p1), "p2": float(p2), "prize": float(prize)})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Auditoría del pool: puntos esperados vs reales.")
    ap.add_argument("--min-matches", type=int, default=0,
                    help="oculta jugadores con menos picks capturados que esto.")
    ap.add_argument("--policies", action="store_true",
                    help="simula el resto del torneo con varias políticas para tu boleto.")
    ap.add_argument("--sims", type=int, default=5000)
    args = ap.parse_args(argv)

    picks = json.loads(POOL_PICKS_JSON.read_text(encoding="utf-8"))["players"]
    standings = json.loads(POOL_STANDINGS_JSON.read_text(encoding="utf-8"))
    ids = {mid for pp in picks.values() for mid in pp}
    matches = season_matches(ids)
    rows = audit(matches, picks)
    you = standings.get("you")
    print(f"\nAuditoría del pool — {len(matches)} partidos jugados, vara = línea justa de "
          f"cierre del MERCADO (no el modelo).\n")
    print(f"{'jugador':<24} {'n':>3} {'esperados':>9} {'reales':>6} {'suerte':>7} "
          f"{'esp/partido':>11} {'empates':>7}")
    for r in rows:
        if r["n"] < args.min_matches:
            continue
        mark = "  ← tú" if r["name"] == you else ""
        print(f"{r['name']:<24} {r['n']:>3} {r['expected']:>9.1f} {r['real']:>6} "
              f"{r['luck']:>+7.1f} {r['exp_per_match']:>11.3f} {r['draw_picks']:>7}{mark}")
    print("\nsuerte = reales − esperados. Esperados por partido = calidad del boleto antes de "
          "patear.\nOjo: jugadores con picks faltantes en los exports tienen n menor.")

    if args.policies:
        horizon = standings["total_matches"] - standings["matches_resolved"]
        res = simulate_policies(matches, picks, standings, ["EV", "X0.29", "X0.28", "X0.27", "modal"],
                                horizon=horizon, sims=args.sims)
        print(f"\nPolíticas para el resto del torneo ({horizon} partidos, {args.sims} sims, "
              f"rivales con sus picks reales re-muestreados):")
        print(f"{'política':<8} {'empates':>7} {'pts esp':>7} {'P(1.º)':>7} {'P(2.º)':>7} {'premio esp':>10}")
        for r in res:
            print(f"{r['policy']:<8} {r['draw_picks']:>7} {r['exp_points']:>7.1f} {r['p1']:>7.2%} "
                  f"{r['p2']:>7.2%} {r['prize']:>10.2%}")


if __name__ == "__main__":
    main()
