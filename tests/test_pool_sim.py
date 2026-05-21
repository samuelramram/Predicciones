"""Tests for the Monte Carlo pool simulation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.config import QuinielaRules
from wc_predictor.model.pool_sim import _sample_score, simulate_pool

RULES = QuinielaRules()


def test_sample_score_returns_consistent_outcome():
    import random
    rng = random.Random(0)
    for _ in range(200):
        s = _sample_score(rng, "1")
        h, a = (int(x) for x in s.split("-"))
        assert h > a, f"home-win score {s} is not a home win"
    for _ in range(200):
        s = _sample_score(rng, "2")
        h, a = (int(x) for x in s.split("-"))
        assert a > h
    for _ in range(200):
        s = _sample_score(rng, "X")
        h, a = (int(x) for x in s.split("-"))
        assert h == a


def test_perfect_model_always_wins():
    """A model that scored the theoretical maximum should win essentially every sim."""
    matches = [
        {"actual_h": 2, "actual_a": 0, "elo_p1": 0.6, "elo_px": 0.25, "elo_p2": 0.15},
        {"actual_h": 1, "actual_a": 3, "elo_p1": 0.2, "elo_px": 0.25, "elo_p2": 0.55},
        {"actual_h": 0, "actual_a": 0, "elo_p1": 0.4, "elo_px": 0.3, "elo_p2": 0.3},
    ]
    max_points = len(matches) * RULES.points_exact
    result = simulate_pool(matches, model_points=max_points, rules=RULES,
                           n_opponents=29, n_sims=2000, seed=1)
    assert result.win_rate > 0.97


def test_zero_point_model_basically_never_wins():
    matches = [
        {"actual_h": 2, "actual_a": 0, "elo_p1": 0.6, "elo_px": 0.25, "elo_p2": 0.15},
        {"actual_h": 1, "actual_a": 3, "elo_p1": 0.2, "elo_px": 0.25, "elo_p2": 0.55},
    ]
    result = simulate_pool(matches, model_points=0, rules=RULES,
                           n_opponents=29, n_sims=2000, seed=2)
    assert result.win_rate < 0.05
    assert result.mean_rank > 20  # near the bottom of a 30-player pool


def test_rank_histogram_sums_to_n_sims():
    matches = [
        {"actual_h": 1, "actual_a": 0, "elo_p1": 0.5, "elo_px": 0.3, "elo_p2": 0.2},
        {"actual_h": 2, "actual_a": 1, "elo_p1": 0.45, "elo_px": 0.3, "elo_p2": 0.25},
    ]
    n_sims = 3000
    result = simulate_pool(matches, model_points=3, rules=RULES,
                           n_opponents=29, n_sims=n_sims, seed=3)
    assert sum(result.rank_histogram.values()) == n_sims
    assert 0.0 <= result.win_rate <= 1.0
    assert 1.0 <= result.mean_rank <= 30.0


def test_higher_model_points_improves_rank():
    matches = [
        {"actual_h": 2, "actual_a": 1, "elo_p1": 0.5, "elo_px": 0.3, "elo_p2": 0.2}
        for _ in range(10)
    ]
    low = simulate_pool(matches, model_points=3, rules=RULES, n_opponents=29, n_sims=3000, seed=4)
    high = simulate_pool(matches, model_points=15, rules=RULES, n_opponents=29, n_sims=3000, seed=4)
    assert high.mean_rank < low.mean_rank
    assert high.win_rate >= low.win_rate
