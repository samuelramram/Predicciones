"""Tests for the Elo-to-1X2 conversion and the Poisson + Elo blend."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.model.blend import (
    blend_poisson_with_elo,
    log_pool,
    rescale_cells_to_marginals,
)
from wc_predictor.ratings.elo import elo_to_1x2_probs


def test_elo_probs_sum_to_one():
    p_h, p_d, p_a = elo_to_1x2_probs(1800.0, 1500.0)
    assert abs(p_h + p_d + p_a - 1.0) < 1e-9


def test_elo_higher_rating_favors_home():
    p_h, _, p_a = elo_to_1x2_probs(2000.0, 1500.0)
    assert p_h > p_a


def test_elo_equal_ratings_at_neutral_yields_symmetric_probs():
    p_h, p_d, p_a = elo_to_1x2_probs(1700.0, 1700.0, home_advantage_elo=0.0)
    assert abs(p_h - p_a) < 1e-9
    assert p_d > 0.20  # equal teams → high draw rate


def test_elo_home_advantage_shifts_probs():
    p_h_neutral, _, _ = elo_to_1x2_probs(1700.0, 1700.0, home_advantage_elo=0.0)
    p_h_host, _, _ = elo_to_1x2_probs(1700.0, 1700.0, home_advantage_elo=80.0)
    assert p_h_host > p_h_neutral


def test_elo_draw_rate_drops_with_large_gap():
    _, p_d_close, _ = elo_to_1x2_probs(1700.0, 1700.0)
    _, p_d_far, _ = elo_to_1x2_probs(2000.0, 1400.0)  # 600 gap
    assert p_d_far < p_d_close


def test_log_pool_with_equal_weights_is_geometric_mean():
    a = (0.5, 0.3, 0.2)
    b = (0.3, 0.4, 0.3)
    pooled = log_pool([a, b], [1.0, 1.0])
    import math
    raw = (math.sqrt(0.5 * 0.3), math.sqrt(0.3 * 0.4), math.sqrt(0.2 * 0.3))
    s = sum(raw)
    expected = (raw[0] / s, raw[1] / s, raw[2] / s)
    for p, e in zip(pooled, expected):
        assert abs(p - e) < 1e-9


def test_rescale_cells_preserves_within_group_shape():
    """When you rescale to new marginals, the conditional shape within each outcome
    group must be preserved exactly."""
    cells = [
        {"score": "1-0", "outcome": "1", "prob": 0.12},
        {"score": "2-0", "outcome": "1", "prob": 0.08},
        {"score": "1-1", "outcome": "X", "prob": 0.10},
        {"score": "0-0", "outcome": "X", "prob": 0.05},
        {"score": "0-1", "outcome": "2", "prob": 0.15},
    ]
    new = rescale_cells_to_marginals(cells, target_p1=0.5, target_px=0.2, target_p2=0.3)
    # Within outcome=1, ratio of 1-0 to 2-0 should be preserved: 0.12/0.08 = 1.5
    p10 = next(c["prob"] for c in new if c["score"] == "1-0")
    p20 = next(c["prob"] for c in new if c["score"] == "2-0")
    assert abs(p10 / p20 - 1.5) < 1e-9
    # Marginals should match the target (after renormalization)
    new_p1 = sum(c["prob"] for c in new if c["outcome"] == "1")
    new_px = sum(c["prob"] for c in new if c["outcome"] == "X")
    new_p2 = sum(c["prob"] for c in new if c["outcome"] == "2")
    assert abs(new_p1 - 0.5) < 1e-9
    assert abs(new_px - 0.2) < 1e-9
    assert abs(new_p2 - 0.3) < 1e-9


def test_blend_poisson_with_elo_smoke():
    """End-to-end smoke: build a fake Poisson matrix + Elo triplet, blend, verify
    output shape and that the result is a valid distribution."""
    cells = [
        {"score": "1-0", "outcome": "1", "prob": 0.15},
        {"score": "2-0", "outcome": "1", "prob": 0.10},
        {"score": "2-1", "outcome": "1", "prob": 0.12},
        {"score": "1-1", "outcome": "X", "prob": 0.13},
        {"score": "0-0", "outcome": "X", "prob": 0.07},
        {"score": "0-1", "outcome": "2", "prob": 0.20},
        {"score": "0-2", "outcome": "2", "prob": 0.13},
        {"score": "1-2", "outcome": "2", "prob": 0.10},
    ]
    pp1 = sum(c["prob"] for c in cells if c["outcome"] == "1")
    ppx = sum(c["prob"] for c in cells if c["outcome"] == "X")
    pp2 = sum(c["prob"] for c in cells if c["outcome"] == "2")
    # Elo says: home strongly favored (P_h=0.6, P_x=0.2, P_a=0.2)
    new_cells, p1, px, p2 = blend_poisson_with_elo(
        cells, pp1, ppx, pp2,
        elo_p1=0.6, elo_px=0.2, elo_p2=0.2,
        w_poisson=0.5, w_elo=0.5,
    )
    assert abs(p1 + px + p2 - 1.0) < 1e-9
    assert abs(sum(c["prob"] for c in new_cells) - 1.0) < 1e-9
    # Blend should shift mass toward home wins compared to the original Poisson marginals
    assert p1 > pp1 - 0.01  # at minimum no worse; in practice strictly higher
