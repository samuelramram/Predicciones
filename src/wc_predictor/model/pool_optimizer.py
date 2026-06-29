"""Pool-aware ticket optimizer — maximize P(finishing 1st), not individual EV.

This closes the loop the diagnostic `pool_sim` left open. In a winner-takes-most
pool the objective is NOT to maximize your own expected points (that just tracks
the favourite and ties you with everyone else who did the same) — it is to
maximize the probability of finishing FIRST. Those are different objectives: the
EV-optimal ticket is low-variance, and low variance is exactly what you do NOT
want when you only get paid for rank 1.

Horizon- and gap-aware objective (the part that decides *how much* to gamble):
the right amount of differentiation depends on (a) how far you currently are from
the lead and (b) how many matches are still left to play. With a big gap and few
matches remaining you must inject variance NOW (chase); with a small gap and a
long runway your per-match edge compounds and variance only hurts (cushion). We
let this fall out of the simulation rather than a hand-set rule:

Method (per round / jornada):
  1. For every match we already have a blended score-matrix and two candidate
     picks from the EV optimizer: the EV-optimal pick and the contrarian pick
     (max ev / p_outcome — the under-picked, high-leverage outcome).
  2. Monte-Carlo the WHOLE remaining tournament with common random numbers:
       - decision round: sample each match's "true" scoreline from its blended
         cells; score your ticket and every opponent against the SAME actuals
         (this common-outcome coupling is what gives differentiation its value —
         when the favourite loses, everyone who picked it loses together);
       - each opponent starts from their real current points (the cushion/gap);
       - tail (the `horizon` matches still to come after this round): add an
         independent points draw per player from their empirical per-match skill
         (2 pts w.p. e, 1 pt w.p. q-e, else 0). More remaining matches = more tail
         variance = a small gap is more likely to close on its own, so the
         optimizer keeps EV; a big gap with a short tail forces it to swap.
  3. Start from the all-EV ticket and greedily swap individual matches to their
     contrarian pick whenever the swap raises the simulated P(finishing 1st).

With no standings/horizon supplied this reduces exactly to the original
single-round, from-zero behaviour. Exposed via `generate_picks --objective pool`.
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
class OpponentState:
    """A real pool opponent's current standing and empirical skill.

    `points` is the cumulative score so far (the cushion you must overcome).
    `q_rate`/`e_rate` are per-match hit rates derived from the leaderboard:
        e_rate = exactos / matches_resolved              (exact-score rate)
        q_rate = (points - exactos) / matches_resolved   (1X2 rate, incl. exact)
    They drive the tail (future-match) point draws — pure marker statistics, no
    narrative knobs.
    """
    name: str
    points: float
    q_rate: float = 0.0
    e_rate: float = 0.0


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


def _sample_tail_points(rng: random.Random, q_rate: float, e_rate: float, horizon: int) -> int:
    """Points a player accrues over `horizon` future matches, sampled from their
    empirical per-match outcome: 2 pts w.p. e_rate, 1 pt w.p. (q_rate - e_rate),
    else 0. q_rate is the 1X2 hit rate (which includes exacts), so q_rate >= e_rate.
    """
    if horizon <= 0:
        return 0
    e = max(0.0, min(1.0, e_rate))
    q = max(e, min(1.0, q_rate))
    total = 0
    for _ in range(horizon):
        r = rng.random()
        if r < e:
            total += 2
        elif r < q:
            total += 1
    return total


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
    *,
    your_points: float = 0.0,
    opponents: list[OpponentState] | None = None,
    your_q_rate: float = 0.0,
    your_e_rate: float = 0.0,
    horizon: int = 0,
) -> TicketResult:
    """Pick, per match, EV vs contrarian to maximize simulated P(finishing 1st).

    Single-round mode (defaults): `opponents=None`, `your_points=0`, `horizon=0`
    reproduces the original from-zero, this-round-only objective.

    Tournament mode: pass the real `opponents` (with current points + empirical
    rates), `your_points`, your own rates, and the `horizon` of matches still to
    come after this round. The objective becomes P(finishing the tournament 1st),
    so the chase-vs-cushion trade-off is decided by the gap and the runway, not a
    hand-tuned rule.
    """
    if not matches:
        return TicketResult({}, [], 0.0, 0.0, n_sims, n_opponents)

    rng = random.Random(seed)
    n_matches = len(matches)
    use_real_field = opponents is not None
    if use_real_field:
        n_opponents = len(opponents)
    if n_opponents == 0:
        # Nobody to beat: any ticket "wins". Keep the all-EV ticket.
        chosen = {m.match_id: m.ev_pick for m in matches}
        return TicketResult(chosen, [], 1.0, 1.0, n_sims, 0)

    # Pre-tabulate, per sim: your candidate per-match points, your tail draw, and
    # the field's best total (cushion + round + tail). Common random numbers across
    # candidate tickets keep swap comparisons apples-to-apples. The field total is
    # independent of YOUR choice, so it is fully precomputed here.
    ev_pts = [[0] * n_sims for _ in range(n_matches)]
    contra_pts = [[0] * n_sims for _ in range(n_matches)]
    your_tail = [0] * n_sims
    field_best = [0.0] * n_sims

    for s in range(n_sims):
        actuals = []
        for mi, m in enumerate(matches):
            ah, aa = _sample_scoreline(rng, m.cells)
            actuals.append((ah, aa))
            o_ev, e_ev = m.ev_pick
            o_co, e_co = m.contra_pick
            ev_pts[mi][s] = score_actual(ah, aa, o_ev, e_ev, rules)
            contra_pts[mi][s] = score_actual(ah, aa, o_co, e_co, rules)

        your_tail[s] = _sample_tail_points(rng, your_q_rate, your_e_rate, horizon)

        best = float("-inf")
        for j in range(n_opponents):
            if use_real_field:
                opp = opponents[j]
                cushion = opp.points
                q_rate, e_rate = opp.q_rate, opp.e_rate
            else:
                cushion = 0.0
                q_rate = e_rate = 0.0
            skill = rng.uniform(skill_lo, skill_hi)
            draw_prop = rng.uniform(draw_prop_lo, draw_prop_hi)
            total = cushion
            for mi, m in enumerate(matches):
                outcome, exact = _human_pick(rng, m.elo_probs, skill, draw_prop)
                ah, aa = actuals[mi]
                total += score_actual(ah, aa, outcome, exact, rules)
            total += _sample_tail_points(rng, q_rate, e_rate, horizon)
            if total > best:
                best = total
        field_best[s] = best

    def win_prob(choice: list[list[int]]) -> float:
        """P(rank=1) of a ticket. choice[mi] is ev_pts[mi] or contra_pts[mi]."""
        wins = 0.0
        for s in range(n_sims):
            total = your_points + your_tail[s]
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
