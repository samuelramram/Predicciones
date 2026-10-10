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
from dataclasses import replace
from pathlib import Path
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

from wc_predictor.config import DATA_DIR
from wc_predictor.ingest import europa_fd
from wc_predictor.liga.europa import (EUROPA_MODEL, RULES, XG_WEIGHT, bot_view, load_override,
                                      promoted_prior, replay_promoted, season_turnover,
                                      top_teams, with_xg)
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
               sweep: tuple[float, ...] = (), opts: dict | None = None) -> dict:
    """``opts`` (experiments, all off by default except honest odds):
    odds: "pre" (line the live bot would see; default) | "close";
    half_life: int days; promoted: bool; xg: float weight of xG in the Poisson target."""
    opts = {"odds": "pre", **(opts or {})}
    if opts.get("half_life"):
        mcfg = replace(mcfg, half_life_days=int(opts["half_life"]))
    rows = [r for r in europa_fd.load() if r["league"] == code]
    if opts["odds"] == "pre":
        # Bots bet and blend ONLY with the pre-match line (what the live bot sees).
        # A market missing pre-match (≈40 corrupt AH rows) is simply not traded.
        rows = [{**r, **{k: r.get(f"{k}_pre") for k in europa_fd.MARKET_KEYS
                         if k != "fair_source"}} for r in rows]
    fit_rows = rows
    if opts.get("xg"):
        from wc_predictor.ingest import understat_xg
        fit_rows = with_xg(rows, understat_xg.index(understat_xg.load()), float(opts["xg"]))
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
    turnover = season_turnover(season_teams)
    last_fit = None
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        if len(train) < min_train:
            continue
        fit_train = [r for r in fit_rows if r["date"] < first]
        season = batch[0]["season"]
        prior = promoted_prior(last_fit, turnover, season) if opts.get("promoted") else None
        # rho profiled once per season (costly); weekly refits reuse it.
        if season not in rho_by_season:
            rho, fit, _ = profile_fit_rho(fit_train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                          half_life_days=mcfg.half_life_days, verbose=False,
                                          prior=prior)
            rho_by_season[season] = rho
        else:
            fit = fit_dc_model(fit_train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                               half_life_days=mcfg.half_life_days,
                               rho=rho_by_season[season], verbose=False, prior=prior)
        last_fit = fit
        wk_mcfg = effective_model_config(fit, mcfg)
        if opts.get("promoted"):
            elos = replay_promoted(train, mcfg, turnover)
        else:
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
                       "top": r["home"] in top or r["away"] in top,
                       "key": f"{code}|{r['date']}|{r['home']}|{r['away']}"}
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


def compare(a_path: str, b_path: str, bots: tuple[str, ...] = ("estadistico", "calibrado")) -> dict:
    """Paired comparison of two backtest runs (variant B minus base A), per bot,
    on the matches both scored. Negative Brier diff = B is better calibrated."""
    a = json.loads(Path(a_path).read_text(encoding="utf-8"))
    b = json.loads(Path(b_path).read_text(encoding="utf-8"))
    out = {}
    for bot in bots:
        ra = {r["key"]: r for r in a[bot]}
        rb = {r["key"]: r for r in b[bot]}
        keys = [k for k in ra if k in rb]
        res = {"n": len(keys)}
        for name, f in (("puntos", "pts"), ("brier_1x2", "b1x2"), ("brier_ou25", "bou"),
                        ("brier_btts", "bbtts")):
            d = paired_diff([rb[k][f] for k in keys], [ra[k][f] for k in keys])
            res[name] = {"diff_total": round(d["total_diff"], 3), "z": round(d["z"], 2)}
        for m in MARKETS:
            d = paired_diff([rb[k].get(f"p_{m}") or 0.0 for k in keys],
                            [ra[k].get(f"p_{m}") or 0.0 for k in keys])
            res[f"ganancia_{m}"] = {"diff_total": round(d["total_diff"], 1), "z": round(d["z"], 2)}
        out[bot] = res
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2024-07-01")
    ap.add_argument("--leagues", nargs="*", default=list(europa_fd.LEAGUES))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--sweep", type=float, nargs="*", default=[],
                    help="pesos de mercado extra a probar como bots calibrado_w<peso>")
    ap.add_argument("--odds", choices=("pre", "close"), default="pre",
                    help="momios previos (lo que ve el bot en vivo; default) o de cierre")
    ap.add_argument("--half-life", type=int, default=None, help="días (default: el del modelo)")
    ap.add_argument("--promoted", action="store_true", help="prior de recién ascendidos")
    ap.add_argument("--xg", type=float, default=XG_WEIGHT,
                    help=f"peso del xG en el Poisson (default producción {XG_WEIGHT}; 0 = solo goles)")
    ap.add_argument("--rows-out", default=None, help="guarda el detalle por partido (para --compare)")
    ap.add_argument("--compare", nargs=2, metavar=("BASE", "VARIANTE"),
                    help="compara dos --rows-out con prueba pareada y sale")
    ap.add_argument("--out", default=str(OUT_JSON))
    args = ap.parse_args(argv)
    if args.compare:
        res = compare(*args.compare)
        for bot, r in res.items():
            print(f"{bot} ({r['n']} partidos, variante − base):")
            for k, v in r.items():
                if k != "n":
                    print(f"  {k:<16} {v['diff_total']:+10} (z={v['z']:+.2f})")
        return
    opts = {"odds": args.odds, "half_life": args.half_life, "promoted": args.promoted,
            "xg": args.xg}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        n = len(args.leagues)
        results = list(ex.map(run_league, args.leagues, [args.since] * n, [EUROPA_MODEL] * n,
                              [300] * n, [tuple(args.sweep)] * n, [opts] * n))
    report = aggregate(results)
    report["since"] = args.since
    report["opts"] = opts
    _print(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n→ {out}")
    if args.rows_out:
        rows = {b: [row for res in results for row in res["recs"][b]["rows"]]
                for b in results[0]["recs"]}
        Path(args.rows_out).write_text(json.dumps(rows), encoding="utf-8")
        print(f"→ {args.rows_out}")


if __name__ == "__main__":
    main()
