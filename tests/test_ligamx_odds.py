"""Tests for the Liga MX odds parsing — pure functions, no network."""
from __future__ import annotations

from wc_predictor.ingest.ligamx_odds import _devig_two, parse_h2h, parse_markets


def _payload():
    return [{
        "home_team": "Atlante FC", "away_team": "América",
        "commence_time": "2026-07-23T01:00:00Z",
        "bookmakers": [
            {"key": "pinnacle", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Atlante FC", "price": 4.5},
                    {"name": "América", "price": 1.8},
                    {"name": "Draw", "price": 3.6},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "point": 2.5, "price": 1.9},
                    {"name": "Under", "point": 2.5, "price": 1.95},
                ]},
            ]},
            {"key": "betway", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Atlante FC", "price": 4.8},   # best price for home
                    {"name": "América", "price": 1.75},
                    {"name": "Draw", "price": 3.5},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "point": 2.5, "price": 2.0},   # best over
                    {"name": "Under", "point": 2.5, "price": 1.85},
                ]},
            ]},
        ],
    }]


def test_devig_two_sums_to_one():
    a, b = _devig_two(1.9, 1.95)
    assert abs(a + b - 1.0) < 1e-9
    assert a > b  # 1.9 is the shorter price → higher prob


def test_parse_h2h_normalizes_names_and_devigs():
    out = parse_h2h(_payload())
    assert "Atlante|América" in out
    e = out["Atlante|América"]
    assert abs(e["p1"] + e["px"] + e["p2"] - 1.0) < 1e-6
    assert e["p2"] > e["p1"]          # América favored
    assert e["n_books"] == 2
    assert e["commence_time"] == "2026-07-23T01:00:00Z"


def test_parse_markets_fair_and_best_price():
    out = parse_markets(_payload())
    m = out["Atlante|América"]
    # 1X2 fair probs sum to 1; best prices are the max across books.
    assert abs(sum(m["h2h"]["fair"].values()) - 1.0) < 1e-6
    assert m["h2h"]["best"]["1"] == {"price": 4.8, "book": "betway"}
    assert m["h2h"]["best"]["2"]["price"] == 1.8   # pinnacle shorter? max is 1.8 vs 1.75
    # Totals line 2.5 present with fair + best.
    assert m["main_total_line"] == 2.5
    t = m["totals"]["2.5"]
    assert abs(t["fair"]["over"] + t["fair"]["under"] - 1.0) < 1e-6
    assert t["best"]["over"] == {"price": 2.0, "book": "betway"}
    assert t["n_books"] == 2
