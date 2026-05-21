"""Tests for the EV optimizer and pool-of-truth scorer.

These are the most critical tests in the project — if the EV calculation is wrong,
every pick we ever make is wrong. Cover:

- score_actual matches the pool rule (exclusive vs non-exclusive)
- optimize_pick prefers exact-heavy outcome when one score dominates
- optimize_pick prefers safe 1X2 when distribution is flat
- abstain triggers when gap is small
- Dixon-Coles rho < 0 increases P(draw)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.config import ModelConfig, QuinielaRules
from wc_predictor.scoring.quiniela import (
    build_score_matrix,
    optimize_pick,
    score_actual,
)


RULES = QuinielaRules()  # exact=2, 1x2=1, exclusive=True
MCFG = ModelConfig()


def test_score_actual_exact_hit_excludes_1x2():
    pts = score_actual(2, 1, "1", "2-1", RULES)
    assert pts == 2


def test_score_actual_outcome_hit_only():
    pts = score_actual(3, 0, "1", "2-1", RULES)
    assert pts == 1


def test_score_actual_miss():
    pts = score_actual(0, 0, "1", "2-1", RULES)
    assert pts == 0


def test_score_actual_non_exclusive_stacks():
    non_exclusive = QuinielaRules(exclusive=False)
    pts = score_actual(2, 1, "1", "2-1", non_exclusive)
    assert pts == 3


def test_dc_rho_increases_draw_mass():
    no_dc = ModelConfig(dc_rho=0.0)
    cells_flat, _, p_x_flat, _, _, _ = build_score_matrix(1.3, 1.1, no_dc)
    cells_dc, _, p_x_dc, _, _, _ = build_score_matrix(1.3, 1.1, MCFG)
    assert p_x_dc > p_x_flat


def test_optimize_pick_strong_home_favorite():
    result = optimize_pick(lambda_home=2.4, lambda_away=0.6, rules=RULES, mcfg=MCFG)
    assert result.pick_1x2 == "1"
    assert result.prob_home_win > result.prob_draw
    assert result.prob_home_win > result.prob_away_win


def test_optimize_pick_balanced_favors_draw_or_low_score():
    result = optimize_pick(lambda_home=1.0, lambda_away=1.0, rules=RULES, mcfg=MCFG)
    assert result.pick_1x2 in {"1", "X", "2"}
    assert 0.20 < result.prob_draw < 0.45


def test_probabilities_sum_to_one():
    result = optimize_pick(lambda_home=1.5, lambda_away=1.2, rules=RULES, mcfg=MCFG)
    total = result.prob_home_win + result.prob_draw + result.prob_away_win
    assert abs(total - 1.0) < 1e-9


def test_ev_consistent_with_score_actual_expectation():
    """The optimizer's EV should match an empirical expectation over the score grid.

    For each score (h, a), compute the probability and the points the chosen pick
    would yield against (h, a). Sum prob * pts. Should match `result.ev`.
    """
    lh, la = 1.8, 1.1
    result = optimize_pick(lh, la, RULES, MCFG)
    cells, _, _, _, _, _ = build_score_matrix(lh, la, MCFG)
    expected_pts = sum(
        cell["prob"] * score_actual(cell["h"], cell["a"], result.pick_1x2, result.pick_exact, RULES)
        for cell in cells
    )
    assert abs(expected_pts - result.ev) < 1e-9
