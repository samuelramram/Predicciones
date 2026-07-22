"""Tests for the value-betting core (pure functions)."""
from __future__ import annotations

from wc_predictor.betting.value import (
    btts_probs,
    ev_per_unit,
    find_value_bets,
    kelly_fraction,
    over_under_probs,
)


def _cells():
    # Minimal score matrix: 0-0, 1-0, 1-1, 2-1, 0-2.
    raw = [(0, 0, 0.30), (1, 0, 0.25), (1, 1, 0.20), (2, 1, 0.15), (0, 2, 0.10)]
    return [{"h": h, "a": a, "prob": p, "outcome": "X" if h == a else ("1" if h > a else "2")}
            for h, a, p in raw]


def test_ev_and_kelly():
    # Fair coin at 2.10 → +EV; at 2.00 → break-even.
    assert ev_per_unit(0.5, 2.10) > 0
    assert abs(ev_per_unit(0.5, 2.0)) < 1e-9
    # No edge → zero Kelly; edge → positive, bounded.
    assert kelly_fraction(0.5, 2.0) == 0.0
    assert kelly_fraction(0.6, 2.0) > 0
    assert kelly_fraction(0.4, 2.0) == 0.0  # negative edge floored at 0


def test_over_under_and_btts():
    over, under = over_under_probs(_cells(), 2.5)
    assert abs(over + under - 1.0) < 1e-9
    # Only 2-1 (=3 goals) exceeds 2.5 → over = 0.15.
    assert abs(over - 0.15) < 1e-9
    yes, no = btts_probs(_cells())
    # 1-1 and 2-1 have both scoring → 0.35.
    assert abs(yes - 0.35) < 1e-9


def test_find_value_bets_flags_only_positive_edge():
    cells = _cells()
    # Model 1X2 (independent). Market fair says home 40%, but model says 55%.
    model_1x2 = (0.55, 0.25, 0.20)
    market = {
        "h2h": {
            "fair": {"1": 0.40, "X": 0.30, "2": 0.30},
            "best": {"1": {"price": 2.5, "book": "x"},
                     "X": {"price": 3.0, "book": "y"},
                     "2": {"price": 3.2, "book": "z"}},
        },
        "totals": {},
    }
    bets = find_value_bets("A vs B", model_1x2, cells, market, edge_min=0.03)
    # Home has a +15pt edge at 2.5 → flagged; X/2 model<fair → not flagged.
    assert [b.selection for b in bets] == ["1"]
    b = bets[0]
    assert b.market == "1X2" and b.book == "x"
    assert b.edge > 0.14 and b.ev > 0 and 0 < b.kelly_stake <= 0.02


def test_find_value_bets_respects_max_stake_cap():
    model_1x2 = (0.95, 0.03, 0.02)  # absurd edge → Kelly would be huge
    market = {"h2h": {"fair": {"1": 0.5, "X": 0.25, "2": 0.25},
                      "best": {"1": {"price": 3.0, "book": "x"}}}, "totals": {}}
    bets = find_value_bets("A vs B", model_1x2, _cells(), market,
                           edge_min=0.03, kelly_mult=0.25, max_stake=0.02)
    assert bets and bets[0].kelly_stake == 0.02  # hard cap holds


def test_find_value_bets_none_when_model_agrees_with_market():
    model_1x2 = (0.40, 0.30, 0.30)
    market = {"h2h": {"fair": {"1": 0.40, "X": 0.30, "2": 0.30},
                      "best": {"1": {"price": 2.4, "book": "x"}}}, "totals": {}}
    assert find_value_bets("A vs B", model_1x2, _cells(), market, edge_min=0.03) == []
