"""Tests for the Liga MX pipeline — pure logic (no network, no disk fit)."""
from __future__ import annotations

from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import FitResult, TeamStrength
from wc_predictor.pipeline.ligamx import (
    _odds_weights,
    altitude_factor,
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


def test_odds_weights_sum_to_one_and_favor_poisson():
    w_po, w_el = _odds_weights(MCFG)
    assert abs(w_po + w_el - 1.0) < 1e-9
    assert w_po > w_el  # backtested ≈0.70/0.30


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
