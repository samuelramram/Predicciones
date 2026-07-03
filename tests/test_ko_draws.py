"""Tests for the knockout draw upgrades: modal-draw unlock, exactos-tilted EV
ranking (ko_exacto_ev_bonus), the pool greedy's expected-exactos tiebreak, and
the ingest's points-vs-result reconciliation (extra-time score detection)."""
from __future__ import annotations

from wc_predictor.config import DEFAULT_CONFIG
from wc_predictor.ingest.pool_picks import _reconcile_results
from wc_predictor.model.pool_optimizer import OpponentState, TicketMatch, optimize_ticket
from wc_predictor.pipeline.generate_picks import _forbid_outcomes
from wc_predictor.scoring.quiniela import optimize_pick_from_cells

RULES = DEFAULT_CONFIG.rules
MCFG = DEFAULT_CONFIG.model


# ------------------------------------------------------- modal-draw unlock ---

def test_modal_draw_unlocks_x_in_knockouts_only():
    px = MCFG.ko_modal_draw_min_prob + 0.001  # below the 0.33 KO gate
    assert px < MCFG.ko_draw_allow_min_prob
    assert "X" not in _forbid_outcomes(MCFG, px, is_knockout=True, modal_outcome="X")
    # Same signal in a group match stays banned (backtests negative there).
    assert "X" in _forbid_outcomes(MCFG, px, is_knockout=False, modal_outcome="X")
    # KO but the modal cell is a win → the probability gates still rule.
    assert "X" in _forbid_outcomes(MCFG, px, is_knockout=True, modal_outcome="1")


def test_modal_draw_unlock_respects_probability_floor():
    px = MCFG.ko_modal_draw_min_prob - 0.02
    assert "X" in _forbid_outcomes(MCFG, px, is_knockout=True, modal_outcome="X")


# --------------------------------------------------- exactos-tilted ranking ---

def _synthetic_cells():
    """Modal cell is the draw 1-1 but the outcome marginal favours the home win:
    pure EV picks 2-1, the exactos-tilted ranking picks 1-1."""
    spec = [
        # (h, a, prob) — best cell per outcome: 1-1 (X), 2-1 (1), 1-2 (2).
        # Marginals: p1=0.40, px=0.31, p2=0.29 → true EV 2-1 (0.49) edges 1-1
        # (0.48); a 0.5 exact tilt flips it (0.535 vs 0.565).
        (1, 1, 0.17), (0, 0, 0.08), (2, 2, 0.06),
        (2, 1, 0.09), (1, 0, 0.08), (2, 0, 0.08), (3, 1, 0.07), (3, 0, 0.08),
        (1, 2, 0.08), (0, 1, 0.08), (0, 2, 0.07), (1, 3, 0.06),
    ]
    assert abs(sum(p for _, _, p in spec) - 1.0) < 1e-9
    cells = [
        {"h": h, "a": a, "score": f"{h}-{a}", "prob": p,
         "outcome": "X" if h == a else ("1" if h > a else "2")}
        for h, a, p in spec
    ]
    p1 = sum(c["prob"] for c in cells if c["outcome"] == "1")
    px = sum(c["prob"] for c in cells if c["outcome"] == "X")
    p2 = sum(c["prob"] for c in cells if c["outcome"] == "2")
    return cells, p1, px, p2


def test_exact_ev_bonus_lands_on_modal_draw():
    cells, p1, px, p2 = _synthetic_cells()
    flat = optimize_pick_from_cells(cells, p1, px, p2, 1.0, 3, RULES, MCFG)
    assert (flat.pick_1x2, flat.pick_exact) == ("1", "2-1")

    tilted = optimize_pick_from_cells(cells, p1, px, p2, 1.0, 3, RULES, MCFG,
                                      exact_ev_bonus=0.5)
    assert (tilted.pick_1x2, tilted.pick_exact) == ("X", "1-1")
    # Reported EV is the TRUE expected points of 1-1, not the tilted metric.
    true_ev = RULES.points_exact * 0.17 + RULES.points_1x2 * (px - 0.17)
    assert abs(tilted.ev - true_ev) < 1e-9


def test_exact_ev_bonus_zero_is_noop():
    cells, p1, px, p2 = _synthetic_cells()
    a = optimize_pick_from_cells(cells, p1, px, p2, 1.0, 3, RULES, MCFG)
    b = optimize_pick_from_cells(cells, p1, px, p2, 1.0, 3, RULES, MCFG,
                                 exact_ev_bonus=0.0)
    assert (a.pick_1x2, a.pick_exact, a.ev) == (b.pick_1x2, b.pick_exact, b.ev)


# ------------------------------------------ pool greedy exactos tiebreak ---

def test_greedy_prefers_more_exactos_at_equal_win_prob():
    """An unreachable leader makes every ticket's P(rank=1) identical (0), so the
    greedy's only signal is the tiebreak: it must still move to the candidate
    with the higher expected exactos instead of staying on the EV pick."""
    cells, p1, px, p2 = _synthetic_cells()
    m = TicketMatch(
        match_id="m1",
        cells=cells,
        elo_probs=(p1, px, p2),
        ev_pick=("1", "2-1"),
        alt_picks=[("X", "1-1"), ("2", "1-2")],  # 1-1 has the higher P(exact)
        contra_pick=("X", "1-1"),
    )
    leader = OpponentState("lider", points=1000.0, exactos=50.0)
    res = optimize_ticket([m], RULES, opponents=[leader], n_sims=300)
    assert abs(res.win_prob_pool - res.win_prob_ev) < 1e-9  # no win prob traded
    assert res.chosen["m1"] == ("X", "1-1")
    assert res.swapped_to_contrarian == ["m1"]


def test_greedy_tiebreak_off_without_tiebreaker_rule():
    from dataclasses import replace
    cells, p1, px, p2 = _synthetic_cells()
    m = TicketMatch(
        match_id="m1", cells=cells, elo_probs=(p1, px, p2),
        ev_pick=("1", "2-1"), alt_picks=[("X", "1-1")], contra_pick=("X", "1-1"),
    )
    leader = OpponentState("lider", points=1000.0, exactos=50.0)
    rules_flat = replace(RULES, tiebreaker_exactos=False)
    res = optimize_ticket([m], rules_flat, opponents=[leader], n_sims=300)
    assert res.chosen["m1"] == ("1", "2-1")  # stays on the EV pick


# --------------------------------------------- ingest reconciliation (ET) ---

def test_reconcile_corrects_extra_time_score():
    """Displayed 3-2 (post-ET) contradicts points paid on the 90' 2-2 → the
    unique consistent scoreline replaces it (the Bélgica-Senegal case)."""
    results = {"m1": (3, 2)}
    picks = {
        "A": {"m1": (2, 2)},  # exacto → 2 pts only under 2-2
        "B": {"m1": (1, 1)},  # draw outcome → 1 pt
        "C": {"m1": (2, 1)},  # home win → 0 pts
    }
    points = {"A": {"m1": 2}, "B": {"m1": 1}, "C": {"m1": 0}}
    _reconcile_results(results, picks, points)
    assert results["m1"] == (2, 2)


def test_reconcile_infers_result_still_listed_pendiente():
    results = {"m1": None}
    picks = {
        "A": {"m1": (2, 2)},
        "B": {"m1": (1, 1)},
        "C": {"m1": (2, 1)},
    }
    points = {"A": {"m1": 2}, "B": {"m1": 1}, "C": {"m1": 0}}
    _reconcile_results(results, picks, points)
    assert results["m1"] == (2, 2)


def test_reconcile_keeps_consistent_result():
    results = {"m1": (2, 1)}
    picks = {"A": {"m1": (2, 1)}, "B": {"m1": (1, 1)}}
    points = {"A": {"m1": 2}, "B": {"m1": 0}}
    _reconcile_results(results, picks, points)
    assert results["m1"] == (2, 1)


def test_reconcile_drops_ambiguous_contradiction():
    """One 0-point pick can't pin the scoreline down — an inconsistent displayed
    result is dropped rather than guessed."""
    results = {"m1": (1, 1)}
    picks = {"A": {"m1": (1, 1)}}
    points = {"A": {"m1": 0}}  # a 1-1 pick scoring 0 contradicts a 1-1 result
    _reconcile_results(results, picks, points)
    assert results["m1"] is None


def test_reconcile_leaves_unscored_matches_alone():
    results = {"m1": None, "m2": (2, 0)}
    picks = {"A": {"m1": (1, 0), "m2": (2, 0)}}
    points = {"A": {"m1": None, "m2": None}}
    _reconcile_results(results, picks, points)
    assert results["m1"] is None
    assert results["m2"] == (2, 0)
