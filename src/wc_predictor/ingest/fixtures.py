"""Load the 104-match World Cup 2026 schedule.

Source of truth: `data/wc2026/fixtures.json` (human-curated, committed). This module
just loads, validates, and exposes typed accessors. Initial population can come from:

- FIFA official site (https://www.fifa.com/fifaplus/en/tournaments/mens/worldcup/canadamexicousa2026/schedule)
- Wikipedia (machine-readable tables, scraped via pandas.read_html)
- API-Football fixtures endpoint when subscription is active

After the draw (already done — Dec 5, 2025), groups, dates, and venues are locked.
Knockout opponents fill in as the bracket resolves.
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


def bootstrap_from_wikipedia() -> None:
    """TODO: scrape https://en.wikipedia.org/wiki/2026_FIFA_World_Cup#Schedule
    Tables include match number, date, venue, home, away, group. After the draw all
    104 rows are populated; knockout brackets show placeholders ("Winner Group A", ...)
    that we keep as is and resolve dynamically.
    """
    raise NotImplementedError("Bootstrap scraper pending — Phase 1.")
