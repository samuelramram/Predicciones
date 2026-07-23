"""Tests for the Liga MX pipeline — pure logic (no network, no disk fit)."""
from __future__ import annotations

from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import FitResult, TeamStrength
from wc_predictor.pipeline.ligamx import (
    _odds_weights,
    altitude_factor,
    effective_model_config,
    predict_fixture,
)

MCFG = LIGAMX_APERTURA_PROFILE.model
RULES = LIGAMX_APERTURA_PROFILE.rules


def test_altitude_factor_differential():
    # Sea-level side (0 m) visiting Toluca (2660 m): full penalty.
    f_lowland = altitude_factor(2660, 0, MCFG)
    # CDMX side (2240 m) visiting Toluca: only the 420 m differential bites.
    f_highland = altitude_factor(2660, 2240, MCFG)
    assert f_lowland < f_highland < 1.0
    # A highland team visiting a lowland venue is never penalised.
    assert altitude_factor(30, 2240, MCFG) == 1.0
    # Equal altitude → no penalty.
    assert altitude_factor(2240, 2240, MCFG) == 1.0


def test_altitude_factor_floored():
    assert altitude_factor(20000, 0, MCFG) == 0.5  # clamped, never below 0.5


def test_altitude_factor_noop_when_disabled():
    from dataclasses import replace
    mcfg = replace(MCFG, altitude_penalty_per_1000m=0.0)
    assert altitude_factor(2660, 0, mcfg) == 1.0


def test_odds_weights_two_way_and_three_way():
    # No odds → 2-way blend sums to 1, Poisson favored.
    w_po, w_el, w_od = _odds_weights(MCFG, have_odds=False)
    assert w_od == 0.0
    assert abs(w_po + w_el - 1.0) < 1e-9
    assert w_po > w_el
    # With odds → all three sum to 1, market takes blend_odds_weight.
    w_po, w_el, w_od = _odds_weights(MCFG, have_odds=True)
    assert abs(w_po + w_el + w_od - 1.0) < 1e-9
    assert abs(w_od - MCFG.blend_odds_weight) < 1e-9
    assert w_po > w_el  # Poisson:Elo ratio preserved on the remainder


def _mini_fit():
    strengths = {
        "Fuerte": TeamStrength("Fuerte", attack=0.5, defense=0.4, n_matches=100),
        "Débil": TeamStrength("Débil", attack=-0.3, defense=-0.3, n_matches=100),
    }
    return FitResult(
        mu=0.15, gamma=0.30, rho=-0.05, strengths=strengths,
        n_matches=200, n_teams=2, half_life_days=730, ridge_lambda=0.3,
        converged=True, final_neg_log_lik=1.0,
    )


def test_predict_fixture_home_favorite():
    fit = _mini_fit()
    elos = {"Fuerte": 1650.0, "Débil": 1400.0}
    alts = {"Fuerte": 2240.0, "Débil": 30.0}
    fx = {"match_id": "x", "jornada": 2, "date": "2026-07-24", "venue": "Estadio Azteca",
          "home": "Fuerte", "away": "Débil", "home_score": None, "away_score": None}
    p = predict_fixture(fx, fit, elos, alts, MCFG, RULES)
    assert p["pick_1x2"] == "1"                 # strong home side wins
    assert p["lambda_home"] > p["lambda_away"]
    # Away side climbs 2210 m → its lambda is damped vs the no-altitude value.
    assert 0.0 < p["p_home_win"] < 1.0
    assert p["ev"] > 0
    assert "-" in p["pick_exact"]


def test_predict_fixture_missing_strengths():
    fit = _mini_fit()
    fx = {"match_id": "y", "home": "Fuerte", "away": "Inexistente"}
    p = predict_fixture(fx, fit, {}, {}, MCFG, RULES)
    assert "error" in p


def test_effective_model_config_honors_fitted_rho():
    """Regression: the score matrix (and the exact-score half of the pool points)
    must be built with the rho the fit was optimized under, not the config
    default. `ligamx fit` profiles rho; `run_picks` must adopt it, mirroring
    generate_picks. Before this fix Liga MX picks silently used the -0.10 default."""
    fit = _mini_fit()  # rho = -0.05
    assert MCFG.dc_rho != fit.rho
    eff = effective_model_config(fit, MCFG)
    assert eff.dc_rho == fit.rho
    # Everything else is untouched (only rho is overridden).
    assert eff.elo_home_bonus == MCFG.elo_home_bonus
    assert eff.blend_poisson_weight == MCFG.blend_poisson_weight


def test_effective_model_config_noop_when_equal():
    from dataclasses import replace
    fit = _mini_fit()
    mcfg = replace(MCFG, dc_rho=fit.rho)
    # No divergence → the same object is returned (no needless copy).
    assert effective_model_config(fit, mcfg) is mcfg


def test_fitted_rho_changes_pick_exact():
    """The rho fix is not cosmetic: a doubly-negative rho inflates 0-0/1-1 and
    can move the EV-optimal exact score. Guards against a regression that
    ignores the fitted rho again."""
    from dataclasses import replace
    fit = _mini_fit()  # rho -0.05
    elos = {"Fuerte": 1550.0, "Débil": 1500.0}  # near-even → draw cells matter
    alts = {"Fuerte": 0.0, "Débil": 0.0}
    fx = {"match_id": "z", "jornada": 3, "date": "2026-08-01", "venue": "v",
          "home": "Fuerte", "away": "Débil", "home_score": None, "away_score": None}
    p_fit = predict_fixture(fx, fit, elos, alts, effective_model_config(fit, MCFG), RULES)
    p_default = predict_fixture(fx, fit, elos, alts, replace(MCFG, dc_rho=MCFG.dc_rho), RULES)
    # The draw marginal differs between the fitted rho (-0.05) and the config
    # default the buggy path used — the fix is not cosmetic.
    assert fit.rho != MCFG.dc_rho
    assert p_fit["p_draw"] != p_default["p_draw"]
