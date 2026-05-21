"""Karlis-Ntzoufras (2003) bivariate Poisson for joint home/away score distribution.

Model
-----
Decompose home/away goals as:
    H = X1 + X3
    A = X2 + X3
where X1, X2, X3 ~ independent Poisson with rates lambda_1, lambda_2, lambda_3.
The shared X3 induces Cov(H, A) = lambda_3 >= 0 — positive correlation between
team scoring, which is exactly what the WC backtest revealed independent Poisson
was missing (the 2-0 over-prediction vs 2-1 under-prediction).

Reparametrization for fitting:
    log(lambda_1) = mu + gamma * host_home_flag + attack[h] - defense[a]
    log(lambda_2) = mu + gamma * host_away_flag + attack[a] - defense[h]
    log(lambda_3) = delta  (single global parameter; could be made hierarchical later)

Joint PMF (Karlis & Ntzoufras 2003):
    P(H=h, A=a) = exp(-(l1+l2+l3)) * l1^h * l2^a / (h! a!)
               * sum_{k=0}^{min(h,a)} C(h,k) C(a,k) k! (l3 / (l1 l2))^k

The inner sum is finite (bounded by min(h, a) <= max_goals).

Fitting is by weighted MLE with L2 ridge on attack/defense (same regularization
strategy as the independent Poisson + DC fit). Optimization uses scipy L-BFGS-B
over ~503 params (one extra log_lambda_3 compared to the independent model).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from wc_predictor.config import ModelConfig
from wc_predictor.model.poisson_dc import _build_design


_LOG_FACT = np.array([math.lgamma(i + 1) for i in range(60)])  # safe up to score 59


@dataclass
class BPTeamStrength:
    team: str
    attack: float
    defense: float
    n_matches: int


@dataclass
class BPFitResult:
    mu: float
    gamma: float
    lambda3: float
    strengths: dict[str, BPTeamStrength]
    n_matches: int
    n_teams: int
    half_life_days: int
    ridge_lambda: float
    converged: bool
    final_neg_log_lik: float

    def to_dict(self) -> dict:
        return {
            "model": "bivariate_poisson_karlis_ntzoufras",
            "mu": self.mu,
            "gamma": self.gamma,
            "lambda3": self.lambda3,
            "n_matches": self.n_matches,
            "n_teams": self.n_teams,
            "half_life_days": self.half_life_days,
            "ridge_lambda": self.ridge_lambda,
            "converged": self.converged,
            "final_neg_log_lik": self.final_neg_log_lik,
            "teams": {
                t: {"attack": round(s.attack, 4), "defense": round(s.defense, 4), "n_matches": s.n_matches}
                for t, s in sorted(self.strengths.items())
            },
        }


def bp_log_pmf(h: int, a: int, l1: float, l2: float, l3: float) -> float:
    """Log-PMF of bivariate Poisson at score (h, a). Used in tests/diagnostics; the
    fit and score-matrix builders use vectorized variants below."""
    if l3 < 1e-12:
        return (-l1 - l2 + h * math.log(l1) - _LOG_FACT[h]
                + a * math.log(l2) - _LOG_FACT[a])
    log_prefix = -(l1 + l2 + l3) + h * math.log(l1) + a * math.log(l2)
    log_prefix -= _LOG_FACT[h] + _LOG_FACT[a]
    log_ratio = math.log(l3) - math.log(l1) - math.log(l2)
    terms = []
    for k in range(min(h, a) + 1):
        t = (_LOG_FACT[h] - _LOG_FACT[k] - _LOG_FACT[h - k]
             + _LOG_FACT[a] - _LOG_FACT[k] - _LOG_FACT[a - k]
             + _LOG_FACT[k]
             + k * log_ratio)
        terms.append(t)
    m = max(terms)
    inner = m + math.log(sum(math.exp(t - m) for t in terms))
    return log_prefix + inner


def _bp_neg_log_lik(theta: np.ndarray, design: dict, ridge_lambda: float, max_inner_k: int = 10) -> float:
    """Vectorized weighted negative log-likelihood + ridge penalty.

    theta layout: [mu, gamma, log_lambda3, attack_1..attack_T, defense_1..defense_T]
    """
    n_teams = len(design["teams"])
    mu = theta[0]
    gamma = theta[1]
    log_l3 = theta[2]
    attack = theta[3 : 3 + n_teams]
    defense = theta[3 + n_teams : 3 + 2 * n_teams]

    l3 = float(np.exp(log_l3))

    home_idx = design["home_idx"]
    away_idx = design["away_idx"]
    h = design["home_goals"].astype(int)
    a = design["away_goals"].astype(int)
    hf = design["home_flag"]
    w = design["weights"]

    log_l1 = mu + gamma * hf + attack[home_idx] - defense[away_idx]
    log_l2 = mu + attack[away_idx] - defense[home_idx]
    l1 = np.exp(log_l1)
    l2 = np.exp(log_l2)

    base = -(l1 + l2 + l3) + h * log_l1 + a * log_l2 - _LOG_FACT[h] - _LOG_FACT[a]

    # Inner-sum via logsumexp across k = 0..max_inner_k, masking invalid k.
    log_ratio = log_l3 - log_l1 - log_l2  # shape (n,)
    n = len(h)
    log_terms = np.full((max_inner_k + 1, n), -np.inf)
    for k in range(max_inner_k + 1):
        valid = (h >= k) & (a >= k)
        if not valid.any():
            continue
        log_terms[k, valid] = (
            _LOG_FACT[h[valid]] - _LOG_FACT[k] - _LOG_FACT[h[valid] - k]
            + _LOG_FACT[a[valid]] - _LOG_FACT[k] - _LOG_FACT[a[valid] - k]
            + _LOG_FACT[k]
            + k * log_ratio[valid]
        )
    max_term = log_terms.max(axis=0)
    inner_log = max_term + np.log(np.sum(np.exp(log_terms - max_term[None, :]), axis=0))

    log_pmf = base + inner_log
    weighted_ll = float(np.sum(w * log_pmf))

    penalty = ridge_lambda * float(np.sum(attack ** 2) + np.sum(defense ** 2))
    return -(weighted_ll - penalty)


def fit_bivariate_poisson(
    rows: list[dict],
    cfg: ModelConfig,
    as_of: date | None = None,
    half_life_days: int = 730,
    ridge_lambda: float = 1.0,
    max_iter: int = 1500,
    initial_log_lambda3: float = math.log(0.1),
    verbose: bool = True,
) -> BPFitResult:
    """Fit bivariate Poisson MLE on weighted match history."""
    from scipy.optimize import minimize

    as_of = as_of or datetime.utcnow().date()
    design = _build_design(rows, as_of, half_life_days)
    n_teams = len(design["teams"])
    if verbose:
        print(f"  bivariate fit: {len(rows)} matches, {n_teams} teams, "
              f"half-life {half_life_days}d, ridge={ridge_lambda}, init log_l3={initial_log_lambda3:.2f}")

    # Bound max inner k for fit by max observed score in training data
    max_score_seen = int(max(design["home_goals"].max(), design["away_goals"].max()))
    max_inner_k = min(max_score_seen, 10)

    theta0 = np.zeros(3 + 2 * n_teams)
    theta0[0] = math.log(1.4)         # mu
    theta0[1] = 0.30                  # gamma
    theta0[2] = initial_log_lambda3   # log_lambda3

    result = minimize(
        _bp_neg_log_lik,
        theta0,
        args=(design, ridge_lambda, max_inner_k),
        method="L-BFGS-B",
        options={"maxiter": max_iter, "gtol": 1e-6},
    )
    if verbose:
        print(f"  optimizer: success={result.success}, iter={result.nit}, nll={result.fun:.2f}")

    mu = float(result.x[0])
    gamma = float(result.x[1])
    log_l3 = float(result.x[2])
    attack = result.x[3 : 3 + n_teams]
    defense = result.x[3 + n_teams : 3 + 2 * n_teams]

    # Sum-to-zero centering (same as Poisson+DC for interpretability)
    mean_att = float(np.mean(attack))
    attack = attack - mean_att
    mu = mu + mean_att
    mean_def = float(np.mean(defense))
    defense = defense - mean_def
    mu = mu - mean_def

    strengths = {
        t: BPTeamStrength(
            team=t, attack=float(attack[i]), defense=float(defense[i]),
            n_matches=int(design["match_count"][i]),
        )
        for i, t in enumerate(design["teams"])
    }

    return BPFitResult(
        mu=mu, gamma=gamma, lambda3=float(math.exp(log_l3)),
        strengths=strengths,
        n_matches=len(rows), n_teams=n_teams,
        half_life_days=half_life_days, ridge_lambda=ridge_lambda,
        converged=bool(result.success), final_neg_log_lik=float(result.fun),
    )


def predict_bivariate_lambdas(
    home: BPTeamStrength,
    away: BPTeamStrength,
    mu: float,
    gamma: float,
    host: str | None = None,
) -> tuple[float, float]:
    """Returns (lambda_1, lambda_2). lambda_3 is a global constant returned separately
    by the fit. The caller combines them into the score matrix builder."""
    home_boost = gamma if host == "home" else 0.0
    away_boost = gamma if host == "away" else 0.0
    l1 = float(np.exp(mu + home_boost + home.attack - away.defense))
    l2 = float(np.exp(mu + away_boost + away.attack - home.defense))
    return l1, l2


def bp_score_matrix(l1: float, l2: float, l3: float, max_goals: int = 8) -> dict:
    """Build a normalized score-probability table for the EV optimizer.

    Returns a dict with the same shape `scoring.quiniela.build_score_matrix` returns,
    so the existing `optimize_pick_from_cells` can consume it.
    """
    cells = []
    raw_p1 = raw_px = raw_p2 = 0.0
    total = 0.0

    if l3 < 1e-12:
        # Independent Poisson fast path
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                p = math.exp(-l1) * l1 ** h / math.factorial(h)
                p *= math.exp(-l2) * l2 ** a / math.factorial(a)
                outcome = "X" if h == a else ("1" if h > a else "2")
                cells.append({"h": h, "a": a, "score": f"{h}-{a}", "prob_raw": p, "outcome": outcome})
                total += p
                if outcome == "1":
                    raw_p1 += p
                elif outcome == "X":
                    raw_px += p
                else:
                    raw_p2 += p
    else:
        log_ratio = math.log(l3) - math.log(l1) - math.log(l2)
        log_prefix_const = -(l1 + l2 + l3)
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                log_prefix = log_prefix_const + h * math.log(l1) + a * math.log(l2)
                log_prefix -= _LOG_FACT[h] + _LOG_FACT[a]
                terms = []
                for k in range(min(h, a) + 1):
                    t = (_LOG_FACT[h] - _LOG_FACT[k] - _LOG_FACT[h - k]
                         + _LOG_FACT[a] - _LOG_FACT[k] - _LOG_FACT[a - k]
                         + _LOG_FACT[k]
                         + k * log_ratio)
                    terms.append(t)
                m = max(terms)
                inner = m + math.log(sum(math.exp(t - m) for t in terms))
                p = math.exp(log_prefix + inner)
                outcome = "X" if h == a else ("1" if h > a else "2")
                cells.append({"h": h, "a": a, "score": f"{h}-{a}", "prob_raw": p, "outcome": outcome})
                total += p
                if outcome == "1":
                    raw_p1 += p
                elif outcome == "X":
                    raw_px += p
                else:
                    raw_p2 += p

    for c in cells:
        c["prob"] = c["prob_raw"] / total
    return {
        "cells": cells,
        "p_1": raw_p1 / total,
        "p_x": raw_px / total,
        "p_2": raw_p2 / total,
        "captured_mass": total,
        "max_goals": max_goals,
    }
