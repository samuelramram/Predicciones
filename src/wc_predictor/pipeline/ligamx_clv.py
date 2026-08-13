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
from wc_predictor.pipeline.ligamx_bets import (
    compute_bets,
    played_stake_mxn,
    DEFAULT_MIN_STAKE,
)

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
            max_stake: float, total_line: float, min_stake: float = 0.0) -> None:
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
            entry_book=b.book,
            stake_mxn=played_stake_mxn(b.kelly_stake, bankroll, min_stake), logged_at=now,
        )
        if e.key() in have:
            continue
        ledger.append(e)
        have.add(e.key())
        added += 1
    _save_ledger(ledger)
    print(f"Registradas {added} apuestas nuevas de {round_spec} "
          f"({len(bets) - added} ya estaban). Ledger: {len(ledger)} entradas.")


def log_boleto(payload: dict) -> int:
    """Registra en el ledger el boleto POR CASA que DE VERDAD apostaste — casa,
    precio y stake reales, no la medición all-books. `payload` es el dict que
    devuelve `per_house_ticket` (mode=="per_house"). Devuelve cuántas entradas
    nuevas se agregaron (idempotente por (round, match, market, selection))."""
    ledger = _load_ledger()
    # Book-aware dedup: the same selection placed at BOTH houses is two real bets,
    # so key on the book too (the shared LedgerEntry.key() omits it on purpose).
    have = {(*e.key(), e.entry_book) for e in ledger}
    now = datetime.utcnow().isoformat() + "Z"
    added = 0
    for house_data in payload.get("houses", {}).values():
        for b in house_data.get("bets", []):
            e = LedgerEntry(
                round=payload["round"], match=b["match"], market=b["market"],
                selection=b["selection"], model_prob=round(b["model_prob"], 4),
                entry_fair_prob=round(b["fair_prob"], 4), entry_price=b["price"],
                entry_book=b["house"], stake_mxn=b["stake_mxn"], logged_at=now,
            )
            k = (*e.key(), e.entry_book)
            if k in have:
                continue
            ledger.append(e)
            have.add(k)
            added += 1
    _save_ledger(ledger)
    return added


def _hours_to_kickoff(match: str, markets: dict, now: datetime) -> float | None:
    """Horas desde `now` hasta el kickoff del partido (negativo si ya empezó), o
    None si no hay commence_time. `match` viene como 'Home vs Away'."""
    home, _, away = match.partition(" vs ")
    m = markets.get(f"{home}|{away}") or {}
    ct = m.get("commence_time")
    if not ct:
        return None
    try:
        k = datetime.fromisoformat(ct.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (k - now.replace(tzinfo=k.tzinfo)).total_seconds() / 3600.0


def cmd_close(within_hours: float | None = None) -> None:
    """Captura la línea de cierre para las entradas abiertas. Con `within_hours`
    SOLO cierra los partidos cuyo kickoff cae dentro de esa ventana (y que aún no
    empezaron): así una rutina diaria captura el cierre REAL de cada partido cerca
    de SU kickoff, en vez de congelar 3 días antes una línea que todavía se moverá.
    Sin el filtro, cierra todo lo abierto (comportamiento previo)."""
    if not ODDS_MARKETS_JSON.exists():
        raise SystemExit(f"Falta {ODDS_MARKETS_JSON}. Corre `ingest.ligamx_odds` justo antes "
                         "del cierre para capturar la línea.")
    markets = json.loads(ODDS_MARKETS_JSON.read_text(encoding="utf-8"))["matches"]
    ledger = _load_ledger()
    now_dt = datetime.utcnow()
    now = now_dt.isoformat() + "Z"
    n = skipped = 0
    for e in ledger:
        if e.close_fair_prob is not None:
            continue
        if within_hours is not None:
            h = _hours_to_kickoff(e.match, markets, now_dt)
            if h is None or h < 0 or h > within_hours:
                skipped += 1        # too early (or already started) → close it later
                continue
        fair, price = _market_lookup(e.match, e.market, e.selection, markets)
        if fair is None:
            continue
        e.close_fair_prob = round(float(fair), 4)
        e.close_price = round(float(price), 3) if price else None
        e.closed_at = now
        n += 1
    _save_ledger(ledger)
    win = f" (ventana ≤{within_hours:.0f}h al kickoff; {skipped} aún lejos)" if within_hours is not None else ""
    print(f"Cerradas {n} entradas con la línea actual{win}.")


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
    pl.add_argument("--min-stake", type=float, default=DEFAULT_MIN_STAKE,
                    help=f"mínimo jugable por apuesta en MXN (default ${DEFAULT_MIN_STAKE:.0f}); "
                         f"registra el stake que de verdad apuestas, no el Kelly crudo.")
    pl.add_argument("--total-line", type=float, default=2.5)
    pc = sub.add_parser("close", help="Captura la línea de cierre para las abiertas (cerca del kickoff).")
    pc.add_argument("--within-hours", type=float, default=None,
                    help="solo cierra partidos cuyo kickoff cae dentro de N horas (y que no han "
                         "empezado); una rutina diaria captura así el cierre real de cada partido.")
    sub.add_parser("settle", help="Liquida W/L + P&L con los resultados conocidos.")
    sub.add_parser("report", help="Resumen: CLV promedio, % que le gana al cierre, ROI + HTML.")
    args = p.parse_args(argv)

    if args.cmd == "log":
        cmd_log(args.round, args.bankroll, args.edge, args.kelly, args.max_stake,
                args.total_line, min_stake=args.min_stake)
    elif args.cmd == "close":
        cmd_close(within_hours=args.within_hours)
    elif args.cmd == "settle":
        cmd_settle()
    elif args.cmd == "report":
        cmd_report()


if __name__ == "__main__":
    main()
