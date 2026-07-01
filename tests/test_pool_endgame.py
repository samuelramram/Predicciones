"""Tests for the endgame upgrades: exactos tiebreaker, real opponent picks,
multi-candidate swaps, knockout draw gate / goal damp, and the pool-picks ingest."""
from __future__ import annotations

from dataclasses import replace

from wc_predictor.config import DEFAULT_CONFIG
from wc_predictor.model.pool_optimizer import (
    OpponentState,
    TicketMatch,
    _parse_pick,
    optimize_ticket,
)
from wc_predictor.pipeline.generate_picks import _forbid_outcomes
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

RULES = DEFAULT_CONFIG.rules
MCFG = DEFAULT_CONFIG.model


def _ticket_match(mid, lh: float, la: float) -> TicketMatch:
    cells, p1, px, p2, mass, gmax = build_score_matrix(lh, la, MCFG)
    pick = optimize_pick_from_cells(cells, p1, px, p2, mass, gmax, RULES, MCFG,
                                    forbid_outcomes=("X",))
    return TicketMatch(
        match_id=mid,
        cells=cells,
        elo_probs=(p1, px, p2),
        ev_pick=(pick.pick_1x2, pick.pick_exact),
        contra_pick=(pick.contrarian_pick_1x2, pick.contrarian_pick_exact),
        alt_picks=pick.alt_picks,
    )


# ---------------------------------------------------------------- quiniela ---

def test_contrarian_can_be_forbidden_outcome():
    """Draws are banned for the EV pick, but the contrarian/alt candidates keep
    the draw on the table (the pool MC decides whether to play it)."""
    cells, p1, px, p2, mass, gmax = build_score_matrix(1.1, 1.05, MCFG)
    pick = optimize_pick_from_cells(cells, p1, px, p2, mass, gmax, RULES, MCFG,
                                    forbid_outcomes=("X",))
    assert pick.pick_1x2 != "X"
    outcomes_in_alts = {o for o, _ in pick.alt_picks}
    assert "X" in outcomes_in_alts
    # In a near coin-flip the under-picked draw dominates ev/p_outcome.
    assert pick.contrarian_pick_1x2 == "X"


def test_contrarian_include_forbidden_false_restores_old_behaviour():
    cells, p1, px, p2, mass, gmax = build_score_matrix(1.1, 1.05, MCFG)
    pick = optimize_pick_from_cells(cells, p1, px, p2, mass, gmax, RULES, MCFG,
                                    forbid_outcomes=("X",),
                                    contrarian_include_forbidden=False)
    assert pick.contrarian_pick_1x2 != "X"


# ---------------------------------------------------------- pool optimizer ---

def test_parse_pick_outcomes():
    assert _parse_pick("2-1") == ("1", "2-1")
    assert _parse_pick("1-1") == ("X", "1-1")
    assert _parse_pick("0-3") == ("2", "0-3")


def test_exactos_tiebreak_changes_win_prob():
    """Same points, better exactos → with the tiebreak you win the sims you
    previously only half-won. P(rank=1) must be strictly higher."""
    matches = [_ticket_match(i, lh, la) for i, (lh, la) in enumerate([
        (1.8, 0.9), (1.2, 1.1),
    ])]
    # One opponent glued to your cumulative points but behind on exactos, whose
    # real picks match your EV picks — the round can't separate you, so the
    # outcome hangs almost entirely on the tiebreaker.
    opp = OpponentState(
        "rival", points=60.0, exactos=10.0,
        picks={m.match_id: m.ev_pick[1] for m in matches},
    )
    kw = dict(your_points=60.0, opponents=[opp], n_sims=600, horizon=0)

    res_tb = optimize_ticket(matches, RULES, your_exactos=14.0, **kw)
    rules_no_tb = replace(RULES, tiebreaker_exactos=False)
    res_flat = optimize_ticket(matches, rules_no_tb, your_exactos=14.0, **kw)

    assert res_tb.win_prob_ev > res_flat.win_prob_ev
    # With identical tickets and a 4-exacto cushion, the tiebreak makes you
    # near-certain to stay ahead.
    assert res_tb.win_prob_ev > 0.95


def test_real_picks_reward_differentiation():
    """If the lone rival holds exactly your EV ticket, mirroring them caps you at
    a coin flip — the optimizer must find a deviation that beats P=0.5."""
    matches = [_ticket_match(i, lh, la) for i, (lh, la) in enumerate([
        (1.6, 0.8), (1.3, 1.2), (1.0, 1.0),
    ])]
    opp = OpponentState(
        "clon", points=0.0, exactos=0.0,
        picks={m.match_id: m.ev_pick[1] for m in matches},
    )
    res = optimize_ticket(matches, RULES, opponents=[opp], n_sims=800)
    # All-EV vs the clone is a pure tie (0.5 by construction).
    assert abs(res.win_prob_ev - 0.5) < 1e-9
    assert res.win_prob_pool > 0.5
    assert res.swapped_to_contrarian  # it had to move off at least one pick


def test_single_round_mode_backwards_compatible():
    matches = [_ticket_match(i, lh, la) for i, (lh, la) in enumerate([
        (2.1, 0.7), (1.5, 1.3), (1.1, 1.0),
    ])]
    res = optimize_ticket(matches, RULES, n_sims=400, n_opponents=10)
    assert res.win_prob_pool >= res.win_prob_ev - 1e-9
    assert set(res.chosen) == {m.match_id for m in matches}


# ------------------------------------------------------------ KO handling ---

def test_ko_draw_gate_is_lower():
    """P(X)=0.36 stays banned in groups but unlocks in knockouts."""
    assert "X" in _forbid_outcomes(MCFG, 0.36, is_knockout=False)
    assert "X" not in _forbid_outcomes(MCFG, 0.36, is_knockout=True)
    assert "X" in _forbid_outcomes(MCFG, 0.30, is_knockout=True)


def test_ko_goal_env_ratio_default_damps():
    assert 0.0 < MCFG.ko_goal_env_ratio <= 1.0
