"""Jornada en vivo de Europa: boletos de los bots para los próximos partidos.

1. Ajusta Poisson·DC + Elo por liga con TODO el historial (data/europa/matches.csv).
2. Lee los próximos partidos con momios previos (Football-Data fixtures.csv).
3. Cada bot arma su boleto: marcador + 1X2, Over/Under 2.5, ambos anotan, y las
   apuestas de valor que ve (1X2, O/U 2.5, hándicap asiático) a precio promedio.
4. ``--seal`` sella los boletos de los bots en data/liga/ledger.jsonl.

El boleto de Samuel = solo partidos con un equipo del top-3 de su liga.

Run:
    python -m wc_predictor.pipeline.europa_live                       # descarga fixtures
    python -m wc_predictor.pipeline.europa_live --fixtures fixtures.csv --seal
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from wc_predictor.ingest import europa_fd
from wc_predictor.liga import seal
from wc_predictor.liga.europa import EUROPA_MODEL, bot_view, load_override, top_teams
from wc_predictor.liga.markets import ah_expected_returns
from wc_predictor.liga.paths import liga_home, rounds_dir
from wc_predictor.model.poisson_dc import profile_fit_rho
from wc_predictor.pipeline.ligamx import effective_model_config
from wc_predictor.ratings.elo import replay_history

BOTS = {"estadistico": 0.0, "calibrado": EUROPA_MODEL.blend_odds_weight, "borrego": 1.0}


def _value_bets(v, fx) -> list[dict]:
    """Bets with positive expected value at the listed average prices."""
    bets = []
    if fx["avg_o1"]:
        for side, p, q in zip("1X2", v.probs, (fx["avg_o1"], fx["avg_ox"], fx["avg_o2"])):
            if p * q > 1:
                bets.append({"market": "1x2", "side": side, "price": q, "edge": round(p * q - 1, 3)})
    if fx["avg_over25"]:
        for side, p, q in (("over2.5", v.p_over25, fx["avg_over25"]),
                           ("under2.5", 1 - v.p_over25, fx["avg_under25"])):
            if p * q > 1:
                bets.append({"market": "ou25", "side": side, "price": q, "edge": round(p * q - 1, 3)})
    if fx["ah_line"] is not None and fx["avg_ahh"]:
        e = ah_expected_returns(v.cells, fx["ah_line"], fx["avg_ahh"], fx["avg_aha"])
        for side, line, q in (("home", fx["ah_line"], fx["avg_ahh"]),
                              ("away", -fx["ah_line"], fx["avg_aha"])):
            if e[side] > 1:
                bets.append({"market": "ah", "side": f"{side} {line:+g}", "price": q,
                             "edge": round(e[side] - 1, 3)})
    # one bet per market: the best edge
    best: dict[str, dict] = {}
    for b in bets:
        if b["market"] not in best or b["edge"] > best[b["market"]]["edge"]:
            best[b["market"]] = b
    return list(best.values())


def build_round(fixtures: list[dict], history: list[dict] | None = None) -> dict:
    history = history if history is not None else europa_fd.load()
    override = load_override()
    by_league: dict[str, list[dict]] = defaultdict(list)
    for fx in fixtures:
        by_league[fx["league"]].append(fx)
    matches, tops = [], {}
    for code, fxs in by_league.items():
        train = [r for r in history if r["league"] == code]
        _, fit, _ = profile_fit_rho(train, EUROPA_MODEL, ridge_lambda=EUROPA_MODEL.ridge_lambda,
                                    half_life_days=EUROPA_MODEL.half_life_days, verbose=False)
        mcfg = effective_model_config(fit, EUROPA_MODEL)
        elos, _ = replay_history(train, EUROPA_MODEL)
        season = max(r["season"] for r in train)
        teams = {t for r in train if r["season"] == season for t in (r["home"], r["away"])}
        top = top_teams(elos, teams | {t for f in fxs for t in (f["home"], f["away"])},
                        3, code, override)
        tops[code] = top
        for fx in fxs:
            mkt = (fx["fair_p1"], fx["fair_px"], fx["fair_p2"]) if fx["fair_p1"] else None
            entry = {"league": code, "date": fx["date"], "kickoff_utc": fx.get("kickoff_utc", ""),
                     "home": fx["home"], "away": fx["away"],
                     "top": fx["home"] in top or fx["away"] in top,
                     "market": {"p1x2": [round(x, 3) for x in mkt] if mkt else None,
                                "p_over25": fx["fair_over25"], "ah_line": fx["ah_line"]},
                     "bots": {}}
            for bot, w in BOTS.items():
                v = bot_view(fx["home"], fx["away"], fit, elos, mcfg, mkt, fx["fair_over25"], w)
                if v is None:
                    entry["bots"][bot] = {"error": "equipo sin historial (recién ascendido)"}
                    continue
                entry["bots"][bot] = {
                    "pick_1x2": v.pick_1x2, "pick_exact": v.pick_exact,
                    "p1x2": [round(x, 3) for x in v.probs],
                    "p_over25": round(v.p_over25, 3), "p_btts": round(v.p_btts, 3),
                    "value_bets": _value_bets(v, fx),
                }
            matches.append(entry)
    matches.sort(key=lambda m: (m["kickoff_utc"] or m["date"], m["league"], m["home"]))
    n = 0
    for m in matches:  # Samuel's ticket is numbered: "mis picks: 2-0, 1-1, …" follows this order
        if m["top"]:
            n += 1
            m["n"] = n
    return {"generated": date.today().isoformat(), "top3": tops, "matches": matches}


def _mx_time(iso_utc: str) -> str:
    """Kickoff in Mexico City time, for humans."""
    if not iso_utc:
        return ""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    d = datetime.fromisoformat(iso_utc).astimezone(ZoneInfo("America/Mexico_City"))
    dias = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
    return f"{dias[d.weekday()]} {d:%d %H:%M}"


def render_md(rnd: dict, only_top: bool = True) -> str:
    names = europa_fd.LEAGUES
    lines = [f"# Jornada Europa {rnd.get('round_id', '')} — generada {rnd['generated']}", "",
             "Horas en tiempo del centro de México. Tu boleto = los partidos numerados; "
             "manda tus marcadores en ese orden (\"-\" para saltar uno).", "",
             "Top-3 por liga: " + "; ".join(f"**{names[k]}**: {', '.join(v)}"
                                            for k, v in rnd["top3"].items()), ""]
    for m in rnd["matches"]:
        if only_top and not m["top"]:
            continue
        num = f"{m['n']}. " if m.get("n") else ""
        when = _mx_time(m.get("kickoff_utc", "")) or m["date"]
        lines.append(f"## {num}{m['home']} vs {m['away']} · {names[m['league']]} · {when}")
        mk = m["market"]
        if mk["p1x2"]:
            lines.append(f"Mercado: 1/X/2 {mk['p1x2']} · Over 2.5 {mk['p_over25']} · "
                         f"hándicap local {mk['ah_line']:+g}")
        for bot, b in m["bots"].items():
            if "error" in b:
                lines.append(f"- **{bot}**: {b['error']}")
                continue
            vb = ", ".join(f"{x['market']} {x['side']} @{x['price']} ({x['edge']:+.0%})"
                           for x in b["value_bets"]) or "nada"
            lines.append(f"- **{bot}**: {b['pick_exact']} ({b['pick_1x2']}) · "
                         f"Over2.5 {b['p_over25']:.0%} · BTTS {b['p_btts']:.0%} · apuesta: {vb}")
        lines.append("")
    return "\n".join(lines)


def seal_bots(rnd: dict, round_id: str) -> list[dict]:
    recs = []
    for bot in BOTS:
        if any(r["round"] == round_id and r["bot"] == bot for r in seal.read_ledger(seal.LEDGER)):
            print(f"{bot} ya selló {round_id}; se queda como está.")
            continue
        picks = [{"home": m["home"], "away": m["away"], "league": m["league"], "date": m["date"],
                  "kickoff_utc": m["kickoff_utc"],
                  **{k: m["bots"][bot][k] for k in ("pick_1x2", "pick_exact", "p1x2",
                                                    "p_over25", "p_btts", "value_bets")}}
                 for m in rnd["matches"] if "error" not in m["bots"][bot]]
        recs.append(seal.append(round_id, bot, picks))
    return recs


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", type=Path, default=None,
                    help="fixtures.csv local (default: $LIGA_HOME/fixtures.csv si existe; si no, se descarga)")
    ap.add_argument("--until", default=None, help="solo partidos hasta esta fecha (YYYY-MM-DD)")
    ap.add_argument("--seal", action="store_true", help="sellar los boletos de los bots")
    ap.add_argument("--all", action="store_true", help="markdown con todos los partidos, no solo top")
    args = ap.parse_args(argv)
    fx_path = args.fixtures or (liga_home() / "fixtures.csv")
    text = fx_path.read_text(encoding="utf-8-sig") if fx_path.exists() else None
    fixtures = europa_fd.load_upcoming(text)
    if args.until:
        fixtures = [f for f in fixtures if f["date"] <= args.until]
    if not fixtures:
        raise SystemExit("No hay partidos próximos en fixtures.csv.")
    first = min(f["date"] for f in fixtures)
    y, w, _ = date.fromisoformat(first).isocalendar()
    round_id = f"eu-{y}-W{w:02d}"
    # One round = one ISO week: fixtures.csv can run into the next week.
    fixtures = [f for f in fixtures if date.fromisoformat(f["date"]).isocalendar()[:2] == (y, w)]
    rnd = build_round(fixtures)
    rnd["round_id"] = round_id
    out_dir = rounds_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{round_id}.json").write_text(json.dumps(rnd, indent=2, ensure_ascii=False),
                                              encoding="utf-8")
    md = render_md(rnd, only_top=not args.all)
    (out_dir / f"{round_id}.md").write_text(md, encoding="utf-8")
    print(md)
    if args.seal:
        for r in seal_bots(rnd, round_id):
            print(f"sellado {r['bot']} {r['round']} {r['hash'][:12]}…")


if __name__ == "__main__":
    main()
