"""Tests for the jornada-3 qualification context: FIFA 2026 standings with
tiebreakers and the per-match stakes classification."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.model.qualification import (
    TOP2_ELIMINATED,
    TOP2_POSSIBLE,
    TOP2_SECURED,
    compute_standings,
    j3_stakes,
)


def _m(home: str, away: str, hs: int, as_: int) -> dict:
    return {"home": home, "away": away, "home_score": hs, "away_score": as_}


# --- compute_standings ---

def test_compute_standings_orders_by_points_then_gd():
    matches = [_m("A", "B", 2, 0), _m("C", "D", 1, 0),
               _m("A", "C", 0, 0), _m("B", "D", 0, 0)]
    table = compute_standings(["A", "B", "C", "D"], matches)
    # A: win + draw = 4 pts, gd +2 ; C: win + draw = 4 pts, gd +1
    assert [t.team for t in table] == ["A", "C", "D", "B"]


def test_compute_standings_head_to_head_beats_overall_gd():
    # P and Q both finish on 3 pts. Q has the better OVERALL goal difference
    # (+3 vs -2), but P won the head-to-head, so FIFA puts P above Q.
    matches = [_m("P", "Q", 1, 0), _m("P", "R", 0, 3),
               _m("Q", "S", 4, 0), _m("R", "S", 0, 0)]
    table = compute_standings(["P", "Q", "R", "S"], matches)
    assert [t.team for t in table] == ["R", "P", "Q", "S"]


def test_compute_standings_ignores_unplayed_matches():
    matches = [_m("A", "B", 1, 0), {"home": "C", "away": "D",
                                    "home_score": None, "away_score": None}]
    table = compute_standings(["A", "B", "C", "D"], matches)
    by_team = {t.team: t for t in table}
    assert by_team["A"].points == 3 and by_team["A"].played == 1
    assert by_team["C"].played == 0 and by_team["D"].played == 0


# --- j3_stakes ---

# Group result after J1+J2:
#   J1: A 1-0 B, C 2-0 D   J2: A 1-0 C, B 1-0 D
#   => A 6 pts, B 3, C 3, D 0. J3 fixtures: A vs D and B vs C.
_J12_SECURED = [_m("A", "B", 1, 0), _m("C", "D", 2, 0),
                _m("A", "C", 1, 0), _m("B", "D", 1, 0)]


def test_j3_stakes_secured_and_eliminated_make_a_dead_rubber():
    ctx = j3_stakes("X", ["A", "B", "C", "D"], _J12_SECURED, "A", "D")
    assert ctx.home_status == TOP2_SECURED       # A on 6 pts cannot drop out of top 2
    assert ctx.away_status == TOP2_ELIMINATED    # D on 0 pts cannot reach top 2
    assert ctx.dead_rubber is True


def test_j3_stakes_decisive_match_is_not_a_dead_rubber():
    ctx = j3_stakes("X", ["A", "B", "C", "D"], _J12_SECURED, "B", "C")
    assert ctx.home_status == TOP2_POSSIBLE
    assert ctx.away_status == TOP2_POSSIBLE
    assert ctx.dead_rubber is False


def test_j3_stakes_mutual_draw_safe():
    # J1: A 3-0 C, B 3-0 D   J2: A 3-0 D, B 3-0 C
    # => A and B both on 6 pts, C and D on 0. J3 fixture A vs B: a draw sends
    # both through regardless of the C vs D result.
    j12 = [_m("A", "C", 3, 0), _m("B", "D", 3, 0),
           _m("A", "D", 3, 0), _m("B", "C", 3, 0)]
    ctx = j3_stakes("Y", ["A", "B", "C", "D"], j12, "A", "B")
    assert ctx.home_status == TOP2_SECURED
    assert ctx.away_status == TOP2_SECURED
    assert ctx.dead_rubber is True
    assert ctx.mutual_draw_safe is True


def test_j3_stakes_returns_none_before_two_rounds_complete():
    j12 = [_m("A", "B", 1, 0), _m("C", "D", 2, 0)]  # only J1 played
    assert j3_stakes("Z", ["A", "B", "C", "D"], j12, "A", "D") is None


def test_j3_stakes_note_is_populated():
    ctx = j3_stakes("X", ["A", "B", "C", "D"], _J12_SECURED, "A", "D")
    assert "nada en juego" in ctx.note
