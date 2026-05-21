"""Monte Carlo simulation of the 30-person quiniela pool.

Question this answers: given the model's measured per-match performance on real
tournaments, how often would it actually WIN a 30-person pool — and how often
finish top-3?

Method (uses real results, not the model's own probabilities — avoids circularity):
  1. Take a real tournament's matches with their ACTUAL scores.
  2. The model's points are known exactly (from the backtest).
  3. Simulate N_OPPONENTS synthetic human players. Each human:
       - has a skill level p_skill ~ Uniform(skill_lo, skill_hi);
       - per match, picks the Elo-favoured outcome with probability p_skill,
         else a random other outcome (humans are noisy);
       - picks an exact scoreline by sampling the empirical WC score distribution
         conditional on the chosen outcome.
     Each human's picks are scored against the SAME actual results.
  4. Rank the model among the humans. Repeat n_sims times.
  5. Report win rate, top-3 rate, mean rank, full rank histogram.

The human model is deliberately "decent but not expert": calibrated so the
average synthetic human scores close to the always_1_0 baseline (~0.68 pts/match).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from wc_predictor.config import QuinielaRules
from wc_predictor.scoring.quiniela import score_actual


# Empirical WC scoreline distribution, conditional on the chosen 1X2 outcome.
# Derived from historical WC score frequencies (1-0 most common, then 2-1, 2-0...).
HOME_WIN_SCORES = {"1-0": 0.40, "2-1": 0.28, "2-0": 0.22, "3-1": 0.06, "3-0": 0.04}
AWAY_WIN_SCORES = {"0-1": 0.40, "1-2": 0.28, "0-2": 0.22, "1-3": 0.06, "0-3": 0.04}
DRAW_SCORES = {"1-1": 0.45, "0-0": 0.35, "2-2": 0.20}


@dataclass
class PoolSimResult:
    tournament: str
    n_opponents: int
    n_sims: int
    model_points: int
    win_rate: float          # P(model finishes strictly 1st; ties split)
    top3_rate: float
    mean_rank: float
    median_rank: float
    rank_histogram: dict[int, int]
    avg_human_points: float
    best_human_mean: float   # mean points of the best human per sim


def _sample_score(rng: random.Random, outcome: str) -> str:
    table = {"1": HOME_WIN_SCORES, "X": DRAW_SCORES, "2": AWAY_WIN_SCORES}[outcome]
    r = rng.random()
    cum = 0.0
    for score, p in table.items():
        cum += p
        if r <= cum:
            return score
    return list(table)[-1]


def _human_pick(
    rng: random.Random,
    elo_probs: tuple[float, float, float],
    skill: float,
    draw_propensity: float,
) -> tuple[str, str]:
    """A synthetic human's (1X2, exact) pick for one match.

    Real pool players pick a WINNER most of the time and only occasionally a draw
    (modelling the 'I think it ends even' instinct). They favour the stronger team
    but with noise.

    elo_probs: (P_home, P_draw, P_away) — the human's perception of strength.
    skill: given they pick a winner, the probability it is the stronger side.
    draw_propensity: probability this player picks X regardless.
    """
    p1, _, p2 = elo_probs
    favourite = "1" if p1 >= p2 else "2"
    underdog = "2" if favourite == "1" else "1"

    r = rng.random()
    if r < draw_propensity:
        outcome = "X"
    elif r < draw_propensity + skill * (1.0 - draw_propensity):
        outcome = favourite
    else:
        outcome = underdog
    return outcome, _sample_score(rng, outcome)


def simulate_pool(
    matches: list[dict],
    model_points: int,
    rules: QuinielaRules,
    n_opponents: int = 29,
    n_sims: int = 20_000,
    skill_lo: float = 0.78,
    skill_hi: float = 1.0,
    draw_prop_lo: float = 0.04,
    draw_prop_hi: float = 0.15,
    seed: int = 20260611,
) -> PoolSimResult:
    """Run the Monte Carlo pool simulation.

    matches: list of dicts each with keys: actual_h, actual_a, elo_p1, elo_px, elo_p2.
    model_points: the model's known total points for this tournament.

    Human calibration: skill in [0.72, 1.0] and draw-propensity in [0.05, 0.18] are
    tuned so the synthetic field averages ~0.60-0.64 pts/match and the strongest
    players approach the always_1_0 baseline (~0.68) — i.e. a believable mix of
    casual and sharp pool players.
    """
    rng = random.Random(seed)
    n_players = n_opponents + 1

    rank_hist: dict[int, int] = {r: 0 for r in range(1, n_players + 1)}
    wins = 0.0
    top3 = 0
    rank_sum = 0.0
    ranks_sorted: list[float] = []
    human_points_total = 0
    best_human_total = 0

    for _ in range(n_sims):
        human_scores = []
        for _ in range(n_opponents):
            skill = rng.uniform(skill_lo, skill_hi)
            draw_prop = rng.uniform(draw_prop_lo, draw_prop_hi)
            total = 0
            for m in matches:
                outcome, exact = _human_pick(
                    rng, (m["elo_p1"], m["elo_px"], m["elo_p2"]), skill, draw_prop
                )
                total += score_actual(m["actual_h"], m["actual_a"], outcome, exact, rules)
            human_scores.append(total)

        human_points_total += sum(human_scores)
        best_human_total += max(human_scores)

        # Rank of the model: 1 + (number of humans strictly above it).
        strictly_above = sum(1 for s in human_scores if s > model_points)
        tied = sum(1 for s in human_scores if s == model_points)
        # Tie-break: expected rank within the tie group (average placement).
        rank = strictly_above + 1 + tied / 2.0
        int_rank = strictly_above + 1

        rank_hist[int_rank] = rank_hist.get(int_rank, 0) + 1
        rank_sum += rank
        ranks_sorted.append(rank)
        if strictly_above == 0:
            wins += 1.0 / (tied + 1)  # split the win across the tie group
        if rank <= 3:
            top3 += 1

    ranks_sorted.sort()
    median_rank = ranks_sorted[len(ranks_sorted) // 2]

    return PoolSimResult(
        tournament="",
        n_opponents=n_opponents,
        n_sims=n_sims,
        model_points=model_points,
        win_rate=wins / n_sims,
        top3_rate=top3 / n_sims,
        mean_rank=rank_sum / n_sims,
        median_rank=median_rank,
        rank_histogram=rank_hist,
        avg_human_points=human_points_total / (n_sims * n_opponents),
        best_human_mean=best_human_total / n_sims,
    )
