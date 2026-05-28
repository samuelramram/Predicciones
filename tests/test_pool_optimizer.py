"""Tests for the pool-aware ticket optimizer (P(rank=1) objective)."""
from __future__ import annotations

from wc_predictor.config import DEFAULT_CONFIG
from wc_predictor.model.pool_optimizer import TicketMatch, optimize_ticket
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

RULES = DEFAULT_CONFIG.rules
MCFG = DEFAULT_CONFIG.model


def _ticket_match(mid: int, lh: float, la: float) -> TicketMatch:
    cells, p1, px, p2, mass, gmax = build_score_matrix(lh, la, MCFG)
    pick = optimize_pick_from_cells(cells, p1, px, p2, mass, gmax, RULES, MCFG,
                                    forbid_outcomes=("X",))
    return TicketMatch(
        match_id=mid,
        cells=cells,
        elo_probs=(p1, px, p2),
        ev_pick=(pick.pick_1x2, pick.pick_exact),
        contra_pick=(pick.contrarian_pick_1x2, pick.contrarian_pick_exact),
    )


def test_empty_ticket_returns_zero():
    res = optimize_ticket([], RULES, n_sims=50)
    assert res.chosen == {}
    assert res.win_prob_ev == 0.0


def test_optimizer_runs_and_never_worsens_win_prob():
    matches = [_ticket_match(i, lh, la) for i, (lh, la) in enumerate([
        (2.1, 0.7), (1.5, 1.3), (1.1, 1.0), (2.4, 0.6), (1.2, 1.4),
    ])]
    res = optimize_ticket(matches, RULES, n_sims=800, n_opponents=29)
    # Greedy can only accept swaps that raise the objective, so the pool ticket
    # must be at least as good as the all-EV ticket under common random numbers.
    assert res.win_prob_pool >= res.win_prob_ev - 1e-9
    assert set(res.chosen) == {m.match_id for m in matches}
    assert all(mid in res.chosen for mid in res.swapped_to_contrarian)


def test_swapped_matches_use_contrarian_pick():
    matches = [_ticket_match(i, lh, la) for i, (lh, la) in enumerate([
        (2.6, 0.5), (1.4, 1.35), (1.0, 1.05),
    ])]
    res = optimize_ticket(matches, RULES, n_sims=600)
    by_id = {m.match_id: m for m in matches}
    for mid in res.swapped_to_contrarian:
        assert res.chosen[mid] == by_id[mid].contra_pick
