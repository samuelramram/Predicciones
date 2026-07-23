"""Tests for the Liga MX walk-forward backtest — the honest-baseline contract.

The full walk-forward runs on the committed history and is exercised by hand /
CI-lite; here we lock the pure pieces so the reported edge stays apples-to-apples:
the baselines must be a function of exactly the rows passed in (the model's
scored set), not a differently-sized slice.
"""
from __future__ import annotations

from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.pipeline.ligamx_backtest import baseline_points

RULES = LIGAMX_APERTURA_PROFILE.rules


def _row(h, a):
    return {"date": "2026-01-01", "home": "A", "away": "B",
            "home_score": h, "away_score": a}


def test_baseline_points_scores_exactly_given_rows():
    # always-1-0: 2 pts on a real 1-0 (exact), 1 pt on any other home win, 0 else.
    rows = [_row(1, 0), _row(2, 1), _row(0, 0), _row(0, 2)]
    b = baseline_points(rows, RULES)
    # 1-0 → exact (2); 2-1 → home win only (1); 0-0 draw → 0; 0-2 away → 0.
    assert b["always_1_0"] == 2 + 1 + 0 + 0
    # home-win 1X2 (generic 9-9 exact, only the 1X2 point can land): 1+1+0+0.
    assert b["always_home_win_1x2"] == 1 + 1 + 0 + 0


def test_baseline_points_is_row_count_sensitive():
    """Core of the fix: baselines depend on WHICH rows they score. Two disjoint
    slices of the same match list give different baselines — so scoring the
    model on one slice and the baseline on another (the old bug) is invalid."""
    rows = [_row(1, 0)] * 3 + [_row(0, 2)] * 3
    first_half = baseline_points(rows[:3], RULES)   # all 1-0 → 3 exactos
    second_half = baseline_points(rows[3:], RULES)  # all 0-2 → 0
    assert first_half["always_1_0"] == 6            # 3 * 2
    assert second_half["always_1_0"] == 0
    assert first_half != second_half


def test_baseline_points_empty():
    assert baseline_points([], RULES) == {"always_1_0": 0, "always_home_win_1x2": 0}
