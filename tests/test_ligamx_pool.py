"""Tests for the Liga MX pool ingest — pure helpers + parse against real fixtures."""
from __future__ import annotations

import json
from pathlib import Path

from wc_predictor.ingest.ligamx_pool import (
    _parse_score,
    build_standings,
    parse_export,
    pool_total_matches,
    resolve_team,
    round_from_filename,
    _name_resolver,
)
from wc_predictor.pipeline.ligamx import FIXTURES_JSON


def test_resolve_team_accepts_variants():
    r = _name_resolver()
    assert resolve_team("Club América", r) == "América"
    assert resolve_team("AME", r) == "América"
    assert resolve_team("américa", r) == "América"
    assert resolve_team("Xolos de Tijuana", r) == "Tijuana"
    # Unknown passes through trimmed.
    assert resolve_team("  Cometas FC ", r) == "Cometas FC"


def test_round_from_filename():
    assert round_from_filename(Path("quiniela_j2.csv")) == 2
    assert round_from_filename(Path("J17-export.csv")) == 17
    import pytest
    with pytest.raises(SystemExit):
        round_from_filename(Path("sinjornada.csv"))


def test_parse_score():
    assert _parse_score("2-1") == (2, 1)
    assert _parse_score(" 0 - 3 ") == (0, 3)
    assert _parse_score("Pendiente") is None
    assert _parse_score("") is None
    assert _parse_score("x-y") is None


def test_build_standings_ranks_by_points_then_exactos():
    rounds = [{
        "jornada": 1,
        "picks": {},
        "points": {
            "A": {"m1": 2, "m2": 1},   # 3 pts, 1 exacto
            "B": {"m1": 2, "m2": 2},   # 4 pts, 2 exactos → leads
            "C": {"m1": 1, "m2": None},  # 1 pt
        },
    }]
    st = build_standings(rounds, you="A", total_matches=153)
    assert st["total_matches"] == 153
    assert [p["name"] for p in st["players"]] == ["B", "A", "C"]
    assert st["players"][0] == {"name": "B", "points": 4, "exactos": 2}
    # m2 for C was None → not counted as resolved for C, but m1/m2 resolved overall.
    assert st["matches_resolved"] == 2


def test_pool_total_matches_counts_from_start_round():
    """Regression: the pool horizon must count only the matches the pool WILL
    score (J3→final), not the full 153-match calendar. Over-counting the horizon
    biased the P(1.º) optimizer toward playing it too safe near the finish."""
    # J3..J17 = 15 jornadas * 9 = 135 regular matches (committed fixtures).
    doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    regular_from_j3 = sum(1 for m in doc["matches"] if (m.get("jornada") or 0) >= 3)
    assert pool_total_matches(3, 0) == regular_from_j3
    # Liguilla matches (not yet in fixtures.json) are added on top.
    assert pool_total_matches(3, 17) == regular_from_j3 + 17
    # A pool that scored from J1 counts the whole calendar (+ liguilla).
    all_regular = sum(1 for m in doc["matches"] if (m.get("jornada") or 0) >= 1)
    assert pool_total_matches(1, 0) == all_regular
    # start_round is exclusive-below: J3 anchor drops J1+J2 (18 matches).
    assert pool_total_matches(1, 0) - pool_total_matches(3, 0) == 18


def test_parse_export_orients_to_fixture(tmp_path):
    """Integration: parse a synthetic J1 export against the real committed
    fixtures.json, checking name resolution + home/away orientation."""
    # Pick a real J1 fixture to build the CSV from.
    doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    j1 = [m for m in doc["matches"] if m.get("jornada") == 1]
    assert j1, "expected committed J1 fixtures"
    fx = j1[0]
    home, away = fx["home"], fx["away"]

    csv_path = tmp_path / "pool_j1.csv"
    # Write the match in REVERSED order to exercise the flip logic.
    csv_path.write_text(
        "Usuario,Partido,Predicción,Resultado Real,Puntos\n"
        f"Samuel,{away} vs {home},1-2,,3\n",
        encoding="utf-8",
    )
    rd = parse_export(csv_path, _name_resolver())
    assert rd["jornada"] == 1
    # "away vs home = 1-2" reversed to fixture orientation → home 2, away 1.
    assert rd["picks"]["Samuel"][fx["match_id"]] == "2-1"
    assert rd["points"]["Samuel"][fx["match_id"]] == 3


# ------------------------------------------------- empirical-Bayes shrinkage ---

def test_shrink_rates_collapses_luck_only_spread():
    """When the spread across players is no bigger than binomial noise, the
    leaderboard is luck: every player's best estimate is the pool mean.

    The Apertura case — after 18 matches the pool's observed spread was SMALLER
    than luck alone, yet the raw rates projected the leader ~60 points clear over
    the remaining horizon, reporting P(1st)=0 and flattening the objective."""
    from wc_predictor.model.standings import shrink_rates
    # 15 players scattered by luck alone around 0.45 over 18 matches
    rates = [0.72, 0.61, 0.56, 0.50, 0.50, 0.50, 0.44, 0.44,
             0.44, 0.44, 0.44, 0.33, 0.39, 0.39, 0.28]
    out = shrink_rates(rates, matches_resolved=18)
    mean = sum(rates) / len(rates)
    assert all(abs(r - mean) < 1e-9 for r in out)      # collapsed to the mean
    assert abs(sum(out) / len(out) - mean) < 1e-9      # mean preserved


def test_shrink_rates_keeps_real_skill_with_a_long_sample():
    """A spread far larger than luck survives: shrinkage keeps genuine skill."""
    from wc_predictor.model.standings import shrink_rates
    rates = [0.90, 0.85, 0.80, 0.50, 0.50, 0.20, 0.15, 0.10]
    out = shrink_rates(rates, matches_resolved=500)    # long sample → little noise
    mean = sum(rates) / len(rates)
    assert out[0] > mean + 0.25                        # the strong player stays strong
    assert out[-1] < mean - 0.25                       # the weak one stays weak
    # ordering preserved, spread only mildly compressed
    assert out == sorted(out, reverse=True)
    assert (max(out) - min(out)) > 0.6 * (max(rates) - min(rates))


def test_shrink_rates_edge_cases():
    from wc_predictor.model.standings import shrink_rates
    assert shrink_rates([0.5], 18) == [0.5]            # single player untouched
    assert shrink_rates([], 18) == []
    assert shrink_rates([0.4, 0.4], 0) == [0.4, 0.4]   # no matches → no inference
    same = shrink_rates([0.5, 0.5, 0.5], 20)           # zero spread stays put
    assert all(abs(r - 0.5) < 1e-9 for r in same)
