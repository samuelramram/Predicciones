"""Tests for the expected-prize objective (`QuinielaRules.prize_shares`).

The Liga MX pot pays 80% to 1st and 20% to 2nd, so the ticket that maximizes
P(1st) is NOT the ticket that maximizes money: it treats a locked-in 2nd place
as worthless. These tests pin the placement math, the winner-takes-all
equivalence (so the World Cup path is untouched), and the behaviour that
motivated the change — an unreachable 1st place must still leave a gradient.
"""
from __future__ import annotations

from wc_predictor.config import QuinielaRules
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE, WC2026_PROFILE
from wc_predictor.model.pool_optimizer import (
    OpponentState,
    TicketMatch,
    _placement_share,
    optimize_ticket,
)

SHARES = (0.8, 0.2)


def _cells(p_home: float, p_draw: float) -> list[dict]:
    """Toy three-outcome matrix: 1-0 / 1-1 / 0-1."""
    return [
        {"h": 1, "a": 0, "prob": p_home, "outcome": "1"},
        {"h": 1, "a": 1, "prob": p_draw, "outcome": "X"},
        {"h": 0, "a": 1, "prob": 1.0 - p_home - p_draw, "outcome": "2"},
    ]


def _matches(n: int, p_home: float = 0.37, p_draw: float = 0.26) -> list[TicketMatch]:
    return [
        TicketMatch(
            match_id=f"m{i}",
            cells=_cells(p_home, p_draw),
            elo_probs=(p_home, p_draw, 1.0 - p_home - p_draw),
            ev_pick=("1", "1-0"),
            contra_pick=("2", "0-1"),
            alt_picks=[("2", "0-1"), ("X", "1-1")],
        )
        for i in range(n)
    ]


# ------------------------------------------------------------- placement ---

def test_placement_share_pays_each_rank():
    assert _placement_share(0, 0, SHARES) == 0.8       # 1st outright
    assert _placement_share(1, 0, SHARES) == 0.2       # 2nd outright
    assert _placement_share(2, 0, SHARES) == 0.0       # off the podium


def test_placement_share_splits_ties():
    # Tied for the lead with one rival: you split 1st + 2nd.
    assert _placement_share(0, 1, SHARES) == (0.8 + 0.2) / 2
    # Tied for 2nd with one rival: you split 2nd + nothing.
    assert _placement_share(1, 1, SHARES) == 0.2 / 2
    # Three-way tie for the lead spans 1st, 2nd and an unpaid 3rd.
    assert _placement_share(0, 2, SHARES) == (0.8 + 0.2) / 3


def test_placement_share_winner_takes_all_is_p_first():
    assert _placement_share(0, 0, (1.0,)) == 1.0
    assert _placement_share(1, 0, (1.0,)) == 0.0
    assert _placement_share(0, 1, (1.0,)) == 0.5      # coin-flip on a dead tie


# ---------------------------------------------------------------- profiles ---

def test_ligamx_pays_two_places_wc_pays_one():
    """The prize split is a property of the pool, read off the webapp."""
    assert LIGAMX_APERTURA_PROFILE.rules.prize_shares == (0.8, 0.2)
    assert WC2026_PROFILE.rules.prize_shares == (1.0,)


def test_default_rules_are_winner_takes_all():
    assert QuinielaRules().prize_shares == (1.0,)


# --------------------------------------------------------------- optimizer ---

def _run(shares: tuple[float, ...], **kw):
    rules = QuinielaRules(prize_shares=shares)
    opponents = [
        OpponentState("Lider", 45, 0.60, 0.20, 14,
                      picks={f"m{i}": "1-0" for i in range(9)}),
        OpponentState("Tercero", 29, 0.52, 0.13, 8,
                      picks={f"m{i}": "0-1" for i in range(9)}),
        OpponentState("Cuarto", 22, 0.48, 0.11, 5,
                      picks={f"m{i}": "0-1" for i in range(9)}),
    ]
    return optimize_ticket(
        _matches(9), rules, n_sims=4000, your_points=30, your_exactos=9,
        opponents=opponents, your_q_rate=0.54, your_e_rate=0.15, horizon=0, **kw
    )


def test_winner_takes_all_objective_matches_p_first():
    """With a single paid place the maximized objective IS the win probability,
    so nothing about the World Cup path changes."""
    res = _run((1.0,))
    assert res.prize_ev == res.win_prob_ev
    assert res.prize_pool == res.win_prob_pool


def test_second_place_keeps_a_gradient_when_first_is_out_of_reach():
    """The motivating case: the leader is unreachable, so P(1st) is flat at zero
    and gives the optimizer nothing to steer by — while 20% of the pot is still
    live and worth protecting."""
    winner_take_all = _run((1.0,))
    two_places = _run(SHARES)

    assert winner_take_all.win_prob_pool == 0.0      # 1st genuinely gone
    assert winner_take_all.prize_pool == 0.0         # ...and the old objective is flat
    # The 80/20 pool still values the ticket, and never below the EV baseline.
    assert two_places.prize_pool > 0.1
    assert two_places.prize_pool >= two_places.prize_ev


def test_prize_shares_reported_on_the_result():
    res = _run(SHARES)
    assert res.prize_shares == SHARES


def test_synthetic_field_sized_from_pool_rules():
    """Without standings the field size comes from the pool's own rules, not a
    hard-coded World-Cup-sized constant."""
    rules = QuinielaRules(pool_participants=12)
    res = optimize_ticket(_matches(3), rules, n_sims=400)
    assert res.n_opponents == 11
