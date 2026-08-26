"""Tests for the horizon- and gap-aware pool objective.

These assert the *strategic* property the optimizer is supposed to encode:
the amount of differentiation (swaps to contrarian) must rise when you are far
behind with little runway left (chase), and fall to zero when you are close with
a long runway (cushion) — driven by math, not a hand-set rule.
"""
from __future__ import annotations

from wc_predictor.config import DEFAULT_CONFIG
from wc_predictor.model.pool_optimizer import (
    OpponentState,
    TicketMatch,
    optimize_ticket,
)
from wc_predictor.model.standings import PoolContext, compute_horizon, load_pool_context
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

RULES = DEFAULT_CONFIG.rules
MCFG = DEFAULT_CONFIG.model


def _ticket_match(mid: int, lh: float, la: float) -> TicketMatch:
    cells, p1, px, p2, mass, gmax = build_score_matrix(lh, la, MCFG)
    pick = optimize_pick_from_cells(cells, p1, px, p2, mass, gmax, RULES, MCFG,
                                    forbid_outcomes=("X",))
    return TicketMatch(
        match_id=mid, cells=cells, elo_probs=(p1, px, p2),
        ev_pick=(pick.pick_1x2, pick.pick_exact),
        contra_pick=(pick.contrarian_pick_1x2, pick.contrarian_pick_exact),
    )


def _coinflip_ticket() -> list[TicketMatch]:
    # A few near-even matches where a contrarian pick is a live, leverage-able bet.
    return [_ticket_match(i, lh, la) for i, (lh, la) in enumerate([
        (1.5, 1.35), (1.4, 1.3), (1.45, 1.4), (1.3, 1.25),
    ])]


def test_backward_compatible_defaults():
    """With no standings/horizon, the result is the original single-round objective."""
    matches = _coinflip_ticket()
    a = optimize_ticket(matches, RULES, n_sims=600, n_opponents=10, seed=1)
    b = optimize_ticket(matches, RULES, n_sims=600, n_opponents=10, seed=1,
                        your_points=0.0, opponents=None, horizon=0)
    assert a.swapped_to_contrarian == b.swapped_to_contrarian
    assert a.win_prob_pool == b.win_prob_pool


def _opp_field(leader_pts: float, others_pts: float, n_others: int = 4) -> list[OpponentState]:
    return [OpponentState("leader", leader_pts, 0.6, 0.15)] + [
        OpponentState(f"o{i}", others_pts, 0.55, 0.12) for i in range(n_others)
    ]


def test_comfortable_lead_long_horizon_is_pure_ev():
    """Far ahead with a long runway → no reason to gamble: 0 swaps (cushion)."""
    matches = _coinflip_ticket()
    res = optimize_ticket(
        matches, RULES, n_sims=2000, seed=7,
        your_points=15.0, opponents=_opp_field(3.0, 2.0),
        your_q_rate=0.6, your_e_rate=0.15, horizon=40,
    )
    assert len(res.swapped_to_contrarian) == 0
    assert res.win_prob_ev > 0.5  # you are winning comfortably


def test_behind_winnable_short_horizon_forces_chase():
    """Behind by a winnable margin with no runway left → gamble, and it must
    measurably raise P(1st) (the differentiation earns its keep)."""
    matches = _coinflip_ticket()
    res = optimize_ticket(
        matches, RULES, n_sims=2000, seed=7,
        your_points=0.0, opponents=_opp_field(3.0, 1.0),
        your_q_rate=0.6, your_e_rate=0.15, horizon=0,
    )
    assert len(res.swapped_to_contrarian) >= 1
    assert res.win_prob_pool > res.win_prob_ev + 1e-6


def test_longer_horizon_never_gambles_more_at_fixed_gap():
    """Holding the gap fixed, a longer runway must not gamble more than a short
    one — your edge gets time to compound, so differentiation is less needed."""
    matches = _coinflip_ticket()
    opp = _opp_field(3.0, 1.0)
    short = optimize_ticket(matches, RULES, n_sims=2000, seed=7,
                            your_points=0.0, opponents=opp,
                            your_q_rate=0.6, your_e_rate=0.15, horizon=0)
    long = optimize_ticket(matches, RULES, n_sims=2000, seed=7,
                           your_points=0.0, opponents=opp,
                           your_q_rate=0.6, your_e_rate=0.15, horizon=30)
    assert len(long.swapped_to_contrarian) <= len(short.swapped_to_contrarian)


def test_load_pool_context_and_rates(tmp_path):
    import json
    doc = {
        "you": "Claudio", "matches_resolved": 74, "total_matches": 104,
        "total_participants": 5,
        "players": [
            {"name": "Bryan Montiel", "points": 59, "exactos": 10},
            {"name": "Claudio", "points": 58, "exactos": 13},
        ],
        "field_baseline": {"points": 50, "exactos": 8},
    }
    p = tmp_path / "pool_standings.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    ctx = load_pool_context(p)
    assert ctx is not None
    assert ctx.you == "Claudio"
    assert ctx.your_points == 58.0
    # Rates are empirical-Bayes shrunk toward the pool mean, so they sit BETWEEN
    # the raw sample rate (e = 13/74, q = (58-13)/74) and the two-player mean.
    # Two players 2 exactos apart over 74 matches is luck, so e shrinks a long way;
    # points are unaffected (only the projection rates are estimated).
    raw_e, raw_q = 13 / 74, (58 - 13) / 74
    mean_e = (10 / 74 + 13 / 74) / 2
    assert min(mean_e, raw_e) - 1e-9 <= ctx.your_e_rate <= max(mean_e, raw_e) + 1e-9
    assert 0.0 <= ctx.your_q_rate <= 1.0
    assert ctx.your_q_rate >= ctx.your_e_rate      # the q >= e invariant survives
    assert abs(ctx.your_q_rate - raw_q) < 0.1      # q spread is small here
    # 5 participants total, 2 listed (1 is you) -> 1 real opp + 3 baseline fills
    assert ctx.estimated_fill == 3
    assert len(ctx.opponents) == 4
    assert ctx.leader_points == 59.0
    # horizon = 104 - 74 - 14 = 16
    assert compute_horizon(ctx, decision_pending=14) == 16


def test_load_pool_context_missing_file(tmp_path):
    assert load_pool_context(tmp_path / "nope.json") is None
