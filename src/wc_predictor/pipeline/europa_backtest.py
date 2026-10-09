"""Backtest walk-forward de la liga de bots en las 5 ligas top de Europa.

Por liga y por semana: re-ajuste Poisson·DC + Elo SOLO con partidos anteriores,
predicción de la semana, y cada bot juega todos los mercados con precios de
cierre promedio (dinero ficticio). Se reporta todo, y aparte el subconjunto
"top" (partidos con al menos un equipo del top-3 Elo de su liga), que es el que
juega Samuel.

Run:
    python -m wc_predictor.pipeline.europa_backtest                  # desde 2024-07-01
    python -m wc_predictor.pipeline.europa_backtest --leagues E0 SP1 --since 2025-07-01
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

from wc_predictor.config import DATA_DIR
from wc_predictor.ingest import europa_fd
from wc_predictor.liga.europa import EUROPA_MODEL, RULES, bot_view, load_override, top_teams
from wc_predictor.liga.markets import (MarketBankroll, ah_expected_returns, ah_return,
                                       binary_brier, simple_market)
from wc_predictor.liga.scoring import brier, outcome_of, paired_diff
from wc_predictor.model.poisson_dc import fit_dc_model, profile_fit_rho
from wc_predictor.pipeline.ligamx import effective_model_config
from wc_predictor.ratings.elo import replay_history
from wc_predictor.scoring.quiniela import score_actual

OUT_JSON = DATA_DIR.parent / "outputs" / "europa_backtest.json"
MARKETS = ("1x2", "ou25", "ah")


def _iso_week(d: str) -> str:
    y, w, _ = datetime.strptime(d, "%Y-%m-%d").date().isocalendar()
    return f"{y}-W{w:02d}"


def _bots(mcfg, sweep: tuple[float, ...] = ()) -> dict[str, float]:
    bots = {"estadistico": 0.0, "calibrado": mcfg.blend_odds_weight, "borrego": 1.0}
    bots.update({f"calibrado_w{w:g}": w for w in sweep})
    return bots


class _Rec:
    def __init__(self, name: str):
        self.name = name
        self.rows: list[dict] = []   # per match: pts, brier1x2, brier_ou, brier_btts, profits, top
        self.books = {m: MarketBankroll(m) for m in MARKETS}


def run_league(code: str, since: str, mcfg=EUROPA_MODEL, min_train: int = 300,
               sweep: tuple[float, ...] = ()) -> dict:
    rows = [r for r in europa_fd.load() if r["league"] == code]
    override = load_override()
    season_teams: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        season_teams[r["season"]] |= {r["home"], r["away"]}
    test = [r for r in rows if r["date"] >= since]
    batches: dict[str, list[dict]] = defaultdict(list)
    for r in test:
        batches[_iso_week(r["date"])].append(r)

    recs = {b: _Rec(b) for b in _bots(mcfg, sweep)}
    rho_by_season: dict[str, float] = {}
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        if len(train) < min_train:
            continue
        season = batch[0]["season"]
        # rho profiled once per season (costly); weekly refits reuse it.
        if season not in rho_by_season:
            rho, fit, _ = profile_fit_rho(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                          half_life_days=mcfg.half_life_days, verbose=False)
            rho_by_season[season] = rho
        else:
            fit = fit_dc_model(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                               half_life_days=mcfg.half_life_days,
                               rho=rho_by_season[season], verbose=False)
        wk_mcfg = effective_model_config(fit, mcfg)
        elos, _ = replay_history(train, mcfg)
        top = set(top_teams(elos, season_teams[season], 3, code, override))

        for r in batch:
            mkt = (r["fair_p1"], r["fair_px"], r["fair_p2"]) if r["fair_p1"] is not None else None
            views = {b: bot_view(r["home"], r["away"], fit, elos, wk_mcfg, mkt,
                                 r["fair_over25"], w) for b, w in _bots(mcfg, sweep).items()}
            if any(v is None for v in views.values()):
                continue
            hs, as_ = r["home_score"], r["away_score"]
            actual = outcome_of(hs, as_)
            over = hs + as_ > 2.5
            btts = hs > 0 and as_ > 0
            for b, v in views.items():
                rec = recs[b]
                row = {"pts": score_actual(hs, as_, v.pick_1x2, v.pick_exact, RULES),
                       "b1x2": brier(v.probs, actual),
                       "bou": binary_brier(v.p_over25, over),
                       "bbtts": binary_brier(v.p_btts, btts),
                       "top": r["home"] in top or r["away"] in top}
                # 1X2 at average closing prices
                if r["avg_o1"]:
                    e, z = simple_market(dict(zip("1X2", v.probs)),
                                         {"1": r["avg_o1"], "X": r["avg_ox"], "2": r["avg_o2"]},
                                         actual)
                    row["p_1x2"] = rec.books["1x2"].settle(e, z)
                if r["avg_over25"]:
                    e, z = simple_market({"over": v.p_over25, "under": 1 - v.p_over25},
                                         {"over": r["avg_over25"], "under": r["avg_under25"]},
                                         "over" if over else "under")
                    row["p_ou25"] = rec.books["ou25"].settle(e, z)
                if r["ah_line"] is not None and r["avg_ahh"]:
                    e = ah_expected_returns(v.cells, r["ah_line"], r["avg_ahh"], r["avg_aha"])
                    z = {"home": ah_return(hs - as_, r["ah_line"], r["avg_ahh"]),
                         "away": ah_return(as_ - hs, -r["ah_line"], r["avg_aha"])}
                    row["p_ah"] = rec.books["ah"].settle(e, z)
                rec.rows.append(row)
    return {"league": code, "rho": rho_by_season,
            "recs": {b: {"rows": rec.rows, "books": {m: bk.summary() for m, bk in rec.books.items()}}
                     for b, rec in recs.items()}}


def _summ(rows: list[dict]) -> dict:
    n = max(len(rows), 1)
    out = {"n": len(rows), "points": sum(r["pts"] for r in rows),
           "exactos": sum(r["pts"] >= RULES.points_exact for r in rows),
           "brier_1x2": round(sum(r["b1x2"] for r in rows) / n, 4),
           "brier_ou25": round(sum(r["bou"] for r in rows) / n, 4),
           "brier_btts": round(sum(r["bbtts"] for r in rows) / n, 4)}
    for m in MARKETS:
        prof = [r.get(f"p_{m}") or 0.0 for r in rows]
        bets = sum(1 for r in rows if r.get(f"p_{m}") is not None)
        out[f"profit_{m}"] = round(sum(prof), 1)
        out[f"bets_{m}"] = bets
        out[f"roi_{m}"] = round(sum(prof) / (10.0 * bets), 4) if bets else 0.0
    return out


def aggregate(results: list[dict]) -> dict:
    bots = list(results[0]["recs"])
    allrows = {b: [row for res in results for row in res["recs"][b]["rows"]] for b in bots}
    report: dict = {"overall": {}, "top": {}, "by_league": {}, "vs_calibrado": {}}
    for b in bots:
        report["overall"][b] = _summ(allrows[b])
        report["top"][b] = _summ([r for r in allrows[b] if r["top"]])
    for res in results:
        report["by_league"][res["league"]] = {b: _summ(res["recs"][b]["rows"]) for b in bots}
    ref = allrows["calibrado"]
    for b in bots:
        if b == "calibrado":
            continue
        cmp = {}
        for key, field_ in (("points", "pts"), ("brier_1x2", "b1x2"), ("brier_ou25", "bou")):
            d = paired_diff([r[field_] for r in allrows[b]], [r[field_] for r in ref])
            cmp[key] = {"total_diff": round(d["total_diff"], 3), "z": round(d["z"], 2)}
        for m in MARKETS:
            d = paired_diff([r.get(f"p_{m}") or 0.0 for r in allrows[b]],
                            [r.get(f"p_{m}") or 0.0 for r in ref])
            cmp[f"profit_{m}"] = {"total_diff": round(d["total_diff"], 1), "z": round(d["z"], 2)}
        report["vs_calibrado"][b] = cmp
    report["rho"] = {res["league"]: res["rho"] for res in results}
    return report


def _print(report: dict) -> None:
    for scope in ("overall", "top"):
        print(f"\n== {scope.upper()} ==")
        print(f"{'bot':<12}{'n':>6}{'pts':>6}{'exac':>6}{'B1x2':>8}{'BOU':>8}{'BTTS':>8}"
              + "".join(f"{'ROI ' + m:>12}" for m in MARKETS))
        for b, s in report[scope].items():
            print(f"{b:<12}{s['n']:>6}{s['points']:>6}{s['exactos']:>6}{s['brier_1x2']:>8.4f}"
                  f"{s['brier_ou25']:>8.4f}{s['brier_btts']:>8.4f}"
                  + "".join(f"{s[f'roi_{m}']*100:>+7.1f}%/{s[f'bets_{m}']:<4}" for m in MARKETS))
    print("\n== vs calibrado (z pareado; |z|<2 = ruido) ==")
    for b, c in report["vs_calibrado"].items():
        print(f"  {b}: " + ", ".join(f"{k} {v['total_diff']:+} (z={v['z']:+.2f})" for k, v in c.items()))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2024-07-01")
    ap.add_argument("--leagues", nargs="*", default=list(europa_fd.LEAGUES))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--sweep", type=float, nargs="*", default=[],
                    help="pesos de mercado extra a probar como bots calibrado_w<peso>")
    ap.add_argument("--out", default=str(OUT_JSON))
    args = ap.parse_args(argv)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        n = len(args.leagues)
        results = list(ex.map(run_league, args.leagues, [args.since] * n, [EUROPA_MODEL] * n,
                              [300] * n, [tuple(args.sweep)] * n))
    report = aggregate(results)
    report["since"] = args.since
    _print(report)
    from pathlib import Path
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
