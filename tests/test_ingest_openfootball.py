"""Unit tests for the openfootball parser. Hermetic — no network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.ingest.openfootball import (
    GROUND_TO_VENUE,
    _collect_real_teams,
    _stage_for,
    _to_utc,
    build_groups,
    parse_fixtures,
)


SAMPLE_RAW = {
    "name": "World Cup 2026",
    "matches": [
        {
            "round": "Matchday 1", "date": "2026-06-11", "time": "13:00 UTC-6",
            "team1": "Mexico", "team2": "South Africa", "group": "Group A", "ground": "Mexico City",
        },
        {
            "round": "Matchday 1", "date": "2026-06-11", "time": "16:00 UTC-6",
            "team1": "South Korea", "team2": "Czech Republic", "group": "Group A", "ground": "Guadalajara (Zapopan)",
        },
        {
            "round": "Round of 32", "num": 73, "date": "2026-06-28", "time": "12:00 UTC-7",
            "team1": "2A", "team2": "2B", "ground": "Los Angeles (Inglewood)",
        },
        {
            "round": "Final", "date": "2026-07-19", "time": "15:00 UTC-4",
            "team1": "W101", "team2": "W102", "ground": "New York/New Jersey (East Rutherford)",
        },
    ],
}


def test_real_teams_only_from_group_stage():
    real = _collect_real_teams(SAMPLE_RAW)
    assert real == {"Mexico", "South Africa", "South Korea", "Czech Republic"}
    # Placeholders like 2A, W101 must NOT be in real teams
    for placeholder in ("2A", "2B", "W101", "W102"):
        assert placeholder not in real


def test_to_utc_with_negative_offset():
    # 13:00 UTC-6 (Mexico City) → 19:00 UTC
    assert _to_utc("2026-06-11", "13:00 UTC-6") == "2026-06-11T19:00:00Z"


def test_to_utc_with_minus_four():
    # 15:00 UTC-4 (NYC summer) → 19:00 UTC
    assert _to_utc("2026-07-19", "15:00 UTC-4") == "2026-07-19T19:00:00Z"


def test_to_utc_missing_time():
    assert _to_utc("2026-06-11", "") is None


def test_stage_for_group_stage():
    assert _stage_for({"round": "Matchday 1"}) == "group_stage"
    assert _stage_for({"round": "Matchday 17"}) == "group_stage"


def test_stage_for_knockouts():
    assert _stage_for({"round": "Round of 32"}) == "round_of_32"
    assert _stage_for({"round": "Round of 16"}) == "round_of_16"
    assert _stage_for({"round": "Quarter-final"}) == "quarter_final"
    assert _stage_for({"round": "Semi-final"}) == "semi_final"
    assert _stage_for({"round": "Match for third place"}) == "third_place"
    assert _stage_for({"round": "Final"}) == "final"


def test_parse_fixtures_locks_only_real_teams():
    fixtures = parse_fixtures(SAMPLE_RAW)
    assert len(fixtures) == 4
    group_fixture = fixtures[0]
    assert group_fixture["home_locked"] and group_fixture["away_locked"]
    assert group_fixture["home"] == "Mexico" and group_fixture["away"] == "South Africa"
    assert group_fixture["home_placeholder"] is None

    ko_fixture = next(f for f in fixtures if f["stage"] == "round_of_32")
    assert not ko_fixture["home_locked"]
    assert ko_fixture["home"] is None
    assert ko_fixture["home_placeholder"] == "2A"


def test_parse_fixtures_maps_venues():
    fixtures = parse_fixtures(SAMPLE_RAW)
    assert fixtures[0]["venue"] == "Estadio Azteca"
    assert fixtures[1]["venue"] == "Estadio Akron"
    # Knockout placeholders still get a venue mapped
    ko_fixture = next(f for f in fixtures if f["stage"] == "round_of_32")
    assert ko_fixture["venue"] == "SoFi Stadium"


def test_build_groups_aggregates_team_set():
    fixtures = parse_fixtures(SAMPLE_RAW)
    groups = build_groups(fixtures)
    assert "A" in groups
    assert set(groups["A"]) == {"Mexico", "South Africa", "South Korea", "Czech Republic"}


def test_venue_map_covers_all_16_stadiums():
    """Spot-check: every official venue.json name appears at least once in the map values."""
    expected_stadiums = {
        "Estadio Azteca", "Estadio Akron", "Estadio BBVA",
        "BMO Field", "BC Place",
        "MetLife Stadium", "AT&T Stadium", "SoFi Stadium",
        "Mercedes-Benz Stadium", "Levi's Stadium", "Hard Rock Stadium",
        "NRG Stadium", "Lumen Field", "Arrowhead Stadium",
        "Lincoln Financial Field", "Gillette Stadium",
    }
    mapped = set(GROUND_TO_VENUE.values())
    missing = expected_stadiums - mapped
    assert not missing, f"Stadiums not in GROUND_TO_VENUE: {missing}"
