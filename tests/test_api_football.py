"""Tests for API-Football injury ingestion (pure parsing — no network)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.ingest.api_football import (
    api_error,
    parse_injuries_response,
)


# --- Error detection ---

def test_api_error_none_when_errors_empty_list():
    assert api_error({"errors": [], "response": []}) is None


def test_api_error_none_when_no_errors_key():
    assert api_error({"response": []}) is None


def test_api_error_reports_plan_block():
    payload = {"errors": {"plan": "Free plans do not have access to this season."},
               "response": []}
    msg = api_error(payload)
    assert msg is not None
    assert "plan" in msg and "Free plans" in msg


# --- /injuries response parsing ---

SAMPLE_INJURIES = {
    "errors": [],
    "results": 3,
    "response": [
        {
            "player": {"id": 1, "name": "Erling Haaland"},
            "team": {"id": 100, "name": "Norway"},
            "type": "Missing Fixture",
            "reason": "Knock",
        },
        {
            # Same player, second upcoming fixture → must collapse to one record.
            "player": {"id": 1, "name": "Erling Haaland"},
            "team": {"id": 100, "name": "Norway"},
            "type": "Missing Fixture",
            "reason": "Knock",
        },
        {
            "player": {"id": 2, "name": "Christian Pulisic"},
            "team": {"id": 200, "name": "USA"},  # must canonicalize
            "type": "Questionable",
            "reason": "Ankle injury",
        },
    ],
}


def test_parse_injuries_basic():
    parsed = parse_injuries_response(SAMPLE_INJURIES)
    assert "Norway" in parsed
    assert parsed["Norway"][0]["player"] == "Erling Haaland"
    assert parsed["Norway"][0]["reason"] == "Knock"


def test_parse_injuries_deduplicates_player():
    parsed = parse_injuries_response(SAMPLE_INJURIES)
    # Haaland appears twice in the payload but only once in the result.
    assert len(parsed["Norway"]) == 1


def test_parse_injuries_canonicalizes_team_name():
    parsed = parse_injuries_response(SAMPLE_INJURIES)
    assert "United States" in parsed
    assert "USA" not in parsed


def test_parse_injuries_empty_payload():
    assert parse_injuries_response({"response": []}) == {}
    assert parse_injuries_response({}) == {}


def test_parse_injuries_skips_incomplete_items():
    payload = {"response": [
        {"team": {"name": "Brazil"}},                       # no player
        {"player": {"name": "Someone"}},                    # no team
        {"player": {"name": ""}, "team": {"name": "Spain"}},  # blank player
    ]}
    assert parse_injuries_response(payload) == {}
