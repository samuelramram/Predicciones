"""Resultados rápidos para la liga de bots desde TheSportsDB.

Football-Data (la fuente de los momios de cierre) publica resultados con días de
rezago. TheSportsDB los tiene minutos después del silbatazo, para las 5 ligas de
Europa y Liga MX. Este módulo:

1. lee el libro sellado y busca los partidos que todavía no tienen resultado de
   Football-Data;
2. pide a TheSportsDB los partidos de esas ligas en esas fechas (±1 día, porque
   un partido nocturno de Liga MX cae al día siguiente en UTC);
3. empareja cada partido sellado con su evento por fecha + nombres parecidos de
   local Y visita (los nombres de Football-Data vienen abreviados: "Man City",
   "Ath Madrid"; los de TheSportsDB completos);
4. guarda solo los **terminados** en ``$LIGA_HOME/results_live.csv``.

El Árbitro los usa mientras Football-Data no tenga ese partido; cuando lo tiene,
manda Football-Data (trae además los momios de cierre para el CLV).

Solo librería estándar: en el VPS lo corre el Utilero en el host, con red.
La llave va en ``THESPORTSDB_API_KEY`` (sin llave usa la pública de prueba).

Run:
    python -m wc_predictor.ingest.liga_results
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

from wc_predictor.config import DATA_DIR, get_thesportsdb_key
from wc_predictor.liga.paths import ledger_path, liga_home

API = "https://www.thesportsdb.com/api/v1/json/{key}/eventsday.php?d={d}&l={lid}"
PUBLIC_KEY = "123"
LEAGUE_IDS = {"E0": 4328, "SP1": 4335, "I1": 4332, "D1": 4331, "F1": 4334, "MX": 4350}
FINISHED = {"FT", "AET", "PEN", "MATCH FINISHED"}
FIELDS = ["league", "date", "home", "away", "home_score", "away_score", "source", "event_id"]

# Football-Data abbreviations → words TheSportsDB spells out.
EXPAND = {"man": "manchester", "utd": "united", "nott'm": "nottingham", "ath": "atletico",
          "m'gladbach": "monchengladbach", "ein": "eintracht", "sg": "saint germain",
          "espanol": "espanyol", "wolves": "wolverhampton", "sheffield": "sheffield",
          "fc": "", "cf": "", "ac": "", "afc": "", "sc": "", "ssc": "", "as": "", "us": "",
          "ud": "", "cd": "", "rc": "", "club": "", "calcio": "", "de": "", "1.": "", "uanl": "",
          "unam": "", "vfb": "", "vfl": "", "tsg": "", "sv": "", "rcd": "", "ogc": "", "fsv": ""}


def fold(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("-", " ")
    out = []
    for t in s.split():
        t = EXPAND.get(t, t)
        out += t.split()
    return out


def similarity(a: str, b: str) -> float:
    """0..1. Abbreviation-aware: each token of the shorter name must be a prefix of
    some token of the longer one ('ath' ⊂ 'atletico', 'leverkusen' ⊂ 'bayer leverkusen')."""
    ta, tb = fold(a), fold(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(" ".join(ta)) <= len(" ".join(tb)) else (tb, ta)
    hit = sum(1 for t in short if any(u.startswith(t) or t.startswith(u) for u in long_))
    prefix = hit / len(short)
    return max(prefix * 0.9, SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio())


def match_event(pick: dict, events: list[dict], min_sim: float = 0.55) -> dict | None:
    """Best event for the sealed pick: both teams must look alike."""
    best, score = None, 0.0
    for e in events:
        sh, sa = similarity(pick["home"], e["strHomeTeam"]), similarity(pick["away"], e["strAwayTeam"])
        if sh >= min_sim and sa >= min_sim and sh + sa > score:
            best, score = e, sh + sa
    return best


def finished_score(e: dict) -> tuple[int, int] | None:
    if (e.get("strStatus") or "").strip().upper() not in FINISHED:
        return None
    if (e.get("strPostponed") or "no").lower() == "yes":
        return None
    try:
        return int(e["intHomeScore"]), int(e["intAwayScore"])
    except (TypeError, ValueError, KeyError):
        return None


# ── qué falta ────────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fd_keys() -> set[tuple]:
    """(league, home, away, date) that Football-Data already has."""
    keys = {(r["league"], r["home"], r["away"], r["date"])
            for r in _read_csv(DATA_DIR / "europa" / "matches.csv")}
    keys |= {("MX", r["home"], r["away"], r["date"])
             for r in _read_csv(DATA_DIR / "ligamx" / "historical_odds.csv")}
    return keys


def _has(keys: set, lg: str, h: str, a: str, d: str) -> bool:
    x = date.fromisoformat(d)
    return any((lg, h, a, (x + timedelta(days=k)).isoformat()) in keys for k in (-1, 0, 1))


def pending(ledger: Path, have: set, today: date) -> list[dict]:
    """Sealed matches (any bot or Samuel) without a Football-Data result, already
    due (date ≤ today), one row per match."""
    seen, out = set(), []
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for p in json.loads(line).get("picks", []):
            k = (p["league"], p["home"], p["away"], p["date"])
            if k in seen or p["league"] not in LEAGUE_IDS or p["date"] > today.isoformat():
                continue
            seen.add(k)
            if not _has(have, *k):
                out.append({"league": k[0], "home": k[1], "away": k[2], "date": k[3]})
    return out


# ── red ──────────────────────────────────────────────────────────────────────
def fetch_day(league: str, d: str, key: str) -> list[dict]:
    url = API.format(key=key, d=d, lid=LEAGUE_IDS[league])
    req = urllib.request.Request(url, headers={"User-Agent": "liga-bots/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")).get("events") or []


def collect(todo: list[dict], fetch, pause: float = 0.0) -> list[dict]:
    """Results rows for the matches in ``todo`` that are finished."""
    days: dict[tuple, list[dict]] = {}
    out = []
    for m in todo:
        d0 = date.fromisoformat(m["date"])
        events = []
        for k in (0, -1, 1):
            key = (m["league"], (d0 + timedelta(days=k)).isoformat())
            if key not in days:
                try:
                    days[key] = fetch(*key)
                except (OSError, ValueError) as exc:  # red caída o JSON roto: ese día queda vacío
                    print(f"  aviso: {key} no respondió ({exc})")
                    days[key] = []
                if pause:
                    time.sleep(pause)
            events += days[key]
        e = match_event(m, events)
        sc = finished_score(e) if e else None
        if sc:
            out.append({**m, "home_score": sc[0], "away_score": sc[1], "source": "thesportsdb",
                        "event_id": e.get("idEvent", "")})
    return out


def merge_write(path: Path, rows: list[dict]) -> int:
    old = {(r["league"], r["home"], r["away"], r["date"]): r for r in _read_csv(path)}
    for r in rows:
        old[(r["league"], r["home"], r["away"], r["date"])] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(old):
            w.writerow({f_: old[k][f_] for f_ in FIELDS})
    tmp.replace(path)
    return len(old)


def live_path() -> Path:
    return liga_home() / "results_live.csv"


def load_live(path: Path | None = None) -> list[dict]:
    """Rows in the Árbitro's shape (scores as int)."""
    return [{**r, "home_score": int(r["home_score"]), "away_score": int(r["away_score"])}
            for r in _read_csv(path or live_path())]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.parse_args(argv)
    key = get_thesportsdb_key() or PUBLIC_KEY
    todo = pending(ledger_path(), fd_keys(), datetime.now(ZoneInfo("America/Mexico_City")).date())
    if not todo:
        print("Resultados rápidos: no falta ningún partido vencido.")
        return
    rows = collect(todo, lambda lg, d: fetch_day(lg, d, key), pause=0.0 if key != PUBLIC_KEY else 2.1)
    n = merge_write(live_path(), rows)
    print(f"Resultados rápidos: {len(rows)} de {len(todo)} partidos pendientes ya terminaron "
          f"(TheSportsDB). Archivo con {n}.")


if __name__ == "__main__":
    main()
