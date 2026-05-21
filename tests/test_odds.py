"""Tests for bookmaker odds ingestion and the 3-way blend."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.ingest.odds import implied_probs_from_decimal, parse_odds_api_response
from wc_predictor.model.blend import blend_three_sources


# --- De-vig math ---

def test_implied_probs_sum_to_one():
    p1, px, p2, overround = implied_probs_from_decimal(2.0, 3.5, 4.0)
    assert abs(p1 + px + p2 - 1.0) < 1e-9


def test_implied_probs_overround_above_one():
    # Real bookmaker odds carry a margin → raw inverse-odds sum > 1.
    _, _, _, overround = implied_probs_from_decimal(2.0, 3.5, 4.0)
    assert overround > 1.0


def test_implied_probs_fair_odds_have_no_overround():
    # Perfectly fair 3-way odds (2/1 each side mapping to 33.3%) → overround ≈ 1.
    _, _, _, overround = implied_probs_from_decimal(3.0, 3.0, 3.0)
    assert abs(overround - 1.0) < 1e-9


def test_implied_probs_shorter_odds_higher_prob():
    p1, _, p2, _ = implied_probs_from_decimal(1.5, 4.0, 6.0)
    assert p1 > p2  # 1.50 favourite must carry more probability than the 6.00 outsider


# --- The Odds API response parsing ---

SAMPLE_ODDS_API = [
    {
        "id": "abc123",
        "sport_key": "soccer_fifa_world_cup",
        "commence_time": "2026-06-11T19:00:00Z",
        "home_team": "Mexico",
        "away_team": "South Africa",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Mexico", "price": 1.65},
                        {"name": "South Africa", "price": 5.50},
                        {"name": "Draw", "price": 3.90},
                    ],
                }],
            },
            {
                "key": "bet365",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Mexico", "price": 1.62},
                        {"name": "South Africa", "price": 5.25},
                        {"name": "Draw", "price": 3.80},
                    ],
                }],
            },
        ],
    },
    {
        "id": "def456",
        "home_team": "USA",  # odds-source name; must canonicalize to "United States"
        "away_team": "Australia",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "USA", "price": 1.90},
                        {"name": "Australia", "price": 4.20},
                        {"name": "Draw", "price": 3.50},
                    ],
                }],
            },
        ],
    },
]


def test_parse_odds_api_basic():
    parsed = parse_odds_api_response(SAMPLE_ODDS_API)
    assert "Mexico|South Africa" in parsed
    entry = parsed["Mexico|South Africa"]
    assert abs(entry["p1"] + entry["px"] + entry["p2"] - 1.0) < 1e-9
    assert entry["n_books"] == 2
    assert entry["p1"] > entry["p2"]  # Mexico favoured


def test_parse_odds_api_canonicalizes_team_names():
    parsed = parse_odds_api_response(SAMPLE_ODDS_API)
    # "USA" in the feed must become the canonical "United States".
    assert "United States|Australia" in parsed
    assert "USA|Australia" not in parsed


def test_parse_odds_api_empty_payload():
    assert parse_odds_api_response([]) == {}


# --- 3-way blend ---

def _flat_cells():
    """A small valid score matrix (probabilities sum to 1)."""
    cells = [
        {"score": "1-0", "outcome": "1", "prob": 0.20},
        {"score": "2-1", "outcome": "1", "prob": 0.15},
        {"score": "1-1", "outcome": "X", "prob": 0.18},
        {"score": "0-0", "outcome": "X", "prob": 0.12},
        {"score": "0-1", "outcome": "2", "prob": 0.20},
        {"score": "0-2", "outcome": "2", "prob": 0.15},
    ]
    return cells, (0.35, 0.30, 0.35)


def test_blend_three_sources_with_odds():
    cells, pois = _flat_cells()
    elo = (0.40, 0.28, 0.32)
    odds = (0.60, 0.25, 0.15)  # market strongly favours home
    new_cells, p1, px, p2 = blend_three_sources(
        cells, pois, elo, odds, w_poisson=0.3, w_elo=0.2, w_odds=0.5
    )
    assert abs(p1 + px + p2 - 1.0) < 1e-9
    assert abs(sum(c["prob"] for c in new_cells) - 1.0) < 1e-9
    # With odds heavily favouring home, blended p1 should exceed the Poisson p1.
    assert p1 > pois[0]


def test_blend_three_sources_drops_missing_odds_gracefully():
    """odds=None must reduce to exactly the 2-source Poisson+Elo blend."""
    cells, pois = _flat_cells()
    elo = (0.40, 0.28, 0.32)
    _, p1_no_odds, px_no_odds, p2_no_odds = blend_three_sources(
        cells, pois, elo, None, w_poisson=0.7, w_elo=0.3, w_odds=0.55
    )
    # Compare against an explicit 2-way log-pool with the same 70/30 split.
    from wc_predictor.model.blend import log_pool
    p1_ref, px_ref, p2_ref = log_pool([pois, elo], [0.7, 0.3])
    assert abs(p1_no_odds - p1_ref) < 1e-9
    assert abs(px_no_odds - px_ref) < 1e-9
    assert abs(p2_no_odds - p2_ref) < 1e-9
