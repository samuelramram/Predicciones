"""Tests for the WC λ adjustments (uniform inflation + skill-gap inflation)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from wc_predictor.config import DEFAULT_CONFIG
from wc_predictor.model.adjustments import apply_wc_lambdas


MCFG = DEFAULT_CONFIG.model


def test_uniform_inflation_only_when_no_mismatch():
    # Even teams (ratio < threshold) get only the WC inflation, no skill-gap term.
    lh, la = apply_wc_lambdas(1.5, 1.4, MCFG)
    assert lh == pytest.approx(1.5 * MCFG.wc_lambda_inflation)
    assert la == pytest.approx(1.4 * MCFG.wc_lambda_inflation)


def test_mismatch_inactive_below_threshold():
    # ratio_raw = 1.8 / 1.0 = 1.8, post-inflation ratio same.
    # threshold default 3.0 → mismatch does NOT fire.
    lh, la = apply_wc_lambdas(1.8, 1.0, MCFG)
    base_lh = 1.8 * MCFG.wc_lambda_inflation
    base_la = 1.0 * MCFG.wc_lambda_inflation
    assert lh == pytest.approx(base_lh)
    assert la == pytest.approx(base_la)


def test_mismatch_boosts_stronger_dampens_weaker():
    # Spain–Cape Verde-like: λ_raw ≈ (2.3, 0.58), ratio ≈ 3.97
    lh_raw, la_raw = 2.30, 0.58
    lh, la = apply_wc_lambdas(lh_raw, la_raw, MCFG)
    # Stronger side got more than just the uniform inflation
    assert lh > lh_raw * MCFG.wc_lambda_inflation * 1.05
    # Weaker side got LESS than just the uniform inflation
    assert la < la_raw * MCFG.wc_lambda_inflation * 0.95


def test_mismatch_works_with_away_stronger():
    # Same magnitude but the away team is the dominant one.
    lh, la = apply_wc_lambdas(0.58, 2.30, MCFG)
    base_lh = 0.58 * MCFG.wc_lambda_inflation
    base_la = 2.30 * MCFG.wc_lambda_inflation
    assert la > base_la * 1.05  # away (stronger) boosted
    assert lh < base_lh * 0.95  # home (weaker) damped


def test_mismatch_saturates():
    # Extreme ratio: stronger side should be boosted by exactly mismatch_strong_boost.
    lh, la = apply_wc_lambdas(5.0, 0.3, MCFG)
    base_lh = 5.0 * MCFG.wc_lambda_inflation
    base_la = 0.3 * MCFG.wc_lambda_inflation
    assert lh == pytest.approx(base_lh * MCFG.mismatch_strong_boost, rel=1e-6)
    assert la == pytest.approx(base_la * MCFG.mismatch_weak_damp, rel=1e-6)


def test_mismatch_can_be_disabled_via_config():
    cfg_off = replace(MCFG, mismatch_strong_boost=1.0, mismatch_weak_damp=1.0)
    lh, la = apply_wc_lambdas(2.30, 0.58, cfg_off)
    # With boost=1 and damp=1, only the uniform inflation applies.
    assert lh == pytest.approx(2.30 * cfg_off.wc_lambda_inflation)
    assert la == pytest.approx(0.58 * cfg_off.wc_lambda_inflation)


def test_mismatch_pick_override_picks_realistic_score():
    """When the dominant outcome's marginal exceeds the threshold and a higher
    blowout score is within EV tolerance of the modal, prefer the higher score."""
    from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

    lh, la = apply_wc_lambdas(2.30, 0.58, MCFG)  # Spain–Cape Verde-like
    cells, p1, px, p2, mass, gmax = build_score_matrix(lh, la, MCFG)
    pick = optimize_pick_from_cells(
        cells, p1, px, p2, mass, gmax,
        DEFAULT_CONFIG.rules, MCFG, forbid_outcomes=("X",),
    )
    # Without inflation: pick would be 2-0. With it + override, pick should be ≥3 home goals.
    h, _, a = pick.pick_exact.partition("-")
    assert int(h) - int(a) >= 2, f"Expected blowout pick, got {pick.pick_exact}"
    assert int(h) >= 3, f"Expected home goals >= 3, got {pick.pick_exact}"
    assert pick.pick_1x2 == "1"


def test_mismatch_pick_override_inactive_for_close_match():
    """For an even match (Ecuador vs Germany-like), the override must NOT fire."""
    from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

    lh, la = apply_wc_lambdas(1.25, 0.91, MCFG)
    cells, p1, px, p2, mass, gmax = build_score_matrix(lh, la, MCFG)
    pick = optimize_pick_from_cells(
        cells, p1, px, p2, mass, gmax,
        DEFAULT_CONFIG.rules, MCFG, forbid_outcomes=("X",),
    )
    # P(home wins) ~0.44 — well below mismatch_pick_min_dominant (0.75).
    # Override must not fire; pick should remain the modal home-win cell.
    assert p1 < MCFG.mismatch_pick_min_dominant
