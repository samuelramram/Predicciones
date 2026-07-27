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


def test_ligamx_tuned_calibration():
    """Fase 1b.2 walk-forward re-fit: stronger localía than the WC default and
    more Elo weight both backtested better on Liga MX (441 vs 434 pts oos).
    Locks the tuned values so a future edit can't silently revert them."""
    m = LIGAMX_APERTURA_PROFILE.model
    d = ModelConfig()
    # Home advantage tuned UP from the shared default.
    assert m.elo_home_bonus == 100.0
    assert m.elo_home_bonus > d.elo_home_bonus
    # Blend leans MORE on Elo than the WC 70/30, and the pair still sums to 1.
    assert m.blend_poisson_weight == 0.60
    assert m.blend_elo_weight == 0.40
    assert abs(m.blend_poisson_weight + m.blend_elo_weight - 1.0) < 1e-9
    # goal_env_mult stays neutral — the league fit self-calibrates to ~2.84 g/match.
    assert m.goal_env_mult == 1.0


def test_ligamx_metadata():
    p = LIGAMX_APERTURA_PROFILE
    assert p.thesportsdb_league_id == 4350
    assert p.elo_source == "replay_ligamx"
    assert p.neutral_venues is False
    assert p.home_advantage_mode == "per_team"
    assert p.odds_sport_key == "soccer_mexico_ligamx"
    # 17 regular jornadas present.
    assert "j1" in p.round_tokens and "j17" in p.round_tokens
    # Liguilla rounds present and two-legged. Apertura 2026 scrapped the Play-In:
    # top-8 go straight to two-legged quarters, so play_in is NOT a round token.
    assert set(p.two_legged_rounds) == {"quarter_final", "semi_final", "final"}
    assert {"quarter_final", "semi_final", "final"} <= set(p.round_tokens)
    assert "play_in" not in p.round_tokens
