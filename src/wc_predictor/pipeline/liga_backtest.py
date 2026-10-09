"""Backtest de la liga de bots — walk-forward, con momios históricos REALES de cierre.

Igual que ``ligamx_backtest`` (refit semanal solo con partidos anteriores: cero
look-ahead), pero ahora cada partido lo pican varios bots y además hay mercado:
``data/ligamx/historical_odds.csv`` (``ingest.ligamx_fd_odds``) trae la línea justa
de cierre y el precio promedio de cierre de cada partido desde 2020.

Solo se puntúan partidos donde TODOS los bots pueden picar (modelo con fuerzas +
momio encontrado), así la tabla compara a todos sobre exactamente los mismos
partidos.

Bots (ver ``liga.bots``): estadistico (sin mercado), calibrado (blend de
producción), borrego (mercado puro). ``--sweep`` agrega variantes del calibrado
con otro peso de mercado — así se mide por fin el ``blend_odds_weight`` (0.55),
que hasta hoy era un default de literatura "no backtesteable".

Bankroll: FICTICIO, 1,000 por bot, apuesta plana de 10 al precio PROMEDIO de
cierre cuando el bot ve valor. No es dinero real ni una recomendación de apuesta.

Run:
    python -m wc_predictor.pipeline.liga_backtest
    python -m wc_predictor.pipeline.liga_backtest --since 2025-01-01 --sweep 0.3,0.75,0.9
    python -m wc_predictor.pipeline.liga_backtest --no-fit-rho      # más rápido
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import replace

from wc_predictor.ingest import ligamx_fd_odds as fd
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.liga.bots import borrego_ticket, ticket_from_prediction, typical_scores
from wc_predictor.liga.scoring import BotRecord, paired_diff, table
from wc_predictor.model.poisson_dc import fit_dc_model, profile_fit_rho
from wc_predictor.pipeline.ligamx import (effective_model_config, load_history_rows,
                                          load_team_altitudes, predict_fixture)
from wc_predictor.pipeline.ligamx_backtest import _iso_week
from wc_predictor.ratings.elo import replay_history

PROFILE = LIGAMX_APERTURA_PROFILE
OUT_JSON = PROFILE.data_dir.parent.parent / "outputs" / "liga_backtest.json"


def run(since: str, sweep: tuple[float, ...] = (), mcfg=None, quiet: bool = False,
        min_train: int = 100) -> dict:
    mcfg = mcfg or PROFILE.model
    rules = PROFILE.rules
    rows = load_history_rows()
    altitudes = load_team_altitudes()
    odds_idx = fd.index(fd.load())

    prod_w = mcfg.blend_odds_weight
    names = ["estadistico", "calibrado", "borrego"] + [f"calibrado_w{w:g}" for w in sweep]
    rec = {n: BotRecord(n) for n in names}

    test = [r for r in rows if r["date"] >= since]
    batches: dict[str, list[dict]] = defaultdict(list)
    for r in test:
        batches[_iso_week(r["date"])].append(r)

    skipped = {"sin_historial": 0, "sin_fuerzas": 0, "sin_momio": 0}
    for wk in sorted(batches):
        batch = batches[wk]
        first = min(r["date"] for r in batch)
        train = [r for r in rows if r["date"] < first]
        if len(train) < min_train:
            skipped["sin_historial"] += len(batch)
            continue
        elos, _ = replay_history(train, mcfg)
        if mcfg.fit_rho:
            _, fit, _ = profile_fit_rho(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                                        half_life_days=mcfg.half_life_days, verbose=False)
        else:
            fit = fit_dc_model(train, mcfg, ridge_lambda=mcfg.ridge_lambda,
                               half_life_days=mcfg.half_life_days, verbose=False)
        wk_mcfg = effective_model_config(fit, mcfg)
        typical = typical_scores(train)

        for r in batch:
            h, a = r["home"], r["away"]
            if h not in fit.strengths or a not in fit.strengths:
                skipped["sin_fuerzas"] += 1
                continue
            o = fd.lookup(odds_idx, h, a, r["date"])
            if o is None:
                skipped["sin_momio"] += 1
                continue
            market = (o["fair_p1"], o["fair_px"], o["fair_p2"])
            prices = (o["avg_o1"], o["avg_ox"], o["avg_o2"])
            odds = {f"{h}|{a}": {"p1": market[0], "px": market[1], "p2": market[2], "n_books": 1}}
            fx = {"match_id": None, "home": h, "away": a, "home_score": None}
            lig = r.get("stage") == "liguilla"

            tickets = {
                "estadistico": ticket_from_prediction(
                    predict_fixture(fx, fit, elos, altitudes, wk_mcfg, rules, odds=None, liguilla=lig)),
                "calibrado": ticket_from_prediction(
                    predict_fixture(fx, fit, elos, altitudes, wk_mcfg, rules, odds=odds, liguilla=lig)),
                "borrego": borrego_ticket(market, typical),
            }
            for w in sweep:
                wm = replace(wk_mcfg, blend_odds_weight=w)
                tickets[f"calibrado_w{w:g}"] = ticket_from_prediction(
                    predict_fixture(fx, fit, elos, altitudes, wm, rules, odds=odds, liguilla=lig))

            for n, t in tickets.items():
                rec[n].add(t.pick_1x2, t.pick_exact, t.probs,
                           r["home_score"], r["away_score"], rules, prices=prices)

    standings = table(list(rec.values()))
    # Is each bot's gap vs production (calibrado) real or luck? Paired, same matches.
    ref = rec["calibrado"]
    vs_prod = {}
    for n, r in rec.items():
        if n == "calibrado" or r.n < 2:
            continue
        pts = paired_diff(r.match_points, ref.match_points)
        bri = paired_diff(r.match_brier, ref.match_brier)
        vs_prod[n] = {"points_diff": pts["total_diff"], "points_z": round(pts["z"], 2),
                      "brier_diff": round(bri["mean_diff"], 5), "brier_z": round(bri["z"], 2)}
    result = {"since": since, "prod_odds_weight": prod_w, "sweep": list(sweep),
              "skipped": skipped, "standings": standings, "vs_calibrado": vs_prod}
    if not quiet:
        _print(result)
    return result


def _print(res: dict) -> None:
    st = res["standings"]
    n = st[0]["n"] if st else 0
    print(f"\nLiga de bots — backtest walk-forward desde {res['since']}: {n} partidos "
          f"(los mismos para todos). Omitidos: {res['skipped']}.")
    print(f"Calibrado = blend de producción (peso mercado {res['prod_odds_weight']:g}). "
          f"Bankroll FICTICIO: 1,000 c/u, apuesta plana 10 al precio promedio de cierre.\n")
    hdr = f"{'#':>2} {'bot':<16} {'pts':>5} {'p/p':>6} {'exactos':>7} {'Brier':>7} {'logloss':>8} " \
          f"{'bankroll':>9} {'apuestas':>8} {'ROI':>7}"
    print(hdr)
    print("-" * len(hdr))
    for i, s in enumerate(st, 1):
        print(f"{i:>2} {s['bot']:<16} {s['points']:>5} {s['pts_per_match']:>6.3f} {s['exactos']:>7} "
              f"{s['brier']:>7.4f} {s['log_loss']:>8.4f} {s['bankroll']:>9.2f} {s['bets']:>8} "
              f"{s['roi']*100:>6.1f}%")
    print("\nBrier = suma sobre 1/X/2 (uniforme 0.667; más bajo es mejor).")
    print("\n¿La diferencia contra el calibrado (producción) es real o suerte? Pareado, mismos partidos:")
    for n, v in res["vs_calibrado"].items():
        verdict = "señal" if abs(v["points_z"]) >= 2 else "dentro de la suerte"
        print(f"   {n:<16} puntos {v['points_diff']:+5.0f} (z={v['points_z']:+.2f}, {verdict}) · "
              f"Brier {v['brier_diff']:+.5f} (z={v['brier_z']:+.2f})")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Backtest de la liga de bots (Liga MX).")
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--sweep", default="", help="pesos de mercado extra para el calibrado, ej. 0.3,0.75,0.9")
    ap.add_argument("--no-fit-rho", dest="fit_rho", action="store_false", default=True)
    ap.add_argument("--out", default=str(OUT_JSON))
    args = ap.parse_args(argv)
    sweep = tuple(float(x) for x in args.sweep.split(",") if x.strip())
    mcfg = PROFILE.model if args.fit_rho else replace(PROFILE.model, fit_rho=False)
    res = run(args.since, sweep=sweep, mcfg=mcfg)
    from pathlib import Path
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
