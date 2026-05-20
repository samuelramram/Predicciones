"""Tests for the Karlis-Ntzoufras bivariate Poisson model."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.model.bivariate_poisson import bp_log_pmf, bp_score_matrix


def test_bp_reduces_to_independent_poisson_when_lambda3_zero():
    """With lambda_3 = 0 the joint should equal Pois(l1) * Pois(l2) pointwise."""
    l1, l2 = 1.5, 1.0
    for h in range(5):
        for a in range(5):
            bp = math.exp(bp_log_pmf(h, a, l1, l2, 0.0))
            indep = (math.exp(-l1) * l1**h / math.factorial(h)) * (math.exp(-l2) * l2**a / math.factorial(a))
            assert abs(bp - indep) < 1e-10, f"mismatch at ({h},{a}): bp={bp}, indep={indep}"


def test_bp_marginals_match_pois_lambda1_plus_lambda3():
    """H ~ Pois(lambda_1 + lambda_3) marginally."""
    l1, l2, l3 = 1.2, 0.8, 0.4
    for h in range(7):
        observed = sum(math.exp(bp_log_pmf(h, a, l1, l2, l3)) for a in range(20))
        expected = math.exp(-(l1 + l3)) * (l1 + l3)**h / math.factorial(h)
        assert abs(observed - expected) < 1e-4, f"marginal mismatch at h={h}: obs={observed}, exp={expected}"


def test_bp_positive_correlation_increases_diagonal_mass_with_marginals_fixed():
    """Holding the MARGINAL goal rates constant (λ_1 + λ_3, λ_2 + λ_3), positive
    correlation pushes mass onto h ≈ a cells and away from h >> a / h << a cells."""
    # Both setups have marginal Pois(1.5) for home and away.
    matrix_indep = bp_score_matrix(1.5, 1.5, 0.0, max_goals=6)
    matrix_corr = bp_score_matrix(1.0, 1.0, 0.5, max_goals=6)
    p11_indep = next(c["prob"] for c in matrix_indep["cells"] if c["score"] == "1-1")
    p11_corr = next(c["prob"] for c in matrix_corr["cells"] if c["score"] == "1-1")
    p02_indep = next(c["prob"] for c in matrix_indep["cells"] if c["score"] == "0-2")
    p02_corr = next(c["prob"] for c in matrix_corr["cells"] if c["score"] == "0-2")
    assert p11_corr > p11_indep, f"1-1 should INCREASE with corr: {p11_indep} → {p11_corr}"
    assert p02_corr < p02_indep, f"0-2 should DECREASE with corr: {p02_indep} → {p02_corr}"


def test_bp_score_matrix_normalizes():
    matrix = bp_score_matrix(1.4, 1.2, 0.3, max_goals=8)
    total = sum(c["prob"] for c in matrix["cells"])
    assert abs(total - 1.0) < 1e-9
    assert abs(matrix["p_1"] + matrix["p_x"] + matrix["p_2"] - 1.0) < 1e-9
