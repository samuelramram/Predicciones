"""Jornada en vivo de Liga MX para la liga de bots, sin API keys.

Todo sale de Football-Data:
- resultados recientes de ``new/MEX.csv`` (vía ``data/ligamx/historical_odds.csv``,
  que refresca la Action diaria) se suman al historial para re-ajustar;
- los próximos partidos con momios previos salen de ``new_league_fixtures.csv``.

Los 3 bots son los mismos del backtest de Liga MX (``liga_backtest``):
estadistico (modelo de producción sin mercado), calibrado (blend de producción,
mercado 0.55) y borrego (favorito del mercado + marcador típico). El boleto de
Samuel en Liga MX = TODOS los partidos de la jornada, numerados por hora de inicio.

Football-Data no publica momios de totales para Liga MX: Over 2.5 y ambos anotan
se califican solo por Brier (sin apuestas), y el borrego no los juega.

Run:
    python -m wc_predictor.pipeline.ligamx_live              # usa $LIGA_HOME/fixtures_new.csv o descarga
    python -m wc_predictor.pipeline.ligamx_live --seal
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from wc_predictor.ingest import ligamx_fd_odds as fd
from wc_predictor.ingest.europa_fd import kickoff_utc
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.liga.bots import borrego_ticket, typical_scores
from wc_predictor.liga.markets import p_btts, p_over
from wc_predictor.liga.paths import liga_home, rounds_dir
from wc_predictor.model.poisson_dc import profile_fit_rho
from wc_predictor.pipeline.europa_live import render_md, seal_bots
from wc_predictor.pipeline.ligamx import (LIGAMX_DIR, effective_model_config, load_history_rows,
                                          load_team_altitudes, predict_fixture)
from wc_predictor.ratings.elo import replay_history

FIXTURES_URL = "https://www.football-data.co.uk/new_league_fixtures.csv"
MX = ZoneInfo("America/Mexico_City")
PROFILE = LIGAMX_APERTURA_PROFILE


def upcoming(text: str) -> tuple[list[dict], set[str]]:
    """Liga MX rows of new_league_fixtures.csv → (fixtures, unmapped team names)."""
    out, unmapped = [], set()
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        if r.get("Country") != "Mexico" or r.get("League") != "Liga MX":
            continue
        h, a = fd.FD_TEAM.get(r["Home"]), fd.FD_TEAM.get(r["Away"])
        if h is None or a is None:
            unmapped.update(n for n, m in ((r["Home"], h), (r["Away"], a)) if m is None)
            continue
        ko = kickoff_utc(r["Date"], r.get("Time", ""))
        local = datetime.fromisoformat(ko).astimezone(MX).date().isoformat() if ko else \
            datetime.strptime(r["Date"], "%d/%m/%Y").date().isoformat()
        odds = [fd._f(r.get(k, "")) for k in ("AvgH", "AvgD", "AvgA")]
        pin = [fd._f(r.get(k, "")) for k in ("PSH", "PSD", "PSA")]
        fair = fd.devig(*pin) if all(pin) else (fd.devig(*odds) if all(odds) else None)
        out.append({"league": "MX", "date": local, "kickoff_utc": ko, "home": h, "away": a,
                    "fair": fair, "avg": odds if all(odds) else None})
    out.sort(key=lambda f: (f["kickoff_utc"] or f["date"], f["home"]))
    return out, unmapped


def training_rows() -> list[dict]:
    """matches_history.csv + newer Football-Data results it doesn't have yet.
    FD dates are UK dates (a night match lands a day later), so dedupe ±1 day."""
    hist = load_history_rows()
    have = {(r["home"], r["away"], r["date"]) for r in hist}
    last = max(r["date"] for r in hist)
    extra = []
    for r in fd.load():
        if r["date"] < last:
            continue
        d = date.fromisoformat(r["date"])
        if any((r["home"], r["away"], (d + timedelta(days=k)).isoformat()) in have for k in (-1, 0, 1)):
            continue
        extra.append({"date": r["date"],
                      "home": r["home"], "away": r["away"], "home_score": r["home_score"],
                      "away_score": r["away_score"], "neutral": False,
                      "tournament": "Liga MX (Football-Data)", "stage": "regular"})
    return sorted(hist + extra, key=lambda r: r["date"])


def jornada_of(fixtures: list[dict]) -> str | None:
    """Jornada label from fixtures.json when the pairings are there (j11 …)."""
    path = LIGAMX_DIR / "fixtures.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    by_pair = {(m["home"], m["away"]): m.get("jornada") for m in doc.get("matches", [])}
    js = [by_pair.get((f["home"], f["away"])) for f in fixtures]
    js = [j for j in js if j]
    return f"J{max(set(js), key=js.count)}" if js else None


def _bot_entry(pick_1x2: str, pick_exact: str, probs, cells, avg) -> dict:
    e = {"pick_1x2": pick_1x2, "pick_exact": pick_exact,
         "p1x2": [round(x, 3) for x in probs],
         "p_over25": round(p_over(cells, 2.5), 3) if cells else None,
         "p_btts": round(p_btts(cells), 3) if cells else None, "value_bets": []}
    if avg:
        best = max(((s, p * q - 1, q) for s, p, q in zip("1X2", probs, avg)), key=lambda t: t[1])
        if best[1] > 0:
            e["value_bets"].append({"market": "1x2", "side": best[0], "price": best[2],
                                    "edge": round(best[1], 3)})
    return e


def build_round(fixtures: list[dict], rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else training_rows()
    mcfg0, rules = PROFILE.model, PROFILE.rules
    elos, _ = replay_history(rows, mcfg0)
    _, fit, _ = profile_fit_rho(rows, mcfg0, ridge_lambda=mcfg0.ridge_lambda,
                                half_life_days=mcfg0.half_life_days, verbose=False)
    mcfg = effective_model_config(fit, mcfg0)
    altitudes = load_team_altitudes()
    typical = typical_scores(rows)
    matches = []
    for n, f in enumerate(fixtures, start=1):
        fx = {"match_id": None, "home": f["home"], "away": f["away"], "home_score": None}
        odds = ({f"{f['home']}|{f['away']}": {"p1": f["fair"][0], "px": f["fair"][1],
                                              "p2": f["fair"][2], "n_books": 1}}
                if f["fair"] else None)
        entry = {"n": n, "league": "MX", "date": f["date"], "kickoff_utc": f["kickoff_utc"],
                 "home": f["home"], "away": f["away"], "top": True,
                 "market": {"p1x2": [round(x, 3) for x in f["fair"]] if f["fair"] else None,
                            "p_over25": None, "ah_line": None}, "bots": {}}
        for bot, o in (("estadistico", None), ("calibrado", odds)):
            p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=o)
            if p is None or "error" in p:
                entry["bots"][bot] = {"error": "equipo sin historial"}
                continue
            probs = (p["p_home_win"], p["p_draw"], p["p_away_win"])
            s = sum(probs)
            entry["bots"][bot] = _bot_entry(p["pick_1x2"], p["pick_exact"],
                                            [x / s for x in probs], p["_cells"], f["avg"])
        if f["fair"]:
            t = borrego_ticket(tuple(f["fair"]), typical)
            entry["bots"]["borrego"] = _bot_entry(t.pick_1x2, t.pick_exact, t.probs, None, f["avg"])
        else:
            entry["bots"]["borrego"] = {"error": "sin momio"}
        matches.append(entry)
    return {"generated": date.today().isoformat(), "top3": {}, "matches": matches}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", type=Path, default=None,
                    help="new_league_fixtures.csv local (default: $LIGA_HOME/fixtures_new.csv o descarga)")
    ap.add_argument("--seal", action="store_true")
    args = ap.parse_args(argv)
    path = args.fixtures or (liga_home() / "fixtures_new.csv")
    if path.exists():
        text = path.read_text(encoding="utf-8-sig")
    else:
        with urllib.request.urlopen(FIXTURES_URL, timeout=60) as resp:  # noqa: S310
            text = resp.read().decode("utf-8-sig", errors="replace")
    fixtures, unmapped = upcoming(text)
    if unmapped:
        raise SystemExit(f"Equipos sin mapear en FD_TEAM: {sorted(unmapped)}")
    if not fixtures:
        raise SystemExit("No hay partidos próximos de Liga MX en el archivo de Football-Data.")
    # One round = the first 4 days from the first kickoff (a jornada runs Fri–Mon).
    first = date.fromisoformat(fixtures[0]["date"])
    fixtures = [f for f in fixtures if date.fromisoformat(f["date"]) <= first + timedelta(days=3)]
    label = jornada_of(fixtures) or f"W{first.isocalendar()[1]:02d}"
    round_id = f"mx-{first.year}-{label}"
    rnd = build_round(fixtures)
    rnd["round_id"] = round_id
    out = rounds_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{round_id}.json").write_text(json.dumps(rnd, indent=2, ensure_ascii=False), encoding="utf-8")
    md = render_md(rnd, only_top=True)
    (out / f"{round_id}.md").write_text(md, encoding="utf-8")
    print(md)
    if args.seal:
        for r in seal_bots(rnd, round_id):
            print(f"sellado {r['bot']} {r['round']} {r['hash'][:12]}…")


if __name__ == "__main__":
    main()
