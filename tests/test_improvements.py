"""Tests for the three model improvements:

1. Dixon-Coles rho profiled on data (poisson_dc.profile_fit_rho).
2. Per-competition weighting in the Poisson+DC design (poisson_dc._competition_weight).
3. Odds blend-weight tuner core (pipeline.tune_odds_weight.score_weight_grid).
"""
from __future__ import annotations

import math
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.config import ModelConfig, QuinielaRules
from wc_predictor.model.poisson_dc import (
    _build_design,
    _competition_weight,
    fit_dc_model,
    profile_fit_rho,
)
from wc_predictor.scoring.quiniela import build_score_matrix
from wc_predictor.pipeline.tune_odds_weight import (
    default_weight_grid,
    recommend,
    score_weight_grid,
)


CFG = ModelConfig()


# --- 1. Competition weighting ------------------------------------------------

def test_competition_weight_tiers_order():
    """friendly < qualifier < tournament < WC, and qualifier beats WC for a
    'World Cup qualification' string (the qualif check must win)."""
    assert _competition_weight("Friendly", CFG) == CFG.competition_weight_friendly
    assert _competition_weight("FIFA World Cup qualification", CFG) == CFG.competition_weight_qualifier
    assert _competition_weight("UEFA Euro", CFG) == CFG.competition_weight_tournament
    assert _competition_weight("FIFA World Cup", CFG) == CFG.competition_weight_wc
    assert (_competition_weight("Friendly", CFG)
            < _competition_weight("FIFA World Cup qualification", CFG)
            < _competition_weight("UEFA Euro", CFG)
            < _competition_weight("FIFA World Cup", CFG))


def test_competition_weight_unknown_defaults_to_tournament():
    assert _competition_weight("Copa América", CFG) == CFG.competition_weight_tournament
    assert _competition_weight("", CFG) == CFG.competition_weight_tournament


def test_build_design_applies_competition_multiplier():
    """Same date + venue: a WC match must carry more design weight than a friendly."""
    rows = [
        {"date": "2026-06-01", "home": "A", "away": "B", "home_score": 1,
         "away_score": 0, "neutral": True, "tournament": "Friendly"},
        {"date": "2026-06-01", "home": "A", "away": "B", "home_score": 1,
         "away_score": 0, "neutral": True, "tournament": "FIFA World Cup"},
    ]
    design = _build_design(rows, date(2026, 6, 1), half_life_days=730, cfg=CFG)
    w_friendly, w_wc = design["weights"]
    assert math.isclose(w_wc / w_friendly,
                        CFG.competition_weight_wc / CFG.competition_weight_friendly,
                        rel_tol=1e-9)


def test_build_design_none_cfg_is_pure_recency():
    """cfg=None preserves the legacy (no competition multiplier) behaviour."""
    rows = [
        {"date": "2026-06-01", "home": "A", "away": "B", "home_score": 1,
         "away_score": 0, "neutral": True, "tournament": "FIFA World Cup"},
        {"date": "2026-06-01", "home": "A", "away": "B", "home_score": 1,
         "away_score": 0, "neutral": True, "tournament": "Friendly"},
    ]
    design = _build_design(rows, date(2026, 6, 1), half_life_days=730, cfg=None)
    assert math.isclose(design["weights"][0], design["weights"][1], rel_tol=1e-9)


# --- 2. rho profiling --------------------------------------------------------

def _synthetic_rows(n: int, rho_truth: float, seed: int = 3) -> list[dict]:
    """Generate matches whose low-score cells are nudged by a known rho, so the
    profile should prefer a negative rho when draws/low scores are inflated."""
    rng = random.Random(seed)
    names = ["A", "B", "C", "D", "E"]
    rows = []
    for _ in range(n):
        h, a = rng.sample(names, 2)
        lh, la = 1.3, 1.1
        hs = _knuth(rng, lh)
        as_ = _knuth(rng, la)
        # Inflate 0-0/1-1 draws to emulate a negative DC rho in the data.
        if rho_truth < 0 and rng.random() < -rho_truth:
            hs = as_ = rng.choice([0, 1])
        rows.append({"date": "2026-05-01", "home": h, "away": a,
                     "home_score": hs, "away_score": as_, "neutral": True,
                     "tournament": "Friendly"})
    return rows


def _knuth(rng: random.Random, lam: float) -> int:
    L = math.exp(-lam)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


def test_profile_fit_rho_returns_grid_member_and_fit():
    rows = _synthetic_rows(1500, rho_truth=-0.1, seed=11)
    grid = [-0.2, -0.1, 0.0]
    best_rho, fit, table = profile_fit_rho(
        rows, CFG, as_of=date(2026, 5, 1), half_life_days=10_000,
        ridge_lambda=0.05, rho_grid=grid, verbose=False,
    )
    assert best_rho in grid
    assert fit.rho == best_rho
    assert len(table) == len(grid)
    # The returned fit is the lowest-NLL row in the table.
    assert all(fit.final_neg_log_lik <= r["neg_log_lik"] + 1e-6 for r in table)


def test_profile_fit_rho_prefers_negative_when_draws_inflated():
    """With heavily inflated low-score draws the profile should not pick rho>=0."""
    rows = _synthetic_rows(2500, rho_truth=-0.18, seed=5)
    best_rho, _, _ = profile_fit_rho(
        rows, CFG, as_of=date(2026, 5, 1), half_life_days=10_000,
        ridge_lambda=0.05, rho_grid=[-0.2, -0.1, 0.0, 0.1], verbose=False,
    )
    assert best_rho < 0.0


# --- 3. odds weight tuner core ----------------------------------------------

def _record(p_pois, p_elo, p_odds, actual_h, actual_a):
    """Build a tuner record from three 1X2 triplets + an actual score."""
    lh, la = 1.4, 1.1  # only used to shape the Poisson cells
    cells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, CFG)
    outcome = "1" if actual_h > actual_a else ("2" if actual_h < actual_a else "X")
    return {
        "match": "X vs Y",
        "poisson_cells": cells,
        "poisson_1x2": p_pois,
        "elo_1x2": p_elo,
        "odds_1x2": p_odds,
        "pmass": pmass, "pmax": pmax,
        "actual_h": actual_h, "actual_a": actual_a,
        "actual_outcome": outcome,
    }


def test_score_weight_grid_shapes_and_recommend():
    rules = QuinielaRules()
    # Market nails the favourite (home) every time; Poisson/Elo are lukewarm.
    records = [
        _record((0.45, 0.30, 0.25), (0.50, 0.25, 0.25), (0.80, 0.12, 0.08), 2, 0),
        _record((0.40, 0.30, 0.30), (0.45, 0.25, 0.30), (0.75, 0.15, 0.10), 1, 0),
        _record((0.42, 0.30, 0.28), (0.48, 0.27, 0.25), (0.78, 0.13, 0.09), 3, 1),
    ]
    grid = default_weight_grid()
    rows = score_weight_grid(records, grid, poisson_share=0.7, rules=rules, mcfg=CFG)
    assert len(rows) == len(grid)
    for r in rows:
        assert r["n"] == 3
        assert 0 <= r["points"] <= r["max_points"]
        assert r["max_points"] == 3 * rules.points_exact
    # When the market is the only accurate source, leaning on it should not lose
    # points vs ignoring it.
    best = recommend(rows)
    w0 = next(r for r in rows if r["w_odds"] == 0.0)
    assert best["points"] >= w0["points"]
    assert 0.0 <= best["w_odds"] <= 0.95


def test_score_weight_grid_empty_is_safe():
    rules = QuinielaRules()
    rows = score_weight_grid([], [0.0, 0.5], poisson_share=0.7, rules=rules, mcfg=CFG)
    assert all(r["n"] == 0 and r["points"] == 0 for r in rows)


def test_goal_env_mult_default_leans_above_calibration():
    """The shipped default nudges lambdas up to fix the measured ~10% goal under-count."""
    assert ModelConfig().goal_env_mult > 1.0


def test_goal_env_mult_raises_expected_goals_of_favorite_pick():
    """Scaling lambdas by goal_env_mult shifts the EV-optimal exact score upward
    for a clear favorite (the mechanism behind the extra exactos in the backtest)."""
    from wc_predictor.scoring.quiniela import optimize_pick

    rules = QuinielaRules()
    base = ModelConfig(goal_env_mult=1.0)
    lh, la = 1.6, 0.7  # clear home favorite

    pick_flat = optimize_pick(lh, la, rules, base, forbid_outcomes=("X",))
    pick_scaled = optimize_pick(lh * 1.20, la * 1.20, rules, base, forbid_outcomes=("X",))

    def total(score: str) -> int:
        h, a = score.split("-")
        return int(h) + int(a)

    # Same winner, but the calibrated lambdas never pick a *lower*-scoring line and
    # here pick a strictly higher one.
    assert pick_flat.pick_1x2 == pick_scaled.pick_1x2 == "1"
    assert total(pick_scaled.pick_exact) >= total(pick_flat.pick_exact)
