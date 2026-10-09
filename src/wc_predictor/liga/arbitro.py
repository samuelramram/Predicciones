"""Árbitro: califica todos los boletos sellados contra los resultados reales.

Lee el libro (solo registros íntegros: si la cadena está rota, no califica nada),
junta las partes de cada jornada por persona/bot, busca el resultado en
``data/europa/matches.csv`` y arma la tabla:

1. **Mano a mano** — Samuel contra cada bot, SOLO en los partidos que Samuel
   jugó, con z pareado (|z| < 2 = todavía es suerte).
2. **Bots** — todos sus partidos: puntos, Brier 1X2 / O-U / ambos anotan, y el
   bankroll ficticio de las apuestas de valor que sellaron (10 por apuesta).

Partidos sin resultado todavía (el CSV de Football-Data llega con rezago) quedan
como pendientes y se califican en la siguiente corrida.

Run:
    python -m wc_predictor.liga.arbitro
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta

from wc_predictor.ingest import europa_fd
from wc_predictor.liga import seal
from wc_predictor.liga.europa import RULES
from wc_predictor.liga.markets import ah_return, binary_brier
from wc_predictor.liga.paths import tabla_dir
from wc_predictor.liga.scoring import brier, outcome_of, paired_diff
from wc_predictor.scoring.quiniela import score_actual

HUMANS = ("samuel",)
STAKE = 10.0


def results_index(rows: list[dict]) -> dict[tuple, dict]:
    return {(r["league"], r["home"], r["away"], r["date"]): r for r in rows}


def find_result(idx: dict, pick: dict) -> dict | None:
    d = date.fromisoformat(pick["date"])
    for delta in (0, -1, 1):
        r = idx.get((pick["league"], pick["home"], pick["away"], (d + timedelta(days=delta)).isoformat()))
        if r:
            return r
    return None


def settle_bet(bet: dict, hs: int, as_: int) -> float:
    """Profit of one sealed value bet at its sealed price."""
    m, side, q = bet["market"], bet["side"], bet["price"]
    if m == "1x2":
        win = side == outcome_of(hs, as_)
        return STAKE * (q - 1) if win else -STAKE
    if m == "ou25":
        over = hs + as_ > 2.5
        win = (side == "over2.5") == over
        return STAKE * (q - 1) if win else -STAKE
    if m == "ah":
        who, line = side.split()
        gd = hs - as_ if who == "home" else as_ - hs
        return STAKE * (ah_return(gd, float(line), q) - 1)
    raise ValueError(f"mercado desconocido {m}")


def collect(records: list[dict], prefix: str = "eu-") -> dict[str, dict[tuple, dict]]:
    """who → {(league, home, away, date): pick}; first seal of a match wins."""
    out: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for r in records:
        if not r["round"].startswith(prefix):
            continue
        for p in r["picks"]:
            k = (p["league"], p["home"], p["away"], p["date"])
            out[r["bot"]].setdefault(k, {**p, "round": r["round"].split("/")[0]})
    return out


def score(picks_by_who: dict, idx: dict) -> dict:
    """Per who: list of scored rows (only matches with a result) + pending count."""
    out = {}
    for who, picks in picks_by_who.items():
        rows, pending = [], 0
        for k, p in picks.items():
            res = find_result(idx, p)
            if res is None:
                pending += 1
                continue
            hs, as_ = res["home_score"], res["away_score"]
            row = {"key": k, "pts": score_actual(hs, as_, p["pick_1x2"], p["pick_exact"], RULES),
                   "result": f"{hs}-{as_}", "pick": p["pick_exact"]}
            if "p1x2" in p:
                row["b1x2"] = brier(tuple(p["p1x2"]), outcome_of(hs, as_))
                row["bou"] = binary_brier(p["p_over25"], hs + as_ > 2.5)
                row["bbtts"] = binary_brier(p["p_btts"], hs > 0 and as_ > 0)
                row["bets"] = [{**b, "profit": settle_bet(b, hs, as_)} for b in p.get("value_bets", [])]
            rows.append(row)
        out[who] = {"rows": rows, "pending": pending}
    return out


def build_table(scored: dict) -> dict:
    table: dict = {"mano_a_mano": {}, "bots": {}}
    human = next((h for h in HUMANS if h in scored), None)
    if human:
        mine = {r["key"]: r for r in scored[human]["rows"]}
        for who, s in scored.items():
            theirs = {r["key"]: r for r in s["rows"]}
            common = [k for k in mine if k in theirs]
            entry = {"n": len(common), "points": sum(theirs[k]["pts"] for k in common),
                     "exactos": sum(theirs[k]["pts"] >= RULES.points_exact for k in common)}
            if who != human and len(common) >= 2:
                d = paired_diff([mine[k]["pts"] for k in common], [theirs[k]["pts"] for k in common])
                entry["samuel_menos_bot"] = round(d["total_diff"], 1)
                entry["z"] = round(d["z"], 2)
            table["mano_a_mano"][who] = entry
    for who, s in scored.items():
        if who in HUMANS:
            continue
        rows = s["rows"]
        n = max(len(rows), 1)
        bets = [b for r in rows for b in r.get("bets", [])]
        by_mkt: dict[str, list[float]] = defaultdict(list)
        for b in bets:
            by_mkt[b["market"]].append(b["profit"])
        table["bots"][who] = {
            "n": len(rows), "pendientes": s["pending"],
            "points": sum(r["pts"] for r in rows),
            "exactos": sum(r["pts"] >= RULES.points_exact for r in rows),
            "brier_1x2": round(sum(r.get("b1x2", 0) for r in rows) / n, 4),
            "brier_ou25": round(sum(r.get("bou", 0) for r in rows) / n, 4),
            "brier_btts": round(sum(r.get("bbtts", 0) for r in rows) / n, 4),
            "mercados": {m: {"apuestas": len(v), "ganancia": round(sum(v), 1),
                             "roi": round(sum(v) / (STAKE * len(v)), 4)} for m, v in by_mkt.items()},
        }
    table["pendientes"] = {w: s["pending"] for w, s in scored.items()}
    return table


def render_md(t: dict) -> str:
    lines = [f"# Tabla de la liga — {date.today().isoformat()}", ""]
    if t["mano_a_mano"]:
        lines += ["## Mano a mano (solo los partidos que jugó Samuel)", "",
                  "| quién | partidos | pts | exactos | Samuel − bot | z |", "|---|---|---|---|---|---|"]
        for who, e in sorted(t["mano_a_mano"].items(), key=lambda kv: -kv[1]["points"]):
            lines.append(f"| {who} | {e['n']} | {e['points']} | {e['exactos']} | "
                         f"{e.get('samuel_menos_bot', '—')} | {e.get('z', '—')} |")
        lines += ["", "|z| < 2: la diferencia todavía puede ser suerte.", ""]
    if t["bots"]:
        lines += ["## Bots (todos sus partidos)", "",
                  "| bot | partidos | pts | exactos | Brier 1X2 | Brier O/U | Brier BTTS | apuestas (ROI) |",
                  "|---|---|---|---|---|---|---|---|"]
        for who, b in sorted(t["bots"].items(), key=lambda kv: -kv[1]["points"]):
            mk = ", ".join(f"{m} {v['apuestas']} ({v['roi']:+.0%})" for m, v in b["mercados"].items()) or "—"
            lines.append(f"| {who} | {b['n']} | {b['points']} | {b['exactos']} | {b['brier_1x2']} | "
                         f"{b['brier_ou25']} | {b['brier_btts']} | {mk} |")
    pend = {w: n for w, n in t["pendientes"].items() if n}
    if pend:
        lines += ["", "Pendientes de resultado: " + ", ".join(f"{w} {n}" for w, n in pend.items())]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.parse_args(argv)
    records = seal.read_ledger(seal.LEDGER)
    ok, why = seal.verify_chain(records)
    if not ok:
        raise SystemExit(f"Libro corrupto, no califico nada: {why}")
    idx = results_index(europa_fd.load())
    t = build_table(score(collect(records), idx))
    out = tabla_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "tabla.json").write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")
    md = render_md(t)
    (out / "tabla.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
