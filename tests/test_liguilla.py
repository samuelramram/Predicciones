"""Tests for the Liga MX liguilla model (table, seeding, two-legged series, MC)."""
from __future__ import annotations

import random

from wc_predictor.model.liguilla import (
    QF_CROSS, Series, build_final, build_quarterfinals, compute_table,
    project_liguilla, reseed_semifinals, series_advance_prob, sim_series, build_cdf,
)


def _match(h, a, hs, as_):
    return {"stage": "regular", "home": h, "away": a, "home_score": hs, "away_score": as_}


# --- table --------------------------------------------------------------------
def test_table_points_and_order():
    teams = ["A", "B", "C", "D"]
    matches = [
        _match("A", "B", 2, 0),   # A win
        _match("C", "D", 1, 1),   # draw
        _match("A", "C", 3, 1),   # A win
        _match("B", "D", 0, 0),   # draw
    ]
    table = compute_table(matches, teams)
    by = {r.team: r for r in table}
    assert by["A"].points == 6 and by["A"].gf == 5 and by["A"].ga == 1
    assert by["C"].points == 1 and by["B"].points == 1 and by["D"].points == 2
    # A is first (most points); order is by points → GD → GF.
    assert table[0].team == "A"


def test_table_seeds_unplayed_teams():
    table = compute_table([], ["X", "Y", "Z"])
    assert len(table) == 3 and all(r.played == 0 and r.points == 0 for r in table)


# --- bracket ------------------------------------------------------------------
def test_quarterfinal_crossings():
    seeds = [f"S{i}" for i in range(1, 9)]  # S1..S8
    qf = build_quarterfinals(seeds)
    pairs = {(s.high, s.low) for s in qf}
    assert pairs == {("S1", "S8"), ("S2", "S7"), ("S3", "S6"), ("S4", "S5")}
    # Higher seed always hosts the vuelta (second leg).
    for s in qf:
        legs = s.legs()
        assert legs[0] == ("ida", s.low, s.high)
        assert legs[1] == ("vuelta", s.high, s.low)


def test_semifinal_reseed_by_table():
    # QF winners: seeds 1, 2, 3, 8 survive → best-vs-worst, 2nd-vs-3rd.
    seed_of = {"A": 1, "B": 2, "C": 3, "H": 8}
    sf = reseed_semifinals(["H", "B", "A", "C"], seed_of)
    pairs = {(s.high, s.low) for s in sf}
    assert pairs == {("A", "H"), ("B", "C")}  # 1v8, 2v3


# --- series advancement -------------------------------------------------------
def _cells_from_probs(prob_by_score):
    return [{"h": h, "a": a, "prob": p, "outcome": ("1" if h > a else "X" if h == a else "2"),
             "score": f"{h}-{a}"} for (h, a), p in prob_by_score.items()]


def test_series_advance_symmetric_tie_goes_to_higher_seed():
    # Both legs a certain 0-0 → aggregate tie → higher seed advances (QF/SF rule).
    ida = _cells_from_probs({(0, 0): 1.0})
    vta = _cells_from_probs({(0, 0): 1.0})
    assert series_advance_prob(ida, vta, tie_to_higher=True) == 1.0
    # In the final an aggregate tie is a coin flip.
    assert abs(series_advance_prob(ida, vta, tie_to_higher=False) - 0.5) < 1e-9


def test_series_advance_higher_seed_wins_both_legs():
    # ida: low home loses 0-1 (high scores as away); vuelta: high home wins 1-0.
    ida = _cells_from_probs({(0, 1): 1.0})   # low 0 - high 1
    vta = _cells_from_probs({(1, 0): 1.0})   # high 1 - low 0
    assert series_advance_prob(ida, vta, tie_to_higher=True) == 1.0


def test_sim_series_deterministic_scorelines():
    rng = random.Random(0)
    ida = build_cdf(_cells_from_probs({(0, 2): 1.0}))   # low 0 - high 2
    vta = build_cdf(_cells_from_probs({(0, 0): 1.0}))   # high 0 - low 0
    # High seed aggregate 2, low 0 → high advances every time.
    assert all(sim_series(rng, ida, vta) for _ in range(20))


# --- projection ---------------------------------------------------------------
def test_projection_probabilities_are_coherent():
    teams = [f"T{i}" for i in range(1, 9)]  # exactly 8 → everyone makes liguilla
    # A round-robin's worth of played matches so the table is fully determined.
    played = [_match(teams[0], teams[i], 3, 0) for i in range(1, 8)]

    def cells_fn(h, a):
        # T1 crushes everyone; others symmetric.
        if h == "T1":
            return _cells_from_probs({(2, 0): 0.7, (1, 1): 0.2, (0, 1): 0.1})
        if a == "T1":
            return _cells_from_probs({(0, 2): 0.7, (1, 1): 0.2, (1, 0): 0.1})
        return _cells_from_probs({(1, 0): 0.34, (1, 1): 0.32, (0, 1): 0.34})

    proj = project_liguilla(played, [], cells_fn, teams, n_sims=500)
    for t in teams:
        assert abs(proj.reach[t]["liguilla"] - 1.0) < 1e-9  # 8 teams, all qualify
        # Monotone: champion ≤ final ≤ semi ≤ qf.
        rc = proj.reach[t]
        assert rc["champion"] <= rc["final"] + 1e-9 <= rc["semi_final"] + 1e-9
    # Champion probabilities sum to 1 across the field.
    assert abs(sum(proj.reach[t]["champion"] for t in teams) - 1.0) < 1e-9
    # T1 is the strongest and top seed → clear favourite.
    assert proj.reach["T1"]["champion"] == max(proj.reach[t]["champion"] for t in teams)
