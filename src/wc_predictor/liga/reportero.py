"""Reportero: el bot que lee noticias (alineaciones, bajas, rotaciones).

Lo opera Claudio (un LLM con búsqueda web), pero los números los pone este código.
Claudio investiga cada partido del boleto y escribe un archivo con su veredicto en
forma de **multiplicadores de goles esperados**:

    {"round": "eu-2026-W41",
     "matches": [{"n": 14, "home": "Liverpool", "away": "Man City",
                  "home_mult": 0.92, "away_mult": 1.0,
                  "nota": "Salah fuera (lesión muscular, confirmado por el club)",
                  "fuentes": ["https://…"]}]}

`home_mult` escala los goles que se esperan del local, `away_mult` los de la visita.
Por ejemplo, si falta el goleador del local, baja su ataque: 0.92. El código parte del
bot **calibrado** (modelo + mercado), aplica los multiplicadores acotados a
[0.75, 1.25], rearma la matriz de marcadores y elige el pick con el mismo optimizador
del pool. Un partido sin noticias se queda igual que el calibrado.

Así la pregunta es medible y justa: ¿leer noticias le gana al calibrado? El
Árbitro lo compara partido por partido (z pareado).

Run:
    python -m wc_predictor.liga.reportero --round eu-2026-W41 --dry-run
    python -m wc_predictor.liga.reportero --round eu-2026-W41 --seal
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.liga import seal
from wc_predictor.liga.europa import EUROPA_MODEL, implied_lambdas
from wc_predictor.liga.markets import p_btts, p_over
from wc_predictor.liga.paths import liga_home, rounds_dir
from wc_predictor.model.blend import rescale_cells_to_marginals
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

BOT = "reportero"
BASE_BOT = "calibrado"
MULT_MIN, MULT_MAX = 0.75, 1.25
RULES = LIGAMX_APERTURA_PROFILE.rules


def notes_path(round_id: str) -> Path:
    return liga_home() / "reportero" / f"{round_id}.json"


def _clamp(x) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 1.0
    return min(MULT_MAX, max(MULT_MIN, x))


def _base_lambdas(entry: dict, rho: float) -> tuple[float, float]:
    """The calibrado bot's expected goals; older round files lack them, so fall
    back to the goal rates implied by its own 1X2 + Over 2.5."""
    if entry.get("goals"):
        return tuple(entry["goals"])
    p1, _, p2 = entry["p1x2"]
    po = entry.get("p_over25") or 0.5
    return implied_lambdas(p1, p2, po, rho)


def adjust(base: dict, home_mult: float, away_mult: float, mcfg) -> dict:
    """Calibrado's view → reportero's view after the news multipliers.

    The grid is rebuilt with the scaled goal rates, and the calibrado's 1X2 is
    moved by the same RELATIVE change the multipliers cause on that grid. So with
    multipliers 1.0 the result is exactly the calibrado (market blend intact) and
    the news only nudges it."""
    if (home_mult, away_mult) == (1.0, 1.0):   # no news → literally the calibrado ticket
        return {"pick_1x2": base["pick_1x2"], "pick_exact": base["pick_exact"],
                "p1x2": list(base["p1x2"]), "p_over25": base.get("p_over25"),
                "p_btts": base.get("p_btts"), "home_mult": 1.0, "away_mult": 1.0}
    lh, la = _base_lambdas(base, mcfg.dc_rho)
    cells0, q1, qx, q2, _, _ = build_score_matrix(lh, la, mcfg)
    cells1, r1, rx, r2, pmass, pmax = build_score_matrix(lh * home_mult, la * away_mult, mcfg)
    b1, bx, b2 = base["p1x2"]
    raw = (b1 * r1 / q1, bx * rx / qx, b2 * r2 / q2)
    s = sum(raw)
    p1, px, p2 = (x / s for x in raw)
    cells = rescale_cells_to_marginals(cells1, p1, px, p2)
    po_base = base.get("p_over25")
    po_grid0, po_grid1 = p_over(cells0, 2.5), p_over(cells1, 2.5)
    po = None if po_base is None else min(0.99, max(0.01, po_base * po_grid1 / po_grid0))
    pick = optimize_pick_from_cells(cells, p1, px, p2, pmass, pmax, RULES, mcfg)
    return {"pick_1x2": pick.pick_1x2, "pick_exact": pick.pick_exact,
            "p1x2": [round(p1, 3), round(px, 3), round(p2, 3)],
            "p_over25": None if po is None else round(po, 3),
            "p_btts": round(p_btts(cells), 3), "home_mult": home_mult, "away_mult": away_mult}


def build_ticket(rnd: dict, notes: dict, now: datetime, mcfg=None) -> tuple[list[dict], list[str]]:
    """Reportero picks for every NUMBERED match (Samuel's ticket) not yet started."""
    mcfg = mcfg or EUROPA_MODEL
    by_n = {int(m["n"]): m for m in notes.get("matches", []) if "n" in m}
    picks, msgs = [], []
    for m in rnd["matches"]:
        if not m.get("n"):
            continue
        label = f"{m['n']}. {m['home']}–{m['away']}"
        ko = m.get("kickoff_utc")
        if ko and now >= datetime.fromisoformat(ko):
            msgs.append(f"{label}: ya empezó, no se sella.")
            continue
        base = m["bots"].get(BASE_BOT, {})
        if "p1x2" not in base:
            msgs.append(f"{label}: sin boleto del calibrado, se salta.")
            continue
        n = by_n.get(int(m["n"]), {})
        if n and (n.get("home"), n.get("away")) not in ((m["home"], m["away"]), (None, None)):
            msgs.append(f"{label}: la nota dice {n.get('home')}–{n.get('away')}; no cuadra, se ignora.")
            n = {}
        hm, am = _clamp(n.get("home_mult", 1.0)), _clamp(n.get("away_mult", 1.0))
        view = adjust(base, hm, am, mcfg)
        avg = (m.get("market") or {}).get("avg_1x2")
        bets = []
        if avg and all(avg):
            side, edge, q = max(((s, p * q - 1, q) for s, p, q in zip("1X2", view["p1x2"], avg)),
                                key=lambda t: t[1])
            if edge > 0:
                bets.append({"market": "1x2", "side": side, "price": q, "edge": round(edge, 3)})
        picks.append({"n": m["n"], "league": m["league"], "date": m["date"], "kickoff_utc": ko,
                      "home": m["home"], "away": m["away"], **view, "value_bets": bets,
                      "nota": str(n.get("nota", ""))[:400],
                      "fuentes": [str(u)[:300] for u in (n.get("fuentes") or [])][:5]})
        changed = "" if (hm, am) == (1.0, 1.0) else f" (local ×{hm:g}, visita ×{am:g})"
        msgs.append(f"{label}: {view['pick_exact']}{changed} · calibrado {base['pick_exact']}")
    return picks, msgs


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--round", required=True)
    ap.add_argument("--notes", type=Path, default=None,
                    help="archivo de notas (default: $LIGA_HOME/reportero/<jornada>.json)")
    ap.add_argument("--seal", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    rnd = json.loads((rounds_dir() / f"{args.round}.json").read_text(encoding="utf-8"))
    path = args.notes or notes_path(args.round)
    notes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"matches": []}
    if not path.exists():
        print(f"(sin notas en {path}: el reportero copia al calibrado)")
    mcfg = LIGAMX_APERTURA_PROFILE.model if args.round.startswith("mx-") else EUROPA_MODEL
    picks, msgs = build_ticket(rnd, notes, datetime.now(timezone.utc), mcfg)
    print("\n".join(msgs))
    if args.dry_run or not args.seal:
        print("(prueba: no se selló nada)")
        return
    records = seal.read_ledger(seal.LEDGER)
    ok, why = seal.verify_chain(records)
    if not ok:
        raise SystemExit(f"Libro corrupto: {why}")
    if any(r["round"] == args.round and r["bot"] == BOT for r in records):
        raise SystemExit(f"El reportero ya selló {args.round}.")
    if not picks:
        raise SystemExit("Nada que sellar.")
    rec = seal.append(args.round, BOT, picks)
    print(f"Sellado {rec['round']} · reportero · {len(picks)} partidos · hash {rec['hash'][:12]}")


if __name__ == "__main__":
    main()
