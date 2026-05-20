"""Tests for Poisson + Dixon-Coles fit and prediction.

Key invariants:
- Synthetic-data recovery: if we generate matches from known strengths, the MLE
  should recover them up to the sum-to-zero gauge.
- predict_lambdas: home advantage strictly increases lambda_home for non-neutral
  games (everything else equal).
- predict_lambdas: stronger attacker → higher lambda; stronger defender → lower
  opponent lambda.
"""
from __future__ import annotations

import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.config import ModelConfig
from wc_predictor.model.poisson_dc import (
    TeamStrength,
    fit_dc_model,
    predict_lambdas,
)


CFG = ModelConfig()


def _generate_synthetic(n_matches: int, seed: int = 42) -> tuple[list[dict], dict[str, dict[str, float]]]:
    """Generate Poisson-distributed match results with known team strengths."""
    rng = random.Random(seed)
    teams = {
        "A": {"attack": +0.50, "defense": +0.40},
        "B": {"attack": +0.20, "defense": +0.10},
        "C": {"attack": +0.00, "defense": +0.00},
        "D": {"attack": -0.20, "defense": -0.30},
        "E": {"attack": -0.50, "defense": -0.20},
    }
    # Sum-to-zero for cleaner recovery
    mean_att = sum(t["attack"] for t in teams.values()) / len(teams)
    mean_def = sum(t["defense"] for t in teams.values()) / len(teams)
    for t in teams.values():
        t["attack"] -= mean_att
        t["defense"] -= mean_def

    true_mu = 0.10
    true_gamma = 0.30
    names = list(teams)

    def _poisson(lam):
        # Knuth's algorithm
        import math
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= rng.random()
        return k - 1

    rows = []
    today = date(2026, 5, 1)
    for i in range(n_matches):
        h, a = rng.sample(names, 2)
        neutral = rng.random() < 0.5
        hf = 0.0 if neutral else 1.0
        import math
        lh = math.exp(true_mu + true_gamma * hf + teams[h]["attack"] - teams[a]["defense"])
        la = math.exp(true_mu + teams[a]["attack"] - teams[h]["defense"])
        rows.append({
            "date": today.isoformat(),
            "home": h, "away": a,
            "home_score": _poisson(lh), "away_score": _poisson(la),
            "neutral": neutral, "tournament": "Friendly",
        })
    return rows, teams


def test_synthetic_recovery_attack_ranking():
    """Fit on 5000 synthetic matches, attack-strength ranking must match truth."""
    rows, true_strengths = _generate_synthetic(5000, seed=42)
    fit = fit_dc_model(
        rows, CFG, as_of=date(2026, 5, 1),
        half_life_days=10_000,  # effectively no decay (all matches same date anyway)
        ridge_lambda=0.01,
        verbose=False,
        max_iter=2000,
    )
    true_order = sorted(true_strengths, key=lambda t: -true_strengths[t]["attack"])
    fit_order = sorted(fit.strengths, key=lambda t: -fit.strengths[t].attack)
    assert true_order == fit_order, f"attack ranking mismatch: true={true_order}, fit={fit_order}"


def test_synthetic_recovery_defense_ranking():
    rows, true_strengths = _generate_synthetic(5000, seed=7)
    fit = fit_dc_model(
        rows, CFG, as_of=date(2026, 5, 1),
        half_life_days=10_000, ridge_lambda=0.01, verbose=False, max_iter=2000,
    )
    true_order = sorted(true_strengths, key=lambda t: -true_strengths[t]["defense"])
    fit_order = sorted(fit.strengths, key=lambda t: -fit.strengths[t].defense)
    assert true_order == fit_order


def test_synthetic_recovery_gamma_positive():
    """Home advantage parameter should come out positive (around 0.3 by construction)."""
    rows, _ = _generate_synthetic(5000, seed=99)
    fit = fit_dc_model(
        rows, CFG, as_of=date(2026, 5, 1),
        half_life_days=10_000, ridge_lambda=0.01, verbose=False, max_iter=2000,
    )
    assert 0.15 < fit.gamma < 0.45, f"gamma out of expected range: {fit.gamma}"


def test_predict_lambdas_home_advantage_raises_lambda_home():
    a = TeamStrength("A", attack=0.3, defense=0.2, n_matches=10)
    b = TeamStrength("B", attack=0.1, defense=0.1, n_matches=10)
    lh_n, la_n = predict_lambdas(a, b, mu=0.2, gamma=0.3, host=None)
    lh_h, la_h = predict_lambdas(a, b, mu=0.2, gamma=0.3, host="home")
    # home advantage applies to home lambda only, not away
    assert lh_h > lh_n
    assert abs(la_h - la_n) < 1e-9


def test_predict_lambdas_away_host_boosts_away_lambda_only():
    """The asymmetric WC case: openfootball labels a host nation in the away column."""
    a = TeamStrength("A", attack=0.3, defense=0.2, n_matches=10)
    b = TeamStrength("B", attack=0.1, defense=0.1, n_matches=10)
    lh_n, la_n = predict_lambdas(a, b, mu=0.2, gamma=0.3, host=None)
    lh_aw, la_aw = predict_lambdas(a, b, mu=0.2, gamma=0.3, host="away")
    assert la_aw > la_n
    assert abs(lh_aw - lh_n) < 1e-9


def test_predict_lambdas_stronger_attacker_scores_more():
    weak = TeamStrength("W", attack=-0.5, defense=0.0, n_matches=10)
    strong = TeamStrength("S", attack=+0.5, defense=0.0, n_matches=10)
    opp = TeamStrength("O", attack=0.0, defense=0.0, n_matches=10)
    lh_weak, _ = predict_lambdas(weak, opp, mu=0.2, gamma=0.0, host=None)
    lh_strong, _ = predict_lambdas(strong, opp, mu=0.2, gamma=0.0, host=None)
    assert lh_strong > lh_weak


def test_predict_lambdas_stronger_defender_concedes_less():
    weak_def = TeamStrength("WD", attack=0.0, defense=-0.5, n_matches=10)
    strong_def = TeamStrength("SD", attack=0.0, defense=+0.5, n_matches=10)
    attacker = TeamStrength("A", attack=0.0, defense=0.0, n_matches=10)
    lh_vs_weak, _ = predict_lambdas(attacker, weak_def, mu=0.2, gamma=0.0, host=None)
    lh_vs_strong, _ = predict_lambdas(attacker, strong_def, mu=0.2, gamma=0.0, host=None)
    assert lh_vs_weak > lh_vs_strong
