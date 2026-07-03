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
let this fall out of the simulation rather than a hand-set rule.

What the simulation knows (all optional, all degrade gracefully):

- **Exactos tiebreaker** (`rules.tiebreaker_exactos`): the leaderboard breaks
  point ties by exact-score hits, so every player carries a `(points, exactos)`
  tuple through the sim and "winning" is the lexicographic comparison. A player
  sitting one point behind with a big exactos edge is closer to the lead than
  the raw points suggest — and picks that add exact-score probability compound
  the tiebreak cushion.
- **Real opponent picks** (`OpponentState.picks`): when the webapp's picks for
  the decision round are known (ingest.pool_picks), each opponent is scored on
  their ACTUAL ticket against the same sampled outcomes, instead of a synthetic
  human model. Differentiation value becomes exact: swapping onto a scoreline a
  rival already holds buys nothing; splitting from the pack buys a lot.
- **Multiple candidates per match** (`TicketMatch.alt_picks`): besides the
  EV-optimal pick the optimizer may choose the best cell of ANY other outcome —
  including the draw, which per-match EV rules forbid. The greedy sweep accepts
  whichever candidate raises simulated P(rank=1).

Method (per round / jornada):
  1. Monte-Carlo the WHOLE remaining tournament with common random numbers:
       - decision round: sample each match's "true" scoreline from its blended
         cells; score your candidate picks and every opponent against the SAME
         actuals (common-outcome coupling is what gives differentiation value);
       - each opponent starts from their real cumulative (points, exactos);
       - tail (the `horizon` matches after this round): an independent
         (points, exactos) draw per player from their empirical per-match skill
         (2 pts w.p. e, 1 pt w.p. q-e, else 0).
  2. Start from the all-EV ticket and greedily swap individual matches to any
     alternative candidate whenever the swap raises simulated P(finishing 1st).

With no standings/horizon supplied this reduces to the original single-round,
from-zero behaviour. Exposed via `generate_picks --objective pool`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from wc_predictor.config import QuinielaRules
from wc_predictor.model.pool_sim import _human_pick
from wc_predictor.scoring.quiniela import score_actual


@dataclass
class TicketMatch:
    """One match's inputs to the pool optimizer."""
    match_id: object
    cells: list[dict]                       # blended score matrix (prob per scoreline)
    elo_probs: tuple[float, float, float]   # (p1, px, p2) for the human field model
    ev_pick: tuple[str, str]                # (1x2, exact)
    contra_pick: tuple[str, str]            # (1x2, exact)
    # Extra candidates beyond ev_pick (best cell of the other outcomes, draw
    # included). None → fall back to [contra_pick] (legacy two-candidate mode).
    alt_picks: list[tuple[str, str]] | None = None


@dataclass
class OpponentState:
    """A real pool opponent's current standing and empirical skill.

    `points`/`exactos` are the cumulative marker so far (the cushion you must
    overcome — exactos matter because they break point ties on the leaderboard).
    `q_rate`/`e_rate` are per-match hit rates derived from the leaderboard:
        e_rate = exactos / matches_resolved              (exact-score rate)
        q_rate = (points - exactos) / matches_resolved   (1X2 rate, incl. exact)
    They drive the tail (future-match) point draws — pure marker statistics, no
    narrative knobs.

    `picks` (optional): the opponent's REAL submitted picks for the decision
    round, as {match_id: "h-a"}. When present for a match, the sim scores that
    exact ticket instead of drawing a synthetic human pick.
    """
    name: str
    points: float
    q_rate: float = 0.0
    e_rate: float = 0.0
    exactos: float = 0.0
    picks: dict = field(default_factory=dict)


@dataclass
class TicketResult:
    chosen: dict[object, tuple[str, str]]   # match_id -> (1x2, exact) selected
    swapped_to_contrarian: list             # match_ids swapped off the EV pick
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


def _sample_tail(rng: random.Random, q_rate: float, e_rate: float,
                 horizon: int) -> tuple[int, int]:
    """(points, exactos) a player accrues over `horizon` future matches, sampled
    from their empirical per-match outcome: 2 pts (an exacto) w.p. e_rate,
    1 pt w.p. (q_rate - e_rate), else 0. q_rate is the 1X2 hit rate (which
    includes exacts), so q_rate >= e_rate."""
    if horizon <= 0:
        return 0, 0
    e = max(0.0, min(1.0, e_rate))
    q = max(e, min(1.0, q_rate))
    pts = ex = 0
    for _ in range(horizon):
        r = rng.random()
        if r < e:
            pts += 2
            ex += 1
        elif r < q:
            pts += 1
    return pts, ex


def _score_pick(ah: int, aa: int, pick: tuple[str, str], rules: QuinielaRules) -> tuple[int, int]:
    """(points, exact_hit) for a pick against the actual 90' score."""
    pts = score_actual(ah, aa, pick[0], pick[1], rules)
    exact = 1 if pick[1] == f"{ah}-{aa}" else 0
    return pts, exact


def _parse_pick(txt: str) -> tuple[str, str]:
    """'2-1' → ('1', '2-1'); outcome derived from the scoreline."""
    h, _, a = txt.partition("-")
    h, a = int(h), int(a)
    outcome = "X" if h == a else ("1" if h > a else "2")
    return outcome, f"{h}-{a}"


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
    your_exactos: float = 0.0,
    opponents: list[OpponentState] | None = None,
    your_q_rate: float = 0.0,
    your_e_rate: float = 0.0,
    horizon: int = 0,
) -> TicketResult:
    """Pick, per match, among the EV pick and its alternatives to maximize
    simulated P(finishing 1st).

    Single-round mode (defaults): `opponents=None`, `your_points=0`, `horizon=0`
    reproduces the original from-zero, this-round-only objective.

    Tournament mode: pass the real `opponents` (with cumulative points/exactos,
    empirical rates and — when captured — their real picks for this round),
    your own cumulative stats, and the `horizon` of matches still to come after
    this round. The objective becomes P(finishing the tournament 1st) under the
    leaderboard's tie rule, so the chase-vs-cushion trade-off is decided by the
    gap and the runway, not a hand-tuned rule.
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

    tiebreak = getattr(rules, "tiebreaker_exactos", False)

    # Candidate picks per match: EV first, then alternatives (deduped).
    cand_picks: list[list[tuple[str, str]]] = []
    for m in matches:
        alts = m.alt_picks if m.alt_picks is not None else [m.contra_pick]
        seen = [m.ev_pick]
        for alt in alts:
            if alt not in seen:
                seen.append(alt)
        cand_picks.append(seen)

    # Real opponent picks parsed once: opp_pick[j][mi] = (outcome, exact) | None
    opp_real: list[list[tuple[str, str] | None]] = []
    if use_real_field:
        for opp in opponents:
            row = []
            for m in matches:
                raw = (opp.picks or {}).get(m.match_id)
                row.append(_parse_pick(raw) if raw else None)
            opp_real.append(row)

    # Pre-tabulate, per sim: your candidates' per-match (points, exactos), your
    # tail draw, and the field's best (points, exactos) tuple (cushion + round +
    # tail). Common random numbers across candidate tickets keep swap
    # comparisons apples-to-apples. The field total is independent of YOUR
    # choice, so it is fully precomputed here.
    cand_pts = [[[0] * n_sims for _ in cands] for cands in cand_picks]
    cand_ex = [[[0] * n_sims for _ in cands] for cands in cand_picks]
    your_tail = [(0, 0)] * n_sims
    field_best: list[tuple[float, float]] = [(float("-inf"), float("-inf"))] * n_sims

    for s in range(n_sims):
        actuals = []
        for mi, m in enumerate(matches):
            ah, aa = _sample_scoreline(rng, m.cells)
            actuals.append((ah, aa))
            for ci, pick in enumerate(cand_picks[mi]):
                pts, ex = _score_pick(ah, aa, pick, rules)
                cand_pts[mi][ci][s] = pts
                cand_ex[mi][ci][s] = ex

        your_tail[s] = _sample_tail(rng, your_q_rate, your_e_rate, horizon)

        best: tuple[float, float] = (float("-inf"), float("-inf"))
        for j in range(n_opponents):
            if use_real_field:
                opp = opponents[j]
                total, total_ex = opp.points, opp.exactos
                q_rate, e_rate = opp.q_rate, opp.e_rate
            else:
                total = total_ex = 0.0
                q_rate = e_rate = 0.0
            skill = rng.uniform(skill_lo, skill_hi)
            draw_prop = rng.uniform(draw_prop_lo, draw_prop_hi)
            for mi, m in enumerate(matches):
                real = opp_real[j][mi] if use_real_field else None
                pick = real if real is not None else _human_pick(rng, m.elo_probs, skill, draw_prop)
                pts, ex = _score_pick(actuals[mi][0], actuals[mi][1], pick, rules)
                total += pts
                total_ex += ex
            t_pts, t_ex = _sample_tail(rng, q_rate, e_rate, horizon)
            total += t_pts
            total_ex += t_ex
            key = (total, total_ex) if tiebreak else (total, 0.0)
            if key > best:
                best = key
        field_best[s] = best

    def win_prob(choice: list[int]) -> float:
        """P(rank=1) of a ticket. choice[mi] indexes cand_picks[mi]."""
        wins = 0.0
        for s in range(n_sims):
            pts = your_points + your_tail[s][0]
            ex = your_exactos + your_tail[s][1]
            for mi in range(n_matches):
                pts += cand_pts[mi][choice[mi]][s]
                ex += cand_ex[mi][choice[mi]][s]
            key = (pts, ex) if tiebreak else (pts, 0.0)
            if key > field_best[s]:
                wins += 1.0
            elif key == field_best[s]:
                wins += 0.5  # split on a dead-even tie (points AND tiebreaker)
        return wins / n_sims

    # Expected exactos of each candidate (per match, independent across matches):
    # the greedy tie-breaker below. When a swap leaves simulated P(rank=1) flat —
    # common under Monte-Carlo quantization — prefer the candidate that banks
    # more expected exact hits: exactos break leaderboard point ties, so at equal
    # win probability the deeper exactos cushion strictly dominates.
    ex_mean = [[sum(col) / n_sims for col in cand_ex[mi]] for mi in range(n_matches)]

    # Greedy: start all-EV, move a match to any alternative only if it helps —
    # more win probability, or equal win probability with more expected exactos
    # (only a tiebreak-aware swap; never trades win probability away).
    choice = [0] * n_matches
    base_win = win_prob(choice)
    current = base_win

    improved = True
    while improved:
        improved = False
        for mi in range(n_matches):
            if len(cand_picks[mi]) == 1:
                continue
            best_ci, best_win = choice[mi], current
            for ci in range(len(cand_picks[mi])):
                if ci == choice[mi]:
                    continue
                choice[mi] = ci
                cand = win_prob(choice)
                better = cand > best_win + 1e-9
                tied_more_exactos = (
                    tiebreak
                    and abs(cand - best_win) <= 1e-9
                    and ex_mean[mi][ci] > ex_mean[mi][best_ci] + 1e-9
                )
                if better or tied_more_exactos:
                    best_ci, best_win = ci, cand
            choice[mi] = best_ci
            if best_win > current + 1e-9:
                current = best_win
                improved = True

    chosen: dict = {}
    swapped: list = []
    for mi, m in enumerate(matches):
        pick = cand_picks[mi][choice[mi]]
        chosen[m.match_id] = pick
        if pick != m.ev_pick:
            swapped.append(m.match_id)

    return TicketResult(
        chosen=chosen,
        swapped_to_contrarian=swapped,
        win_prob_ev=base_win,
        win_prob_pool=current,
        n_sims=n_sims,
        n_opponents=n_opponents,
    )
