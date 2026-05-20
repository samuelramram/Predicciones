"""EV optimizer for the World Cup quiniela.

Adapted from the Liga MX `quiniela.py` (Dixon-Coles bivariate Poisson + EV-greedy
score picker), generalized so the scoring rule lives in `QuinielaRules` instead of
being hardcoded.

Key idea: instead of picking the modal exact score, pick the `(1X2, exact)` pair that
maximizes:

    EV(pick) = points_exact * P(exact) + points_1x2 * P(1X2 outcome)   if exclusive

The exclusive flag matters: when the pool awards 2 pts for exact OR 1 pt for 1X2 (not
both), an exact-score hit forfeits the 1X2 point. When non-exclusive, an exact-score
hit also banks the 1X2 point. Both branches are handled.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial

from wc_predictor.config import ModelConfig, QuinielaRules


def poisson_prob(lambda_val: float, k: int) -> float:
    return (lambda_val**k * exp(-lambda_val)) / factorial(k)


def dc_correction(h: int, a: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles low-score correction. rho<0 inflates draws and dampens 1-0 / 0-1."""
    if h == 0 and a == 0:
        return 1.0 - lh * la * rho
    if h == 1 and a == 0:
        return 1.0 + la * rho
    if h == 0 and a == 1:
        return 1.0 + lh * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def _captured_mass(lh: float, la: float, max_goals: int) -> float:
    mh = sum(poisson_prob(lh, k) for k in range(max_goals + 1))
    ma = sum(poisson_prob(la, k) for k in range(max_goals + 1))
    return mh * ma


def choose_grid_limit(lh: float, la: float, mcfg: ModelConfig) -> int:
    """Adaptive grid: smallest N such that P(h<=N) * P(a<=N) >= target_mass."""
    for g in range(mcfg.poisson_grid_min_goals, mcfg.poisson_grid_max_cap + 1):
        if _captured_mass(lh, la, g) >= mcfg.poisson_grid_target_mass:
            return g
    return mcfg.poisson_grid_max_cap


@dataclass
class PickResult:
    pick_1x2: str
    pick_exact: str
    ev: float
    ev_confidence_gap: float
    abstain: bool
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    prob_exact: float
    top_5_by_prob: list[dict]
    grid_max_goals: int
    captured_mass: float


def build_score_matrix(
    lambda_home: float, lambda_away: float, mcfg: ModelConfig
) -> tuple[list[dict], float, float, float, float, int]:
    """Compute the (max_goals+1)^2 score probability table with DC correction.

    Returns the per-score list (normalized), marginal outcomes, and grid metadata.
    """
    max_goals = choose_grid_limit(lambda_home, lambda_away, mcfg)

    cells: list[dict] = []
    raw_p1 = raw_px = raw_p2 = 0.0
    sum_raw = 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_prob(lambda_home, h) * poisson_prob(lambda_away, a)
            p *= dc_correction(h, a, lambda_home, lambda_away, mcfg.dc_rho)
            outcome = "X" if h == a else ("1" if h > a else "2")
            cells.append({"h": h, "a": a, "score": f"{h}-{a}", "prob_raw": p, "outcome": outcome})
            sum_raw += p
            if outcome == "1":
                raw_p1 += p
            elif outcome == "X":
                raw_px += p
            else:
                raw_p2 += p

    if sum_raw <= 0:
        raise ValueError(f"Degenerate lambda pair: lh={lambda_home}, la={lambda_away}")

    for cell in cells:
        cell["prob"] = cell["prob_raw"] / sum_raw

    return cells, raw_p1 / sum_raw, raw_px / sum_raw, raw_p2 / sum_raw, sum_raw, max_goals


def optimize_pick(
    lambda_home: float,
    lambda_away: float,
    rules: QuinielaRules,
    mcfg: ModelConfig,
) -> PickResult:
    """Choose (1X2, exact) pair maximizing EV under the pool's scoring rules."""
    cells, p1, px, p2, captured, max_goals = build_score_matrix(lambda_home, lambda_away, mcfg)

    best_by_outcome: dict[str, dict] = {}
    for cell in cells:
        cur = best_by_outcome.get(cell["outcome"])
        if cur is None or cell["prob"] > cur["prob"]:
            best_by_outcome[cell["outcome"]] = cell

    outcome_marginals = {"1": p1, "X": px, "2": p2}

    candidates = []
    for outcome, cell in best_by_outcome.items():
        p_exact = cell["prob"]
        p_outcome = outcome_marginals[outcome]
        if rules.exclusive:
            ev = rules.points_exact * p_exact + rules.points_1x2 * (p_outcome - p_exact)
        else:
            ev = rules.points_exact * p_exact + rules.points_1x2 * p_outcome
        candidates.append((ev, outcome, cell))

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_ev, best_outcome, best_cell = candidates[0]
    gap = best_ev - candidates[1][0] if len(candidates) > 1 else best_ev

    top5 = sorted(cells, key=lambda c: c["prob"], reverse=True)[:5]

    return PickResult(
        pick_1x2=best_outcome,
        pick_exact=best_cell["score"],
        ev=best_ev,
        ev_confidence_gap=gap,
        abstain=gap < mcfg.ev_abstain_gap,
        prob_home_win=p1,
        prob_draw=px,
        prob_away_win=p2,
        prob_exact=best_cell["prob"],
        top_5_by_prob=top5,
        grid_max_goals=max_goals,
        captured_mass=captured,
    )


def expected_points(
    lambda_home: float,
    lambda_away: float,
    pick_1x2: str,
    pick_exact: str,
    rules: QuinielaRules,
    mcfg: ModelConfig,
) -> float:
    """EV of an arbitrary pick (not necessarily the optimum). Used for backtesting
    alternative strategies (modal, contrarian, manual override)."""
    cells, p1, px, p2, _, _ = build_score_matrix(lambda_home, lambda_away, mcfg)
    p_outcome = {"1": p1, "X": px, "2": p2}[pick_1x2]
    p_exact = next((c["prob"] for c in cells if c["score"] == pick_exact and c["outcome"] == pick_1x2), 0.0)
    if rules.exclusive:
        return rules.points_exact * p_exact + rules.points_1x2 * (p_outcome - p_exact)
    return rules.points_exact * p_exact + rules.points_1x2 * p_outcome


def score_actual(
    actual_home: int,
    actual_away: int,
    pick_1x2: str,
    pick_exact: str,
    rules: QuinielaRules,
) -> int:
    """Award points for one match given the true (90-minute) score and the pick.

    Pool-of-truth function. Backtests should call this, never reimplement the rule.
    """
    actual_outcome = "X" if actual_home == actual_away else ("1" if actual_home > actual_away else "2")
    actual_score = f"{actual_home}-{actual_away}"

    exact_hit = pick_1x2 == actual_outcome and pick_exact == actual_score
    outcome_hit = pick_1x2 == actual_outcome

    if exact_hit:
        return rules.points_exact + (0 if rules.exclusive else rules.points_1x2)
    if outcome_hit:
        return rules.points_1x2
    return 0
