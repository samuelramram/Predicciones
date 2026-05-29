"""Pool-aware ticket optimizer — maximize P(finishing 1st), not individual EV.

This closes the loop the diagnostic `pool_sim` left open. In a 30-person,
winner-takes-most pool the objective is NOT to maximize your own expected points
(that just tracks the favourite and ties you with everyone else who did the same)
— it is to maximize the probability of finishing FIRST. Those are different
objectives: the EV-optimal ticket is low-variance, and low variance is exactly
what you do NOT want when you only get paid for rank 1.

Method (per round / jornada):
  1. For every match we already have a blended score-matrix and two candidate
     picks from the EV optimizer: the EV-optimal pick and the contrarian pick
     (max ev / p_outcome — the under-picked, high-leverage outcome).
  2. Monte-Carlo the round with COMMON RANDOM NUMBERS:
       - sample each match's "true" scoreline from its own blended cell
         distribution (the model's best estimate of reality);
       - simulate `n_opponents` synthetic humans (same field model as pool_sim)
         and record the field's top score per simulation.
  3. Start from the all-EV ticket and greedily swap individual matches to their
     contrarian pick whenever the swap raises the simulated P(rank=1). Because the
     ticket score is a sum of independent per-match contributions, each candidate
     swap is evaluated in O(n_sims) against pre-tabulated per-match point streams.

The result is a ticket that deliberately trades a little expected-points for the
differentiation that actually wins a pool. Exposed via
`generate_picks --objective pool`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from wc_predictor.config import QuinielaRules
from wc_predictor.model.pool_sim import _human_pick
from wc_predictor.scoring.quiniela import score_actual


@dataclass
class TicketMatch:
    """One match's inputs to the pool optimizer."""
    match_id: int
    cells: list[dict]                       # blended score matrix (prob per scoreline)
    elo_probs: tuple[float, float, float]   # (p1, px, p2) for the human field model
    ev_pick: tuple[str, str]                # (1x2, exact)
    contra_pick: tuple[str, str]            # (1x2, exact)


@dataclass
class TicketResult:
    chosen: dict[int, tuple[str, str]]      # match_id -> (1x2, exact) selected
    swapped_to_contrarian: list[int]        # match_ids swapped off the EV pick
    win_prob_ev: float                      # P(rank=1) of the all-EV ticket
    win_prob_pool: float                    # P(rank=1) of the optimized ticket
    n_sims: int
    n_opponents: int


def _sample_scoreline(rng: random.Random, cells: list[dict]) -> tuple[int, int]:
    """Sample a (home, away) scoreline from a blended score matrix."""
    r = rng.random()
    cum = 0.0
    last = cells[-1]
    for c in cells:
        cum += c["prob"]
        if r <= cum:
            return c["h"], c["a"]
    return last["h"], last["a"]


def optimize_ticket(
    matches: list[TicketMatch],
    rules: QuinielaRules,
    n_opponents: int = 29,
    n_sims: int = 4000,
    skill_lo: float = 0.78,
    skill_hi: float = 1.0,
    draw_prop_lo: float = 0.04,
    draw_prop_hi: float = 0.15,
    seed: int = 20260611,
) -> TicketResult:
    """Pick, per match, EV vs contrarian to maximize simulated P(finishing 1st)."""
    if not matches:
        return TicketResult({}, [], 0.0, 0.0, n_sims, n_opponents)

    rng = random.Random(seed)
    n_matches = len(matches)

    # Pre-tabulate, per sim: the sampled actual score, the field's best human
    # total, and each candidate pick's points for every match (common random
    # numbers across all candidate tickets keeps swap comparisons apples-to-apples).
    ev_pts = [[0] * n_sims for _ in range(n_matches)]
    contra_pts = [[0] * n_sims for _ in range(n_matches)]
    field_best = [0] * n_sims

    for s in range(n_sims):
        actuals = []
        for mi, m in enumerate(matches):
            ah, aa = _sample_scoreline(rng, m.cells)
            actuals.append((ah, aa))
            o_ev, e_ev = m.ev_pick
            o_co, e_co = m.contra_pick
            ev_pts[mi][s] = score_actual(ah, aa, o_ev, e_ev, rules)
            contra_pts[mi][s] = score_actual(ah, aa, o_co, e_co, rules)

        best = 0
        for _ in range(n_opponents):
            skill = rng.uniform(skill_lo, skill_hi)
            draw_prop = rng.uniform(draw_prop_lo, draw_prop_hi)
            total = 0
            for mi, m in enumerate(matches):
                outcome, exact = _human_pick(rng, m.elo_probs, skill, draw_prop)
                ah, aa = actuals[mi]
                total += score_actual(ah, aa, outcome, exact, rules)
            if total > best:
                best = total
        field_best[s] = best

    def win_prob(choice: list[list[int]]) -> float:
        """P(rank=1) of a ticket. choice[mi] is ev_pts[mi] or contra_pts[mi]."""
        wins = 0.0
        for s in range(n_sims):
            total = 0
            for mi in range(n_matches):
                total += choice[mi][s]
            if total > field_best[s]:
                wins += 1.0
            elif total == field_best[s]:
                wins += 0.5  # optimistic split on a tie for the lead
        return wins / n_sims

    # Greedy: start all-EV, swap a match to contrarian only if it helps.
    choice = [ev_pts[mi] for mi in range(n_matches)]
    base_win = win_prob(choice)
    current = base_win
    swapped: list[int] = []

    improved = True
    while improved:
        improved = False
        for mi, m in enumerate(matches):
            if m.ev_pick == m.contra_pick or choice[mi] is contra_pts[mi]:
                continue
            choice[mi] = contra_pts[mi]
            cand = win_prob(choice)
            if cand > current + 1e-9:
                current = cand
                improved = True
            else:
                choice[mi] = ev_pts[mi]  # revert

    chosen: dict[int, tuple[str, str]] = {}
    for mi, m in enumerate(matches):
        if choice[mi] is contra_pts[mi]:
            chosen[m.match_id] = m.contra_pick
            swapped.append(m.match_id)
        else:
            chosen[m.match_id] = m.ev_pick

    return TicketResult(
        chosen=chosen,
        swapped_to_contrarian=swapped,
        win_prob_ev=base_win,
        win_prob_pool=current,
        n_sims=n_sims,
        n_opponents=n_opponents,
    )
