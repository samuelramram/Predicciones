"""Blend multiple probability sources into a single score-matrix estimate.

Sources currently supported:
- Poisson + Dixon-Coles → full score distribution + marginal 1X2
- Bivariate Poisson (Karlis-Ntzoufras) → full score distribution + marginal 1X2
- Elo → 1X2 only

Strategy:
1. Get each source's 1X2 triplet.
2. Weighted geometric mean (log-pool) — better calibrated than arithmetic
   for combining classifier-style outputs (Bordley 1982, Genest & Zidek 1986).
3. For exact scorelines, anchor to the Poisson cell distribution but re-scale
   each outcome group so the blended marginals are respected. This preserves
   the per-outcome score shape (1-0 vs 2-0 vs 2-1) while letting Elo / odds
   re-balance the outcome probabilities.

If a source is missing (e.g., no odds available), the caller should redistribute
its weight to the remaining sources before calling `log_pool`.
"""
from __future__ import annotations

import math


def log_pool(triplets: list[tuple[float, float, float]], weights: list[float]) -> tuple[float, float, float]:
    """Weighted geometric mean of (P_home, P_draw, P_away) triplets, renormalized."""
    assert len(triplets) == len(weights) and weights, "mismatched inputs"
    total_w = sum(weights)
    if total_w <= 0:
        raise ValueError("Sum of weights must be positive")
    norm_w = [w / total_w for w in weights]
    out = [0.0, 0.0, 0.0]
    for (p1, px, p2), w in zip(triplets, norm_w):
        out[0] += w * math.log(max(p1, 1e-9))
        out[1] += w * math.log(max(px, 1e-9))
        out[2] += w * math.log(max(p2, 1e-9))
    raw = [math.exp(v) for v in out]
    s = sum(raw)
    return raw[0] / s, raw[1] / s, raw[2] / s


def rescale_cells_to_marginals(
    cells: list[dict],
    target_p1: float,
    target_px: float,
    target_p2: float,
) -> list[dict]:
    """Re-scale a score-matrix so its outcome marginals match (target_p1, target_px, target_p2).

    Each cell keeps its CONDITIONAL probability within its outcome group; only the
    group-level mass shifts. The conditional shape (1-0 vs 2-0 vs 2-1 within home
    wins) comes from the Poisson/DC model; the marginal balance comes from the
    blend with Elo / odds / etc.

    Returns NEW cell dicts (does not mutate inputs).
    """
    cur_p1 = sum(c["prob"] for c in cells if c["outcome"] == "1")
    cur_px = sum(c["prob"] for c in cells if c["outcome"] == "X")
    cur_p2 = sum(c["prob"] for c in cells if c["outcome"] == "2")

    scales = {
        "1": target_p1 / max(cur_p1, 1e-12),
        "X": target_px / max(cur_px, 1e-12),
        "2": target_p2 / max(cur_p2, 1e-12),
    }
    rescaled = [{**c, "prob": c["prob"] * scales[c["outcome"]]} for c in cells]

    total = sum(c["prob"] for c in rescaled)
    for c in rescaled:
        c["prob"] /= total
    return rescaled


def blend_poisson_with_elo(
    poisson_cells: list[dict],
    poisson_p1: float,
    poisson_px: float,
    poisson_p2: float,
    elo_p1: float,
    elo_px: float,
    elo_p2: float,
    w_poisson: float,
    w_elo: float,
) -> tuple[list[dict], float, float, float]:
    """Blend Poisson + Elo via log-pool and re-shape the score matrix."""
    p1, px, p2 = log_pool(
        [(poisson_p1, poisson_px, poisson_p2), (elo_p1, elo_px, elo_p2)],
        [w_poisson, w_elo],
    )
    cells = rescale_cells_to_marginals(poisson_cells, p1, px, p2)
    return cells, p1, px, p2
