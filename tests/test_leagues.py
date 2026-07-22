"""Tests for the league-profile layer (Fase 0 of the Liga MX adaptation).

These lock two invariants:
  1. The WC profile is a faithful mirror of today's config (no behaviour change).
  2. The Liga MX profile neutralises every World-Cup-only knob, so those layers
     can't silently distort Liga MX lambdas before the Fase 1 re-fit.
"""
from __future__ import annotations

from wc_predictor.config import DATA_DIR, ModelConfig, QuinielaRules
from wc_predictor.leagues import (
    DEFAULT_PROFILE_KEY,
    LIGAMX_APERTURA_PROFILE,
    PROFILES,
    WC2026_PROFILE,
    get_profile,
)


def test_registry_and_default():
    assert set(PROFILES) == {"wc2026", "ligamx_apertura"}
    assert DEFAULT_PROFILE_KEY == "wc2026"
    assert get_profile() is WC2026_PROFILE
    assert get_profile("ligamx_apertura") is LIGAMX_APERTURA_PROFILE


def test_unknown_profile_raises():
    import pytest

    with pytest.raises(SystemExit):
        get_profile("premier_league")


def test_wc_profile_matches_current_defaults():
    """The WC profile must reproduce the untouched config so the existing
    pipeline and its 166 tests keep the exact same numbers."""
    assert WC2026_PROFILE.model == ModelConfig()
    assert WC2026_PROFILE.rules == QuinielaRules()
    assert WC2026_PROFILE.thesportsdb_league_id == 4429
    assert WC2026_PROFILE.neutral_venues is True
    assert WC2026_PROFILE.home_advantage_mode == "host_only"
    assert WC2026_PROFILE.two_legged_rounds == ()


def test_data_dir_resolves_under_data():
    assert WC2026_PROFILE.data_dir == DATA_DIR / "wc2026"
    assert LIGAMX_APERTURA_PROFILE.data_dir == DATA_DIR / "ligamx"


def test_ligamx_neutralises_wc_only_knobs():
    m = LIGAMX_APERTURA_PROFILE.model
    # Host boosts off (localía is per-team, not host-only).
    assert m.host_advantage_usa == 1.0
    assert m.host_advantage_mexico == 1.0
    assert m.host_advantage_canada == 1.0
    # WC goal inflation off.
    assert m.wc_lambda_inflation == 1.0
    # Mismatch ramp effectively disabled (threshold pushed out, gains at 1.0).
    assert m.mismatch_strong_boost == 1.0
    assert m.mismatch_weak_damp == 1.0
    assert m.mismatch_ratio_threshold >= 6.0
    # J3 group-qualification rotation inert.
    assert m.qual_rotation_lambda_mult == 1.0


def test_ligamx_keeps_shared_knobs_active():
    m = LIGAMX_APERTURA_PROFILE.model
    # Altitude matters (more, even) in Liga MX — must stay on.
    assert m.altitude_penalty_per_1000m > 0.0
    # The engine's core grid / ridge / draw gates are shared, untouched defaults.
    assert m.ridge_lambda == ModelConfig().ridge_lambda
    assert m.poisson_grid_target_mass == ModelConfig().poisson_grid_target_mass


def test_ligamx_metadata():
    p = LIGAMX_APERTURA_PROFILE
    assert p.thesportsdb_league_id == 4350
    assert p.elo_source == "clubelo"
    assert p.neutral_venues is False
    assert p.home_advantage_mode == "per_team"
    assert p.odds_sport_key == "soccer_mexico_ligamx"
    # 17 regular jornadas present.
    assert "j1" in p.round_tokens and "j17" in p.round_tokens
    # Liguilla rounds present and two-legged where expected.
    assert set(p.two_legged_rounds) == {"quarter_final", "semi_final", "final"}
    assert "play_in" in p.round_tokens
