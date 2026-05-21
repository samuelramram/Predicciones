"""Calibration metrics for 1X2 probability predictions.

Three complementary metrics:

1. **Brier score** — multi-class quadratic loss. Sum of (p_predicted - p_one_hot_actual)².
   Lower is better. Random uniform prediction on 3 classes scores 0.667; perfect
   knowledge scores 0.0. Strictly proper: minimized by truthful probabilities.

2. **Log-loss** — -log(p_predicted_for_actual_outcome). Lower is better. Penalizes
   overconfidence harder than Brier. Random uniform on 3 classes: log(3) ≈ 1.099.

3. **Reliability table** — bin predictions by predicted probability for a given
   outcome (say P_home_win), then report (mean predicted prob, observed frequency,
   count) per bin. A well-calibrated model: bin avg == observed freq across all bins.

For a binary outcome version: pass arrays of (p_home_win, actual_is_home_win) and
get the home-side reliability. Same for draw and away.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def brier_score(predictions: list[tuple[float, float, float]], actuals: list[str]) -> float:
    """Multi-class Brier score on 1X2.

    predictions: list of (P_home, P_draw, P_away) — must sum to ~1 each.
    actuals: list of "1", "X", or "2".
    Returns the mean Brier (in [0, 2]; lower is better; random uniform ≈ 0.667).
    """
    if not predictions or len(predictions) != len(actuals):
        raise ValueError("predictions and actuals must match in length")
    onehot = {"1": (1.0, 0.0, 0.0), "X": (0.0, 1.0, 0.0), "2": (0.0, 0.0, 1.0)}
    total = 0.0
    for (p1, px, p2), actual in zip(predictions, actuals):
        o1, ox, o2 = onehot[actual]
        total += (p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2
    return total / len(predictions)


def log_loss(predictions: list[tuple[float, float, float]], actuals: list[str], eps: float = 1e-12) -> float:
    """Cross-entropy on the actual outcome. Lower is better. Random uniform ≈ 1.099."""
    total = 0.0
    idx = {"1": 0, "X": 1, "2": 2}
    for probs, actual in zip(predictions, actuals):
        p = max(probs[idx[actual]], eps)
        total -= math.log(p)
    return total / len(predictions)


@dataclass
class ReliabilityBin:
    bin_low: float
    bin_high: float
    n: int
    mean_predicted: float
    observed_freq: float


def reliability_table(
    predicted_probs: list[float],
    binary_actuals: list[int],
    n_bins: int = 10,
) -> list[ReliabilityBin]:
    """For a single binary outcome (e.g., "did home actually win?"), bin by predicted
    probability and return per-bin observed frequency.

    A well-calibrated model has mean_predicted ≈ observed_freq in every bin.
    """
    if not predicted_probs or len(predicted_probs) != len(binary_actuals):
        raise ValueError("predicted_probs and binary_actuals must match in length")

    edges = [i / n_bins for i in range(n_bins + 1)]
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, a in zip(predicted_probs, binary_actuals):
        b = min(int(p * n_bins), n_bins - 1)
        bins[b].append((p, a))

    out: list[ReliabilityBin] = []
    for b, entries in enumerate(bins):
        if not entries:
            out.append(ReliabilityBin(edges[b], edges[b + 1], 0, 0.0, 0.0))
            continue
        n = len(entries)
        mean_p = sum(p for p, _ in entries) / n
        obs = sum(a for _, a in entries) / n
        out.append(ReliabilityBin(edges[b], edges[b + 1], n, mean_p, obs))
    return out


def actual_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "1"
    if home_score < away_score:
        return "2"
    return "X"
