"""Partidos de copas UEFA (Champions, Europa League, Conference) con momios.

Football-Data no cubre las copas, así que los próximos partidos y sus momios salen
de The Odds API: 1X2 y Over/Under 2.5, promedio de las casas y su línea justa
(sin margen). El boleto de Samuel en Europa toma de aquí solo los partidos de un
equipo del top-3 de su liga (eso lo decide ``pipeline.europa_live``).

Solo librería estándar: en el VPS lo corre el Utilero en el host, con red. La llave
va en ``THE_ODDS_API_KEY``. Cada llamada cuesta 2 créditos (h2h + totals) por copa;
el plan gratis da 500 al mes, así que por default solo se refresca si el archivo
tiene más de 20 horas (``--max-age-h``): 3 copas × 1 vez al día ≈ 180 créditos/mes.

Run:
    python -m wc_predictor.ingest.uefa_odds                 # → $LIGA_HOME/uefa_fixtures.json
    python -m wc_predictor.ingest.uefa_odds --max-age-h 0   # forzar
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from statistics import mean

from wc_predictor.liga.paths import liga_home

COMPETITIONS = {
    "UCL": "soccer_uefa_champs_league",
    "UEL": "soccer_uefa_europa_league",
    "UECL": "soccer_uefa_europa_conference_league",
}
NAMES = {"UCL": "Champions League", "UEL": "Europa League", "UECL": "Conference League"}
API = ("https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={key}"
       "&regions=eu&markets=h2h,totals&oddsFormat=decimal")


def out_path() -> Path:
    return liga_home() / "uefa_fixtures.json"


def _devig(*odds: float) -> tuple[float, ...]:
    inv = [1.0 / o for o in odds]
    s = sum(inv)
    return tuple(x / s for x in inv)


def parse_event(code: str, ev: dict) -> dict | None:
    """One Odds API event → the fixture row europa_live expects (same keys as
    Football-Data's ``load_upcoming``). None when no bookmaker has a 1X2."""
    home, away = ev["home_team"], ev["away_team"]
    h2h: list[tuple[float, float, float]] = []
    over: list[tuple[float, float]] = []
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            prices = {o["name"]: o for o in mk.get("outcomes", [])}
            if mk["key"] == "h2h" and {home, away, "Draw"} <= prices.keys():
                q = (prices[home]["price"], prices["Draw"]["price"], prices[away]["price"])
                if all(x > 1.0 for x in q):
                    h2h.append(q)
            elif (mk["key"] == "totals" and {"Over", "Under"} <= prices.keys()
                  and prices["Over"].get("point") == 2.5 and prices["Under"].get("point") == 2.5):
                over.append((prices["Over"]["price"], prices["Under"]["price"]))
    if not h2h:
        return None
    avg = tuple(round(mean(q[i] for q in h2h), 3) for i in range(3))
    # Fair line = mean of each book's devigged probabilities (robust to one book's margin).
    fair = [mean(_devig(*q)[i] for q in h2h) for i in range(3)]
    s = sum(fair)
    fair = [p / s for p in fair]
    row = {"league": code, "date": ev["commence_time"][:10],
           "kickoff_utc": ev["commence_time"].replace("Z", "+00:00"),
           "home": home, "away": away,
           "fair_p1": round(fair[0], 4), "fair_px": round(fair[1], 4), "fair_p2": round(fair[2], 4),
           "avg_o1": avg[0], "avg_ox": avg[1], "avg_o2": avg[2],
           "fair_over25": None, "avg_over25": None, "avg_under25": None,
           "ah_line": None, "avg_ahh": None, "avg_aha": None, "n_books": len(h2h)}
    if over:
        row["fair_over25"] = round(mean(_devig(o, u)[0] for o, u in over), 4)
        row["avg_over25"] = round(mean(o for o, _ in over), 3)
        row["avg_under25"] = round(mean(u for _, u in over), 3)
    return row


def fetch(key: str) -> list[dict]:
    rows = []
    for code, sport in COMPETITIONS.items():
        req = urllib.request.Request(API.format(sport=sport, key=key),
                                     headers={"User-Agent": "liga-bots/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            left = r.headers.get("x-requests-remaining")
            events = json.loads(r.read().decode("utf-8"))
        parsed = [p for p in (parse_event(code, e) for e in events) if p]
        print(f"  {NAMES[code]}: {len(parsed)} partidos con momios (créditos restantes: {left})")
        rows += parsed
    return rows


def load(path: Path | None = None) -> list[dict]:
    path = path or out_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("fixtures", [])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-age-h", type=float, default=20.0,
                    help="no vuelve a pedir si el archivo es más nuevo que esto (cuida créditos)")
    args = ap.parse_args(argv)
    dst = out_path()
    if dst.exists() and (time.time() - dst.stat().st_mtime) < args.max_age_h * 3600:
        print(f"uefa_fixtures.json fresco (<{args.max_age_h:g} h); no gasto créditos.")
        return
    key = os.environ.get("THE_ODDS_API_KEY")
    if not key:
        raise SystemExit("Falta THE_ODDS_API_KEY: sin ella no hay partidos de copas.")
    rows = fetch(key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "fixtures": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dst)
    print(f"→ {dst} ({len(rows)} partidos)")


if __name__ == "__main__":
    main()
