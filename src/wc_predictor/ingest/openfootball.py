"""Ingest openfootball/worldcup.json → canonical WC2026 fixture list.

Source: https://github.com/openfootball/worldcup.json (CC-by-SA). The 2026 file has
all **104 matches** with:
- Official group letters (A-L, 12 groups × 4 teams).
- Kickoff time + timezone offset (e.g. "13:00 UTC-6").
- Stadium city name (mapped here to our `venues.json` keys).
- Knockout placeholders ("W89", "L101") that resolve dynamically as the bracket fills.

This is the single source of truth for *who plays who when where*. Scores come from
martj42 (see `ingest.martj42.lookup_score`) — openfootball doesn't track results.

Run from the repo root:

    python -m wc_predictor.ingest.openfootball --bootstrap
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wc_predictor.config import RAW_DIR, WC_DIR
from wc_predictor.ingest.martj42 import _match_id, _read_rows, lookup_score

OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# openfootball "ground" → our venues.json key. Verified against the 16 official stadiums.
GROUND_TO_VENUE = {
    "Mexico City": "Estadio Azteca",
    "Guadalajara": "Estadio Akron",
    "Guadalajara (Zapopan)": "Estadio Akron",
    "Zapopan": "Estadio Akron",
    "Monterrey": "Estadio BBVA",
    "Monterrey (Guadalupe)": "Estadio BBVA",
    "Guadalupe": "Estadio BBVA",
    "Toronto": "BMO Field",
    "Vancouver": "BC Place",
    "New York/New Jersey (East Rutherford)": "MetLife Stadium",
    "East Rutherford": "MetLife Stadium",
    "Dallas (Arlington)": "AT&T Stadium",
    "Arlington": "AT&T Stadium",
    "Los Angeles (Inglewood)": "SoFi Stadium",
    "Inglewood": "SoFi Stadium",
    "Atlanta": "Mercedes-Benz Stadium",
    "San Francisco Bay Area (Santa Clara)": "Levi's Stadium",
    "Santa Clara": "Levi's Stadium",
    "Miami (Miami Gardens)": "Hard Rock Stadium",
    "Miami Gardens": "Hard Rock Stadium",
    "Houston": "NRG Stadium",
    "Seattle": "Lumen Field",
    "Kansas City": "Arrowhead Stadium",
    "Philadelphia": "Lincoln Financial Field",
    "Boston (Foxborough)": "Gillette Stadium",
    "Foxborough": "Gillette Stadium",
    "Philadelphia (Philadelphia)": "Lincoln Financial Field",
}

# openfootball round label → our internal stage key. Group rounds collapse to one stage.
ROUND_TO_STAGE = {
    "Round of 32": "round_of_32",
    "Round of 16": "round_of_16",
    "Quarter-final": "quarter_final",
    "Semi-final": "semi_final",
    "Match for third place": "third_place",
    "Final": "final",
}

TIME_RE = re.compile(r"^(\d{2}):(\d{2})\s+UTC([+-]\d+)$")


def _collect_real_teams(raw: dict) -> set[str]:
    """The 48 real teams are exactly those that appear in any Matchday N (group stage)
    fixture. Knockout slots use placeholders like '1A', '2L', '3A/B/C/D/F', 'W89', 'L101'."""
    real: set[str] = set()
    for match in raw["matches"]:
        if match.get("round", "").startswith("Matchday "):
            real.add(match["team1"])
            real.add(match["team2"])
    return real


def fetch_raw(dst: Path | None = None) -> Path:
    dst = dst or (RAW_DIR / "openfootball_wc2026.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(OPENFOOTBALL_URL) as response, dst.open("wb") as f:
        f.write(response.read())
    return dst


def _to_utc(date_str: str, time_str: str) -> str | None:
    """Combine 'YYYY-MM-DD' + '13:00 UTC-6' → ISO UTC timestamp. Returns None if unparseable."""
    if not time_str:
        return None
    m = TIME_RE.match(time_str.strip())
    if not m:
        return None
    hour, minute, tz_h = int(m.group(1)), int(m.group(2)), int(m.group(3))
    naive = datetime.fromisoformat(date_str).replace(hour=hour, minute=minute)
    local = naive.replace(tzinfo=timezone(timedelta(hours=tz_h)))
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stage_for(match: dict) -> str:
    rnd = match.get("round", "")
    if rnd in ROUND_TO_STAGE:
        return ROUND_TO_STAGE[rnd]
    if rnd.startswith("Matchday "):
        return "group_stage"
    return "unknown"


def parse_fixtures(raw: dict, martj42_rows: list[dict] | None = None) -> list[dict]:
    """Walk openfootball's flat match list, normalize, optionally merge scores from martj42."""
    real_teams = _collect_real_teams(raw)
    fixtures = []
    for match in raw["matches"]:
        date = match["date"]
        team1 = match["team1"]
        team2 = match["team2"]
        stage = _stage_for(match)
        ground = match.get("ground", "")
        venue = GROUND_TO_VENUE.get(ground)
        group_raw = match.get("group")
        group = group_raw.replace("Group ", "") if group_raw else None

        home_locked = team1 in real_teams
        away_locked = team2 in real_teams
        home_team = team1 if home_locked else None
        away_team = team2 if away_locked else None
        home_placeholder = team1 if not home_locked else None
        away_placeholder = team2 if not away_locked else None

        score = None
        if home_locked and away_locked and martj42_rows is not None:
            score = lookup_score(martj42_rows, date, team1, team2)

        if home_locked and away_locked:
            fx_id = _match_id(date, team1, team2)
        else:
            key = f"{date}|{team1}|{team2}".encode("utf-8")
            fx_id = "m_" + hashlib.sha1(key).hexdigest()[:10]

        fixtures.append({
            "match_id": fx_id,
            "num": match.get("num"),
            "stage": stage,
            "round_label": match.get("round"),
            "group": group,
            "date": date,
            "time_local": match.get("time"),
            "date_utc": _to_utc(date, match.get("time", "")),
            "ground": ground,
            "venue": venue,
            "home": home_team,
            "away": away_team,
            "home_placeholder": home_placeholder,
            "away_placeholder": away_placeholder,
            "home_locked": home_locked,
            "away_locked": away_locked,
            "home_score": score[0] if score else None,
            "away_score": score[1] if score else None,
        })
    fixtures.sort(key=lambda x: (x["date"], x.get("num") or 0))
    return fixtures


def build_groups(fixtures: list[dict]) -> dict[str, list[str]]:
    """Aggregate teams by official group letter from openfootball."""
    groups: dict[str, set[str]] = {}
    for fx in fixtures:
        if fx["stage"] != "group_stage" or not fx["group"]:
            continue
        groups.setdefault(fx["group"], set()).add(fx["home"])
        groups[fx["group"]].add(fx["away"])
    return {g: sorted(teams) for g, teams in sorted(groups.items())}


def write_fixtures(fixtures: list[dict], groups: dict[str, list[str]], dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": datetime.utcnow().strftime("%Y.%m.%d"),
        "sources": ["openfootball/worldcup.json", "martj42/international_results"],
        "groups": groups,
        "matches": fixtures,
    }
    with dst.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def bootstrap(refetch: bool = False) -> dict:
    of_src = RAW_DIR / "openfootball_wc2026.json"
    if refetch or not of_src.exists():
        print(f"Fetching {OPENFOOTBALL_URL} ...")
        of_src = fetch_raw(of_src)
    with of_src.open(encoding="utf-8") as f:
        raw = json.load(f)
    print(f"Loaded {len(raw['matches'])} matches from openfootball")

    martj42_src = RAW_DIR / "international_results.csv"
    martj42_rows = _read_rows(martj42_src) if martj42_src.exists() else None
    if martj42_rows is not None:
        print(f"Found martj42 raw at {martj42_src} → will merge scores when available")

    fixtures = parse_fixtures(raw, martj42_rows)
    groups = build_groups(fixtures)

    dst = WC_DIR / "fixtures.json"
    write_fixtures(fixtures, groups, dst)
    print(f"Wrote {len(fixtures)} fixtures in {len(groups)} groups to {dst}")

    unmapped = sorted({f["ground"] for f in fixtures if f["venue"] is None})
    if unmapped:
        print(f"WARNING: {len(unmapped)} grounds unmapped to venues.json:")
        for g in unmapped:
            print(f"  - {g!r}")

    return {
        "fixtures": len(fixtures),
        "groups": len(groups),
        "unmapped_grounds": len(unmapped),
    }


def main():
    parser = argparse.ArgumentParser(description="Bootstrap WC2026 fixtures from openfootball.")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--refetch", action="store_true")
    args = parser.parse_args()
    if not args.bootstrap:
        parser.error("Pass --bootstrap to run.")
    print("Done.", bootstrap(refetch=args.refetch))


if __name__ == "__main__":
    main()
