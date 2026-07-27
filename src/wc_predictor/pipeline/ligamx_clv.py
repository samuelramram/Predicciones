"""CLV ledger for the Liga MX value bets — log, close, settle, report.

The season-long record that says whether the model's betting edge is REAL. Flow:

    # 1) When you place (or would place) the jornada's value bets:
    python -m wc_predictor.pipeline.ligamx_clv log --round j3

    # 2) Right before kickoff, after refreshing odds (ingest.ligamx_odds),
    #    capture the closing line for the open bets:
    python -m wc_predictor.pipeline.ligamx_clv close

    # 3) Once results are in (refresh fixtures / ingest), settle W/L + P&L:
    python -m wc_predictor.pipeline.ligamx_clv settle

    # 4) Read the verdict (avg CLV, % beating the close, realized ROI):
    python -m wc_predictor.pipeline.ligamx_clv report

The ledger is versioned at data/ligamx/clv_ledger.json (it's the record, not an
ephemeral artifact). CLV converges far faster than P&L, so the headline is the
average CLV: positive over a season ⇒ the model finds genuine value; negative ⇒
the "edges" were noise and the quiniela is where the real advantage lives.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from wc_predictor.betting.clv import (LedgerEntry, entry_from_dict, entry_to_dict,
                                      settle_profit, summarize)
from wc_predictor.config import OUTPUTS_DIR
from wc_predictor.pipeline.ligamx import FIXTURES_JSON, LIGAMX_DIR
from wc_predictor.pipeline.ligamx_bets import compute_bets

LEDGER_JSON = LIGAMX_DIR / "clv_ledger.json"
ODDS_MARKETS_JSON = LIGAMX_DIR / "odds_markets.json"


def _load_ledger() -> list[LedgerEntry]:
    if not LEDGER_JSON.exists():
        return []
    doc = json.loads(LEDGER_JSON.read_text(encoding="utf-8"))
    return [entry_from_dict(e) for e in doc.get("entries", [])]


def _save_ledger(entries: list[LedgerEntry]) -> None:
    LEDGER_JSON.write_text(json.dumps(
        {"updated_at": datetime.utcnow().isoformat() + "Z",
         "entries": [entry_to_dict(e) for e in entries]},
        indent=2, ensure_ascii=False), encoding="utf-8")


def _market_lookup(match: str, market: str, selection: str, markets: dict):
    """(fair_prob, best_price) for a selection from odds_markets.json, or (None, None)."""
    home, _, away = match.partition(" vs ")
    m = markets.get(f"{home}|{away}")
    if not m:
        return None, None
    if market == "1X2":
        fair = (m.get("h2h") or {}).get("fair") or {}
        best = (m.get("h2h") or {}).get("best") or {}
        return fair.get(selection), (best.get(selection) or {}).get("price")
    if market.startswith("O/U"):
        line = market.split()[-1]
        t = (m.get("totals") or {}).get(line) or {}
        key = "over" if selection.lower().startswith("o") else "under"
        return (t.get("fair") or {}).get(key), (t.get("best") or {}).get(key, {}).get("price")
    return None, None


def cmd_log(round_spec: str, bankroll: float, edge_min: float, kelly_mult: float,
            max_stake: float, total_line: float) -> None:
    bets = compute_bets(round_spec, edge_min, kelly_mult, max_stake, total_line)
    if not bets:
        print(f"Sin apuestas de valor para {round_spec} (nada que registrar).")
        return
    ledger = _load_ledger()
    have = {e.key() for e in ledger}
    now = datetime.utcnow().isoformat() + "Z"
    added = 0
    for b in bets:
        e = LedgerEntry(
            round=round_spec.strip().lower(), match=b.match, market=b.market,
            selection=b.selection, model_prob=round(b.model_prob, 4),
            entry_fair_prob=round(b.fair_prob, 4), entry_price=b.price,
            entry_book=b.book, stake_mxn=round(b.kelly_stake * bankroll, 2), logged_at=now,
        )
        if e.key() in have:
            continue
        ledger.append(e)
        have.add(e.key())
        added += 1
    _save_ledger(ledger)
    print(f"Registradas {added} apuestas nuevas de {round_spec} "
          f"({len(bets) - added} ya estaban). Ledger: {len(ledger)} entradas.")


def cmd_close() -> None:
    if not ODDS_MARKETS_JSON.exists():
        raise SystemExit(f"Falta {ODDS_MARKETS_JSON}. Corre `ingest.ligamx_odds` justo antes "
                         "del cierre para capturar la línea.")
    markets = json.loads(ODDS_MARKETS_JSON.read_text(encoding="utf-8"))["matches"]
    ledger = _load_ledger()
    now = datetime.utcnow().isoformat() + "Z"
    n = 0
    for e in ledger:
        if e.close_fair_prob is not None:
            continue
        fair, price = _market_lookup(e.match, e.market, e.selection, markets)
        if fair is None:
            continue
        e.close_fair_prob = round(float(fair), 4)
        e.close_price = round(float(price), 3) if price else None
        e.closed_at = now
        n += 1
    _save_ledger(ledger)
    print(f"Cerradas {n} entradas con la línea actual (corre esto cerca del kickoff).")


def _settle_result(match: str, market: str, selection: str, fx_by_match: dict) -> str | None:
    fx = fx_by_match.get(match)
    if not fx or fx.get("home_score") is None:
        return None
    hs, as_ = fx["home_score"], fx["away_score"]
    if market == "1X2":
        outcome = "1" if hs > as_ else ("X" if hs == as_ else "2")
        return "win" if selection == outcome else "loss"
    if market.startswith("O/U"):
        line = float(market.split()[-1])
        total = hs + as_
        over = total > line
        return "win" if (selection.lower().startswith("o") == over) else "loss"
    return None


def cmd_settle() -> None:
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    fx_by_match = {f"{m['home']} vs {m['away']}": m for m in fx_doc["matches"]}
    ledger = _load_ledger()
    n = 0
    for e in ledger:
        if e.result is not None:
            continue
        res = _settle_result(e.match, e.market, e.selection, fx_by_match)
        if res is None:
            continue
        e.result = res
        e.profit_mxn = round(settle_profit(e.entry_price, e.stake_mxn, res), 2)
        n += 1
    _save_ledger(ledger)
    print(f"Liquidadas {n} entradas con resultados conocidos.")


def cmd_report() -> None:
    from wc_predictor.pipeline.ligamx_html import render_clv
    ledger = _load_ledger()
    if not ledger:
        print("Ledger vacío. Corre `ligamx_clv log --round jN` primero.")
        return
    stats = summarize(ledger)
    print(f"\nCLV ledger — {stats['n']} apuestas ({stats['n_closed']} con línea de cierre, "
          f"{stats['n_settled']} liquidadas)")
    clv = stats["avg_clv_pct"]
    beat = stats["pct_beat_close"]
    print(f"  CLV promedio: {clv:+.2f}%" if clv is not None else "  CLV promedio: — (cierra líneas primero)")
    if beat is not None:
        print(f"  Le ganó a la línea de cierre: {beat:.0f}% de las apuestas")
    if stats["n_settled"]:
        print(f"  P&L realizado: ${stats['profit_mxn']:+.0f} sobre ${stats['staked_mxn']:.0f} "
              f"({stats['roi_pct']:+.1f}% ROI · {stats['wins']}W-{stats['losses']}L)")
    print("  Por mercado:")
    for mkt, s in stats["by_market"].items():
        c = f"{s['avg_clv_pct']:+.2f}%" if s["avg_clv_pct"] is not None else "—"
        print(f"    {mkt:<10} n={s['n']:<3} CLV {c}")
    closed = [e for e in ledger if e.close_price is not None]
    same_snapshot = bool(closed) and all(e.close_price == e.entry_price for e in closed)
    verdict = ("registra más jornadas para un veredicto" if clv is None or stats["n_closed"] < 10
               else "CLV ~0: capturaste el cierre en el mismo instante que el log — corre `close` "
                    "cerca del kickoff para medir el movimiento real"
               if same_snapshot and abs(clv) < 0.05
               else "edge REAL — el modelo le gana a la línea de cierre" if clv > 0
               else "sin edge — concentra la energía en la quiniela")
    print(f"  Veredicto: {verdict}")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "ligamx_clv.json").write_text(
        json.dumps({"stats": stats, "entries": [entry_to_dict(e) for e in ledger]},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    html = render_clv(stats, [entry_to_dict(e) for e in ledger])
    (OUTPUTS_DIR / "ligamx_clv.html").write_text(html, encoding="utf-8")
    print(f"  wrote {OUTPUTS_DIR / 'ligamx_clv.json'}\n  wrote {OUTPUTS_DIR / 'ligamx_clv.html'}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Ledger de CLV para las apuestas Liga MX.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("log", help="Registra las apuestas de valor de una ronda.")
    pl.add_argument("--round", required=True, help="j1..j17")
    pl.add_argument("--bankroll", type=float, default=500.0)
    pl.add_argument("--edge", type=float, default=0.03)
    pl.add_argument("--kelly", type=float, default=0.25)
    pl.add_argument("--max-stake", type=float, default=0.02)
    pl.add_argument("--total-line", type=float, default=2.5)
    sub.add_parser("close", help="Captura la línea de cierre para las abiertas (cerca del kickoff).")
    sub.add_parser("settle", help="Liquida W/L + P&L con los resultados conocidos.")
    sub.add_parser("report", help="Resumen: CLV promedio, % que le gana al cierre, ROI + HTML.")
    args = p.parse_args(argv)

    if args.cmd == "log":
        cmd_log(args.round, args.bankroll, args.edge, args.kelly, args.max_stake, args.total_line)
    elif args.cmd == "close":
        cmd_close()
    elif args.cmd == "settle":
        cmd_settle()
    elif args.cmd == "report":
        cmd_report()


if __name__ == "__main__":
    main()
