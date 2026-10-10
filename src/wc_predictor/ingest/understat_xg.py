"""xG por partido de las 5 ligas top (Understat), con nombres de Football-Data.

Understat publica, por liga y temporada, cada partido con goles y xG de ambos
lados (``getLeagueData/<liga>/<año>``). Esto alimenta el experimento de xG del
modelo de Europa: el Poisson se ajusta sobre una mezcla goles/xG (los goles tienen
mucha suerte; el xG mide la calidad de las ocasiones). Liga MX no está en Understat.

Salida: ``data/europa/xg.csv`` (league, date, home, away, home_goals, away_goals,
xg_home, xg_away). Uso respetuoso: ~35 peticiones, una por segundo.

Run:
    python -m wc_predictor.ingest.understat_xg               # descarga
    python -m wc_predictor.ingest.understat_xg --src DIR     # desde <Liga>_<año>.json ya bajados
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from wc_predictor.config import DATA_DIR

URL = "https://understat.com/getLeagueData/{league}/{year}"
LEAGUES = {"EPL": "E0", "La_liga": "SP1", "Serie_A": "I1", "Bundesliga": "D1", "Ligue_1": "F1"}
YEARS = tuple(range(2020, 2027))
OUT_CSV = DATA_DIR / "europa" / "xg.csv"
FIELDS = ["league", "date", "home", "away", "home_goals", "away_goals", "xg_home", "xg_away"]

# Understat spelling → Football-Data spelling (the rest already match).
NAMES = {
    "Manchester City": "Man City", "Manchester United": "Man United",
    "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
    "West Bromwich Albion": "West Brom", "Wolverhampton Wanderers": "Wolves",
    "Athletic Club": "Ath Bilbao", "Atletico Madrid": "Ath Madrid", "Celta Vigo": "Celta",
    "Deportivo La Coruna": "La Coruna", "Espanyol": "Espanol", "Racing Santander": "Santander",
    "Rayo Vallecano": "Vallecano", "Real Betis": "Betis", "Real Oviedo": "Oviedo",
    "Real Sociedad": "Sociedad", "Real Valladolid": "Valladolid", "SD Huesca": "Huesca",
    "AC Milan": "Milan", "Parma Calcio 1913": "Parma",
    "Arminia Bielefeld": "Bielefeld", "Bayer Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund", "Borussia M.Gladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt", "FC Cologne": "FC Koln", "FC Heidenheim": "Heidenheim",
    "Greuther Fuerth": "Greuther Furth", "Hamburger SV": "Hamburg", "Hertha Berlin": "Hertha",
    "Mainz 05": "Mainz", "RasenBallsport Leipzig": "RB Leipzig", "St. Pauli": "St Pauli",
    "VfB Stuttgart": "Stuttgart",
    "Clermont Foot": "Clermont", "Paris Saint Germain": "Paris SG", "Saint-Etienne": "St Etienne",
}


def _decode(raw: bytes) -> dict:
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    return json.loads(raw)


def _fetch(league: str, year: int) -> dict:
    req = urllib.request.Request(URL.format(league=league, year=year),
                                 headers={"X-Requested-With": "XMLHttpRequest",
                                          "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (fixed https host)
        return _decode(resp.read())


def normalize(doc: dict, league: str) -> list[dict]:
    out = []
    for m in doc.get("dates", []):
        if not m.get("isResult"):
            continue
        out.append({
            "league": LEAGUES[league], "date": m["datetime"][:10],
            "home": NAMES.get(m["h"]["title"], m["h"]["title"]),
            "away": NAMES.get(m["a"]["title"], m["a"]["title"]),
            "home_goals": int(m["goals"]["h"]), "away_goals": int(m["goals"]["a"]),
            "xg_home": round(float(m["xG"]["h"]), 4), "xg_away": round(float(m["xG"]["a"]), 4),
        })
    return out


def build(src: Path | None = None) -> list[dict]:
    rows: list[dict] = []
    for league in LEAGUES:
        for year in YEARS:
            if src is not None:
                p = src / f"{league}_{year}.json"
                if not p.exists():
                    continue
                doc = _decode(p.read_bytes())
            else:
                doc = _fetch(league, year)
                time.sleep(1.0)
            rows += normalize(doc, league)
    rows.sort(key=lambda r: (r["date"], r["league"], r["home"]))
    return rows


def write(rows: list[dict], dst: Path = OUT_CSV) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def load(src: Path = OUT_CSV) -> list[dict]:
    with src.open(encoding="utf-8") as f:
        return [{**r, "home_goals": int(r["home_goals"]), "away_goals": int(r["away_goals"]),
                 "xg_home": float(r["xg_home"]), "xg_away": float(r["xg_away"])}
                for r in csv.DictReader(f)]


def index(rows: list[dict]) -> dict[tuple, dict]:
    return {(r["league"], r["home"], r["away"], r["date"]): r for r in rows}


def lookup(idx: dict, league: str, home: str, away: str, iso_date: str) -> dict | None:
    """Football-Data dates are UK dates; Understat's are its own — allow ±1 day."""
    d = date.fromisoformat(iso_date)
    for k in (0, -1, 1):
        r = idx.get((league, home, away, (d + timedelta(days=k)).isoformat()))
        if r:
            return r
    return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, default=None)
    args = ap.parse_args(argv)
    rows = build(args.src)
    write(rows)
    print(f"{len(rows)} partidos con xG → {OUT_CSV} ({rows[0]['date']} → {rows[-1]['date']})")


if __name__ == "__main__":
    main()
