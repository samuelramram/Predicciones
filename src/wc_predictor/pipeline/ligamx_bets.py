"""Value bets for a Liga MX jornada: model (no-odds) vs the market.

Compares the model's INDEPENDENT probability (Poisson+Elo, odds NOT in the
blend) against the de-vigged book price, and flags +EV bets with a conservative
¼-Kelly stake capped per bet. Line-shopping: the price shown is the BEST across
books. Markets: 1X2 + Over/Under 2.5.

This is a MEASUREMENT tool, not a tipster: the goal is to recover the Claude
spend, not to chase. The quiniela (vs 30 humans) is the real edge; here the
opponent is a book with vig, so the edges are thin and discipline is the point.

Run (needs odds_markets.json from ingest.ligamx_odds + a fit):
    python -m wc_predictor.pipeline.ligamx_bets --round j2 --bankroll 500
    python -m wc_predictor.pipeline.ligamx_bets --round j2 --edge 0.04 --kelly 0.25 --max-stake 0.02
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from wc_predictor.betting.value import find_value_bets
from wc_predictor.config import OUTPUTS_DIR
from wc_predictor.pipeline.ligamx import (
    FIXTURES_JSON,
    LIGAMX_DIR,
    PROFILE,
    ELO_JSON,
    STRENGTHS_JSON,
    load_team_altitudes,
    predict_fixture,
)
from wc_predictor.model.poisson_dc import load_fit

ODDS_MARKETS_JSON = LIGAMX_DIR / "odds_markets.json"


def compute_bets(round_spec: str, edge_min: float = 0.03, kelly_mult: float = 0.25,
                 max_stake: float = 0.02, total_line: float = 2.5) -> list:
    """The value bets for a round (sorted by edge desc). Returns [] when there is
    no market file or nothing clears the edge gate. Pure of printing/serialization
    so both the CLI and the boleto renderer can reuse it. Requires a fit +
    odds_markets.json; the model view is INDEPENDENT (odds=None) by construction."""
    mcfg, rules = PROFILE.model, PROFILE.rules
    if not STRENGTHS_JSON.exists() or not ODDS_MARKETS_JSON.exists():
        return []
    fit = load_fit(STRENGTHS_JSON)
    elos = {r["team"]: r["elo"]
            for r in json.loads(ELO_JSON.read_text(encoding="utf-8"))["teams"]}
    altitudes = load_team_altitudes()
    markets = json.loads(ODDS_MARKETS_JSON.read_text(encoding="utf-8"))["matches"]
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))

    spec = round_spec.strip().lower()
    if spec in ("all", ""):
        selected = fx_doc["matches"]
    elif spec.startswith("j") and spec[1:].isdigit():
        n = int(spec[1:])
        selected = [m for m in fx_doc["matches"] if m.get("jornada") == n]
    else:
        return []

    all_bets = []
    for fx in selected:
        market = markets.get(f"{fx['home']}|{fx['away']}")
        if market is None:
            continue
        p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=None)
        if "error" in p:
            continue
        model_1x2 = (p["p_home_win"], p["p_draw"], p["p_away_win"])
        all_bets.extend(find_value_bets(
            f"{fx['home']} vs {fx['away']}", model_1x2, p["_cells"], market,
            edge_min=edge_min, kelly_mult=kelly_mult, max_stake=max_stake,
            total_line=total_line,
        ))
    all_bets.sort(key=lambda b: -b.edge)
    return all_bets


def bets_payload(round_spec: str, bankroll: float = 500.0, edge_min: float = 0.03,
                 kelly_mult: float = 0.25, max_stake: float = 0.02,
                 total_line: float = 2.5) -> dict | None:
    """JSON-serializable bets bundle for a round, or None if no market file."""
    if not ODDS_MARKETS_JSON.exists():
        return None
    bets = compute_bets(round_spec, edge_min, kelly_mult, max_stake, total_line)
    return {
        "as_of": datetime.utcnow().isoformat() + "Z", "round": round_spec.strip().lower(),
        "params": {"bankroll": bankroll, "edge_min": edge_min, "kelly_mult": kelly_mult,
                   "max_stake": max_stake, "total_line": total_line},
        "bets": [
            {"match": b.match, "market": b.market, "selection": b.selection,
             "model_prob": round(b.model_prob, 4), "fair_prob": round(b.fair_prob, 4),
             "edge": round(b.edge, 4), "price": b.price, "book": b.book,
             "ev": round(b.ev, 4), "stake_frac": round(b.kelly_stake, 4),
             "stake_mxn": round(b.kelly_stake * bankroll, 2)}
            for b in bets
        ],
    }


def run(round_spec: str, bankroll: float, edge_min: float, kelly_mult: float,
        max_stake: float, total_line: float) -> None:
    if not STRENGTHS_JSON.exists():
        raise SystemExit(f"Falta {STRENGTHS_JSON}. Corre `pipeline.ligamx fit` primero.")
    if not ODDS_MARKETS_JSON.exists():
        raise SystemExit(f"Falta {ODDS_MARKETS_JSON}. Corre `ingest.ligamx_odds` primero.")
    spec = round_spec.strip().lower()
    all_bets = compute_bets(spec, edge_min, kelly_mult, max_stake, total_line)

    print(f"\nApuestas de valor {spec} — bankroll ${bankroll:.0f} · "
          f"edge≥{edge_min:.0%} · ¼-Kelly×{kelly_mult} · tope {max_stake:.0%}/apuesta")
    if not all_bets:
        print("  Sin valor: el modelo no le gana al mercado en ningún mercado cubierto. "
              "(Eso es sano — casi siempre es así vs un book afilado.)")
    else:
        print(f"  {'Partido':<26} {'Mercado':<9} {'Sel':<5} {'modelo':>7} {'justo':>6} "
              f"{'edge':>6} {'precio':>7} {'casa':<12} {'stake':>8} {'EV':>6}")
        for b in all_bets:
            stake_mxn = b.kelly_stake * bankroll
            print(f"  {b.match:<26} {b.market:<9} {b.selection:<5} "
                  f"{b.model_prob*100:>6.1f}% {b.fair_prob*100:>5.1f}% {b.edge*100:>5.1f}% "
                  f"{b.price:>7.2f} {(b.book or '-'):<12} "
                  f"${stake_mxn:>6.0f} {b.ev*100:>+5.1f}%")
        total_stake = sum(b.kelly_stake for b in all_bets) * bankroll
        print(f"\n  {len(all_bets)} apuestas · stake total ${total_stake:.0f} "
              f"({total_stake/bankroll*100:.1f}% del bankroll)")
        big = [b for b in all_bets if b.edge >= 0.08]
        if big:
            print(f"\n  ⚠ {len(big)} apuesta(s) con edge ≥8%: contra un mercado de ~20+ "
                  f"casas, un edge así casi siempre es ERROR DEL MODELO, no valor real "
                  f"(el backtest sin odds solo le gana ~8% a un baseline trivial → el "
                  f"modelo NO es más afilado que el mercado). Trátalas como medición, "
                  f"no como certeza; registra el CLV y sube --edge si dudas.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUTPUTS_DIR / f"ligamx_bets_{spec}.json"
    dst.write_text(json.dumps(
        bets_payload(spec, bankroll, edge_min, kelly_mult, max_stake, total_line),
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {dst}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apuestas de valor Liga MX.")
    parser.add_argument("--round", default="all", help="j1..j17 | all")
    parser.add_argument("--bankroll", type=float, default=500.0, help="bankroll en MXN.")
    parser.add_argument("--edge", type=float, default=0.03, help="edge mínimo (modelo − justo).")
    parser.add_argument("--kelly", type=float, default=0.25, help="fracción de Kelly (¼ por defecto).")
    parser.add_argument("--max-stake", type=float, default=0.02, help="tope de stake por apuesta.")
    parser.add_argument("--total-line", type=float, default=2.5, help="línea de O/U a evaluar.")
    args = parser.parse_args(argv)
    run(args.round, args.bankroll, args.edge, args.kelly, args.max_stake, args.total_line)


if __name__ == "__main__":
    main()
