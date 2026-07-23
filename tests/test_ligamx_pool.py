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
