"""Blend multiple probability sources into a single (P_1, P_X, P_2, lambdas) estimate.

Sources:
- Poisson + Dixon-Coles → marginal 1X2 + full score distribution
- Elo → 1X2 only (no scoreline; convert to lambdas via league-avg goals)
- Closing odds → 1X2 only (de-overrounded)

Strategy:
1. Convert each source to a 1X2 probability triplet.
2. Weighted geometric mean (log-pool) — better calibrated than arithmetic.
3. For scorelines, anchor to the Poisson cell distribution but re-scale outcome groups
   to match the blended 1X2 marginals.

The weights live in ModelConfig.blend_*. If odds are missing, redistribute the odds
weight proportionally to Elo and Poisson.
"""
from __future__ import annotations

import math

from wc_predictor.config import ModelConfig


def log_pool(triplets: list[tuple[float, float, float]], weights: list[float]) -> tuple[float, float, float]:
    """Weighted geometric mean of probability triplets, renormalized."""
    assert len(triplets) == len(weights) and weights, "mismatched inputs"
    total_w = sum(weights)
    norm_w = [w / total_w for w in weights]
    out = [0.0, 0.0, 0.0]
    for (p1, px, p2), w in zip(triplets, norm_w):
        out[0] += w * math.log(max(p1, 1e-9))
        out[1] += w * math.log(max(px, 1e-9))
        out[2] += w * math.log(max(p2, 1e-9))
    raw = [math.exp(v) for v in out]
    s = sum(raw)
    return (raw[0] / s, raw[1] / s, raw[2] / s)
