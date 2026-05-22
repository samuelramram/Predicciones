"""API-Football ingestion — player injuries / unavailability for WC 2026 teams.

Status (May 2026): the account on file is a **Free** plan, which the API blocks
from the 2026 season ("Free plans do not have access to this season, try from
2022 to 2024"). So today this module fetches nothing usable — it is wired to
**degrade gracefully**: on any plan/auth error it prints the reason and returns
an empty dict, and the pipeline runs unchanged.

It exists so the upgrade is a one-command flip. Once the account moves to a paid
plan (~$19/mo Pro), `python -m wc_predictor.ingest.api_football` starts caching
real injury data to data/raw/injuries_api_football.json with no code change.

The consuming side — turning unavailable players into a lambda penalty via
model/adjustments.py — is intentionally NOT built yet: that needs real data to
calibrate against (see the over-penalty bug noted in adjustments.py).

Normalized shape returned by the parser / loader:
    {team_name: [{"player": str, "type": str, "reason": str}, ...]}
keyed by canonical (martj42) team name, deduplicated by player.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from wc_predictor.config import (
    RAW_DIR,
    WC2026_LEAGUE_ID_API_FOOTBALL,
    WC2026_SEASON,
    get_api_football_key,
)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io/"
INJURIES_CACHE = "injuries_api_football.json"

# API-Football national-team names that differ from martj42 canonical names.
# Best-effort: cannot be verified against live data until the account is on a
# paid plan — revisit in June once real responses come back.
TEAM_CANONICAL = {
    "USA": "United States",
    "Korea Republic": "South Korea",
    "Czechia": "Czech Republic",
    "Czech-Republic": "Czech Republic",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "DR Congo": "DR Congo",
    "Cape Verde Islands": "Cape Verde",
    "Cabo Verde": "Cape Verde",
    "Curacao": "Curaçao",
}


def _canon(name: str) -> str:
    return TEAM_CANONICAL.get(name.strip(), name.strip())


def api_error(payload: dict) -> str | None:
    """Return a human-readable API error if the payload carries one, else None.

    API-Football reports errors in the `errors` field: an empty list `[]` means
    OK, a non-empty dict like {"plan": "..."} or {"token": "..."} means failure
    (the HTTP status is still 200, so this must be checked explicitly).
    """
    errors = payload.get("errors")
    if not errors:
        return None
    if isinstance(errors, dict):
        return "; ".join(f"{k}: {v}" for k, v in errors.items())
    return str(errors)


def parse_injuries_response(payload: dict) -> dict[str, list[dict]]:
    """Convert an API-Football /injuries response into per-team injury lists.

    Pure function — no network. Deduplicates by (team, player); a player with
    several upcoming-fixture entries collapses to one record.
    """
    out: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for item in payload.get("response", []):
        team = item.get("team") or {}
        player = item.get("player") or {}
        team_name = _canon(str(team.get("name", "")).strip())
        player_name = str(player.get("name", "")).strip()
        if not team_name or not player_name:
            continue
        dedup_key = (team_name, player_name)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        out.setdefault(team_name, []).append({
            "player": player_name,
            "type": str(item.get("type") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        })
    return out


def _call(path: str, key: str) -> dict:
    req = urllib.request.Request(
        API_FOOTBALL_BASE + path, headers={"x-apisports-key": key}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_injuries(
    api_key: str | None = None,
    season: int = WC2026_SEASON,
    league: int = WC2026_LEAGUE_ID_API_FOOTBALL,
    cache_path: Path | None = None,
) -> dict[str, list[dict]]:
    """Fetch WC injuries from API-Football. Returns {} (no raise) on any error.

    Caches the raw payload to data/raw/ for reproducibility. A plan/auth error
    (e.g. the Free-tier season block) is reported and swallowed so the pipeline
    keeps running without injury data.
    """
    key = api_key or get_api_football_key()
    if not key:
        print("API_FOOTBALL_KEY not set — skipping injury ingestion.")
        return {}

    payload = _call(f"injuries?league={league}&season={season}", key)

    err = api_error(payload)
    if err:
        print(f"API-Football returned an error — no injury data fetched:\n  {err}")
        return {}

    cache = cache_path or (RAW_DIR / INJURIES_CACHE)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return parse_injuries_response(payload)


def load_cached_injuries(cache_path: Path | None = None) -> dict[str, list[dict]]:
    """Load and parse a previously cached /injuries payload (offline re-runs)."""
    cache = cache_path or (RAW_DIR / INJURIES_CACHE)
    if not cache.exists():
        return {}
    with cache.open(encoding="utf-8") as f:
        return parse_injuries_response(json.load(f))


def main():
    key = get_api_football_key()
    if not key:
        print("API_FOOTBALL_KEY not set.")
        print("Add it to .env:  API_FOOTBALL_KEY=your_key_here")
        print("\nThe pipeline runs fine without it — injury data is optional.")
        return

    print(f"Fetching WC injuries from API-Football (league={WC2026_LEAGUE_ID_API_FOOTBALL}, "
          f"season={WC2026_SEASON}) ...")
    injuries = fetch_injuries()
    if not injuries:
        print("\nNo injury data available (see message above). The pipeline is "
              "unaffected — it does not depend on this source yet.")
        return

    total = sum(len(v) for v in injuries.values())
    print(f"  got {total} injuries across {len(injuries)} teams "
          f"→ cached to data/raw/{INJURIES_CACHE}")
    print("\nSample (first 5 teams):")
    for team, players in list(injuries.items())[:5]:
        names = ", ".join(p["player"] for p in players[:4])
        print(f"  {team:<22} {len(players)} out — {names}")


if __name__ == "__main__":
    main()
