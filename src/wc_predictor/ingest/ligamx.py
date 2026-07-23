"""Ingest Liga MX matches from TheSportsDB → training history + current fixtures.

Liga MX replaces the World Cup's martj42/openfootball feeds. TheSportsDB league
**4350** ("Mexican Primera League") is the same source the webapp
(samuelramram/quinielacartoimagen) uses, so team names / match_ids stay in the
same universe as the pool app.

Two artifacts, both versioned truth (mirrors the WC split):

  data/ligamx/matches_history.csv   training set (all past seasons w/ scores),
                                    columns identical to the international CSV
                                    so the Poisson+DC fit and the Elo replay
                                    consume it unchanged.
  data/ligamx/fixtures.json         the CURRENT Apertura calendar (played +
                                    upcoming), fixtures.json shape the pipeline
                                    already understands, keyed by jornada.

TheSportsDB "season" strings span a full calendar year and contain BOTH the
Apertura (Jul–Dec) and Clausura (Jan–Jun) short tournaments; we split them by
kickoff month and tag `tournament` accordingly.

Names are normalised to the canonical `name_es` from data/ligamx/teams.json so
every downstream key matches the webapp's short names.

Run from the repo root (needs THESPORTSDB_API_KEY in .env / env — the premium
key; the free key "3" caps eventsseason at ~5 rows):

    python -m wc_predictor.ingest.ligamx --bootstrap
    python -m wc_predictor.ingest.ligamx --seasons 2024-2025 2025-2026 --current 2026-2027
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DATA_DIR, get_thesportsdb_key

LIGAMX_DIR = DATA_DIR / "ligamx"
LIGAMX_LEAGUE_ID = 4350
API_BASE = "https://www.thesportsdb.com/api/v1/json"
FETCH_ATTEMPTS = 3

# Recent seasons carry the current sides' form; older ones drag in defunct teams
# (Morelia, Veracruz, Lobos BUAP) that are harmless as opponents but add nothing
# for the present 18. Default to the three most recent full seasons + current.
DEFAULT_HISTORY_SEASONS = ("2023-2024", "2024-2025", "2025-2026")
DEFAULT_CURRENT_SEASON = "2026-2027"

HISTORY_COLUMNS = [
    "match_id", "date", "home", "away", "home_score", "away_score",
    "neutral", "tournament", "city", "country",
]


def _match_id(date_str: str, home: str, away: str) -> str:
    """Deterministic short id — same (date, home, away) → same id across runs."""
    key = f"{date_str}|{home}|{away}".encode("utf-8")
    return "m_" + hashlib.sha1(key).hexdigest()[:10]


# TheSportsDB spelling → canonical name_es (data/ligamx/teams.json). Extra keys
# cover defunct/older sides so multi-season history normalises cleanly. Unknown
# names fall through _normalize's prefix-stripper and, failing that, pass raw.
NAME_MAP = {
    "CF America": "América",
    "América": "América",
    "Club America": "América",
    "Atlas": "Atlas",
    "Atletico de San Luis": "San Luis",
    "Atlético de San Luis": "San Luis",
    "Atletico San Luis": "San Luis",
    "Atlético San Luis": "San Luis",
    "Cruz Azul": "Cruz Azul",
    "CD Guadalajara": "Guadalajara",
    "Guadalajara": "Guadalajara",
    "FC Juarez": "Juárez",
    "FC Juárez": "Juárez",
    "León": "León",
    "Leon": "León",
    "Club Leon": "León",
    "Mazatlán": "Mazatlán",
    "Mazatlan": "Mazatlán",
    "Monterrey": "Monterrey",
    "Necaxa": "Necaxa",
    "Pachuca": "Pachuca",
    "Puebla": "Puebla",
    "Pumas": "Pumas",
    "Pumas UNAM": "Pumas",
    "UNAM Pumas": "Pumas",
    "Queretaro FC": "Querétaro",
    "Querétaro": "Querétaro",
    "Queretaro": "Querétaro",
    "Santos Laguna": "Santos",
    "Tigres": "Tigres",
    "Tigres UANL": "Tigres",
    "Tijuana": "Tijuana",
    "Xolos de Tijuana": "Tijuana",
    "Toluca": "Toluca",
    "Atlante": "Atlante",
    "Atlante FC": "Atlante",
}

_STRIP_PREFIXES = ("CF ", "CD ", "FC ", "Club ", "Deportivo ")


def _fold(s: str) -> str:
    """Accent- and case-insensitive key: 'Atlético San Luis' → 'atletico san luis'.
    Also drops a standalone ' de ' so 'Atlético de San Luis' folds the same way."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(" de ", " ").strip()


# Folded index of NAME_MAP so any accent/spacing variant of a known name resolves
# instead of silently passing through (which would drop that match's odds — the
# feed spells "Atlético San Luis" where fixtures use "San Luis").
_FOLDED_MAP = {_fold(k): v for k, v in NAME_MAP.items()}


def normalize_name(raw: str) -> str:
    """Map a TheSportsDB / odds-feed team name to the canonical short name_es."""
    if not raw:
        return raw
    raw = raw.strip()
    if raw in NAME_MAP:
        return NAME_MAP[raw]
    for pre in _STRIP_PREFIXES:
        if raw.startswith(pre):
            stripped = raw[len(pre):].strip()
            if stripped in NAME_MAP:
                return NAME_MAP[stripped]
            return _FOLDED_MAP.get(_fold(stripped), stripped)
    # Accent-insensitive fallback before giving up.
    return _FOLDED_MAP.get(_fold(raw), raw)


def _tournament_label(date_str: str) -> str:
    """Apertura (Jul–Dec) vs Clausura (Jan–Jun) of the year the match kicks off."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "Liga MX"
    return f"Liga MX Apertura {d.year}" if d.month >= 7 else f"Liga MX Clausura {d.year}"


def fetch_season(season: str, key: str, base: str = API_BASE) -> list[dict]:
    """All events of a TheSportsDB season for league 4350. Best-effort with
    retries; raises on repeated failure so callers can degrade to cached data."""
    import requests

    url = f"{base}/{key}/eventsseason.php?id={LIGAMX_LEAGUE_ID}&s={season}"
    last_err: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=40)
            resp.raise_for_status()
            events = resp.json().get("events")
            if events:
                return events
            last_err = RuntimeError(f"empty events for season {season}")
        except Exception as exc:  # noqa: BLE001 — best-effort ingest
            last_err = exc
        time.sleep(2 * attempt)
    raise RuntimeError(f"failed to fetch season {season}: {last_err}")


def _has_score(ev: dict) -> bool:
    return ev.get("intHomeScore") not in (None, "") and ev.get("intAwayScore") not in (None, "")


def event_to_history_row(ev: dict) -> dict | None:
    """One completed event → a history CSV row (canonical names), or None if the
    match has no final score yet."""
    if not _has_score(ev):
        return None
    date_str = ev.get("dateEvent") or ""
    home = normalize_name(ev.get("strHomeTeam") or "")
    away = normalize_name(ev.get("strAwayTeam") or "")
    if not (date_str and home and away):
        return None
    return {
        "match_id": _match_id(date_str, home, away),
        "date": date_str,
        "home": home,
        "away": away,
        "home_score": int(ev["intHomeScore"]),
        "away_score": int(ev["intAwayScore"]),
        "neutral": False,  # Liga MX regular season is always home/away
        "tournament": _tournament_label(date_str),
        "city": (ev.get("strVenue") or "").strip(),
        "country": "Mexico",
    }


def event_to_fixture(ev: dict) -> dict | None:
    """One event → a fixtures.json match record (played or upcoming)."""
    date_str = ev.get("dateEvent") or ""
    home = normalize_name(ev.get("strHomeTeam") or "")
    away = normalize_name(ev.get("strAwayTeam") or "")
    if not (date_str and home and away):
        return None
    try:
        jornada = int(ev.get("intRound") or 0)
    except (ValueError, TypeError):
        jornada = 0
    scored = _has_score(ev)
    return {
        "match_id": _match_id(date_str, home, away),
        "tsdb_event_id": ev.get("idEvent"),
        "stage": "regular",
        "jornada": jornada,
        "round_label": f"Jornada {jornada}" if jornada else None,
        "date": date_str,
        "date_utc": ev.get("strTimestamp"),
        "venue": (ev.get("strVenue") or "").strip() or None,
        "home": home,
        "away": away,
        "home_locked": True,
        "away_locked": True,
        "home_score": int(ev["intHomeScore"]) if scored else None,
        "away_score": int(ev["intAwayScore"]) if scored else None,
    }


def write_history(rows: list[dict], dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["date"], r["home"]))
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_fixtures(fixtures: list[dict], season: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fixtures = sorted(fixtures, key=lambda m: (m.get("jornada") or 0, m["date"], m["home"]))
    doc = {
        "version": datetime.utcnow().strftime("%Y.%m.%d"),
        "league": "Liga MX",
        "season": season,
        "sources": {"fixtures": f"TheSportsDB league {LIGAMX_LEAGUE_ID}"},
        "matches": fixtures,
    }
    with dst.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Liga MX (TheSportsDB 4350).")
    parser.add_argument("--bootstrap", action="store_true",
                        help="fetch the default recent seasons + current fixtures.")
    parser.add_argument("--seasons", nargs="*", default=list(DEFAULT_HISTORY_SEASONS),
                        help="seasons for the training history CSV.")
    parser.add_argument("--current", default=DEFAULT_CURRENT_SEASON,
                        help="season whose calendar becomes fixtures.json.")
    args = parser.parse_args()

    key = get_thesportsdb_key()
    if not key or key == "3":
        raise SystemExit(
            "Need a PREMIUM THESPORTSDB_API_KEY (the free key '3' caps "
            "eventsseason at ~5 rows). Put it in .env or the environment."
        )

    # Training history: every completed match across the requested seasons +
    # the current one (its played jornadas are the freshest form signal).
    seasons = list(dict.fromkeys([*args.seasons, args.current]))
    history: list[dict] = []
    for s in seasons:
        events = fetch_season(s, key)
        rows = [r for ev in events if (r := event_to_history_row(ev)) is not None]
        history.extend(rows)
        print(f"  {s}: {len(events)} events, {len(rows)} with scores")
    hist_dst = LIGAMX_DIR / "matches_history.csv"
    write_history(history, hist_dst)
    print(f"wrote {hist_dst} ({len(history)} matches)")

    # Current fixtures (played + upcoming) for the pick pipeline.
    cur_events = fetch_season(args.current, key)
    fixtures = [f for ev in cur_events if (f := event_to_fixture(ev)) is not None]
    fx_dst = LIGAMX_DIR / "fixtures.json"
    write_fixtures(fixtures, args.current, fx_dst)
    played = sum(1 for f in fixtures if f["home_score"] is not None)
    print(f"wrote {fx_dst} ({len(fixtures)} fixtures, {played} played)")


if __name__ == "__main__":
    main()
