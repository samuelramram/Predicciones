"""Load the 104-match World Cup 2026 schedule.

Source of truth: `data/wc2026/fixtures.json` (human-curated, committed). This module
loads, validates, and exposes typed accessors.

Bootstrap population — primary source is **TheSportsDB league 4429** (`WC2026_LEAGUE_ID_THESPORTSDB`)
because that is the same source the Lovable webapp consumes for live results; using it
here keeps `match_id` and team-name normalization consistent end-to-end. The model
output can then be pasted into the pool's UI without remapping.

Fallback if TheSportsDB key is missing or quota-limited:
- Wikipedia tables (`pandas.read_html` on the 2026 FIFA World Cup page).
- FIFA.com via Firecrawl (last resort, fragile).

After the draw (Dec 5, 2025) all 104 rows exist with groups, dates, venues, and
group-stage opponents. Knockout rows have placeholders ("Winner Group A", ...) that
we resolve dynamically as results come in.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wc_predictor.config import WC_DIR


@dataclass(frozen=True)
class Fixture:
    match_id: str
    stage: str
    group: str | None
    date_utc: datetime
    venue: str
    home: str
    away: str
    home_locked: bool
    away_locked: bool


def load_fixtures(path: Path | None = None) -> list[Fixture]:
    src = path or (WC_DIR / "fixtures.json")
    if not src.exists():
        raise FileNotFoundError(
            f"Fixtures file missing: {src}. Run `python -m wc_predictor.ingest.fixtures --bootstrap`."
        )
    with src.open(encoding="utf-8") as f:
        data = json.load(f)
    fixtures = []
    for row in data["matches"]:
        fixtures.append(
            Fixture(
                match_id=row["match_id"],
                stage=row["stage"],
                group=row.get("group"),
                date_utc=datetime.fromisoformat(row["date_utc"]),
                venue=row["venue"],
                home=row["home"],
                away=row["away"],
                home_locked=row.get("home_locked", True),
                away_locked=row.get("away_locked", True),
            )
        )
    return fixtures


def bootstrap_from_thesportsdb() -> None:
    """TODO Phase 1: pull league 4429 via
        https://www.thesportsdb.com/api/v1/json/{key}/eventsseason.php?id=4429&s=2026
    Normalize team names against `data/wc2026/teams.json::team_aliases`. Write to
    `data/wc2026/fixtures.json` with the schema consumed by `load_fixtures`.
    """
    raise NotImplementedError("TheSportsDB bootstrap pending — Phase 1.")


def bootstrap_from_wikipedia() -> None:
    """Fallback when TheSportsDB is unavailable. Phase 1, lower priority."""
    raise NotImplementedError("Wikipedia fallback scraper pending — Phase 1.")
