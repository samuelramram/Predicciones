"""Goal rates implied by the market, and pulling the model's toward them.

The 1X2 blend only re-weights the outcome marginals; the score grid inside keeps
the model's goal environment. ``anchor_lambdas`` moves the Poisson rates toward
the ones whose Poisson·DC grid reproduces the market's home/away win and Over 2.5
probabilities, so the exact-score shape follows the market too. Shared by the
Europa bots and the Liga MX pipeline (Claudio + liga bots).
"""
from __future__ import annotations

import numpy as np


def _probs_np(lh: float, la: float, rho: float, n: int = 11) -> tuple[float, float, float, float]:
    """(p1, px, p2, p_over2.5) of a Poisson·DC grid, vectorized (fast inner loop)."""
    from math import exp, lgamma, log
    k = np.arange(n)
    lf = np.array([lgamma(i + 1) for i in range(n)])
    ph = np.exp(k * log(lh) - lh - lf)
    pa = np.exp(k * log(la) - la - lf)
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m /= m.sum()
    tot = k[:, None] + k[None, :]
    return (float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum()),
            float(m[tot > 2.5].sum()))


def implied_lambdas(p1: float, p2: float, p_over25: float, rho: float,
                    start: tuple[float, float] = (1.4, 1.1)) -> tuple[float, float]:
    """Goal rates whose Poisson·DC grid best reproduces the market's home/away
    win and Over 2.5 probabilities. 1X2 alone can't tell a 1-0 favourite from a
    4-1 one; the total pins the goal environment, so the handicap distribution
    of the market-following bots stays consistent with the market's AH line."""
    from scipy.optimize import minimize

    def loss(x):
        q1, _, q2, qo = _probs_np(exp(x[0]), exp(x[1]), rho)
        return (q1 - p1) ** 2 + (q2 - p2) ** 2 + (qo - p_over25) ** 2

    from math import exp, log
    r = minimize(loss, [log(start[0]), log(start[1])], method="Nelder-Mead",
                 options={"xatol": 1e-4, "fatol": 1e-9, "maxiter": 400})
    return exp(r.x[0]), exp(r.x[1])


def anchor_lambdas(lh: float, la: float, market_1x2: tuple[float, float, float],
                   market_over25: float | None, rho: float, w: float) -> tuple[float, float]:
    """Geometric blend of the model's rates with the market-implied ones, weight
    ``w`` on the market. Without a market total the model's own P(Over 2.5) is
    the target, so only the home/away split moves and the goal level stays."""
    target = market_over25 if market_over25 is not None else _probs_np(lh, la, rho)[3]
    mh, ma = implied_lambdas(market_1x2[0], market_1x2[2], target, rho, start=(lh, la))
    w = min(max(w, 0.0), 1.0)
    return lh ** (1 - w) * mh ** w, la ** (1 - w) * ma ** w
