"""Tests for ingest.pool_picks: CSV parsing, orientation, standings recompute."""
from __future__ import annotations

import json

from wc_predictor.config import DEFAULT_CONFIG, WC_DIR
from wc_predictor.ingest.pool_picks import (
    _parse_score,
    parse_export,
    recompute_standings,
    round_from_filename,
)
from pathlib import Path

RULES = DEFAULT_CONFIG.rules


def test_round_from_filename():
    assert round_from_filename(Path("predicciones_Fase_de_Grupos__J1_3.csv")) == "j1"
    assert round_from_filename(Path("predicciones_Dieciseisavos_de_Final_3.csv")) == "round_of_32"
    assert round_from_filename(Path("octavos.csv")) == "round_of_16"
    assert round_from_filename(Path("Final.csv")) == "final"


def test_parse_score():
    assert _parse_score("2-1") == (2, 1)
    assert _parse_score("Pendiente") is None
    assert _parse_score("") is None


def _fixture_by_teams(home: str, away: str) -> dict:
    with (WC_DIR / "fixtures.json").open(encoding="utf-8") as f:
        doc = json.load(f)
    for m in doc["matches"]:
        if {m.get("home"), m.get("away")} == {home, away}:
            return m
    raise AssertionError(f"fixture {home} vs {away} not found")


def test_parse_export_orients_to_fixture(tmp_path):
    """The app lists 'Bélgica vs Senegal'; whatever order fixtures.json uses,
    the persisted pick must be oriented to the fixture's home/away."""
    fx = _fixture_by_teams("Belgium", "Senegal")
    csv_src = tmp_path / "dieciseisavos.csv"
    csv_src.write_text(
        "Usuario,Partido,Predicción,Resultado Real,Puntos\n"
        "Tester,Bélgica vs Senegal,3-1,Pendiente,-\n",
        encoding="utf-8",
    )
    rd = parse_export(csv_src, "round_of_32")
    pick = rd["picks"]["Tester"][fx["match_id"]]
    if fx["home"] == "Belgium":
        assert pick == (3, 1)
    else:
        assert pick == (1, 3)


def test_recompute_standings_counts_exactos(tmp_path):
    fx = _fixture_by_teams("Belgium", "Senegal")
    mid = fx["match_id"]
    belgium_first = fx["home"] == "Belgium"
    rounds = [{
        "round": "round_of_32",
        "results": {mid: (2, 2)},
        "picks": {"A": {mid: (2, 2)}, "B": {mid: (1, 1) }},
        # app points missing → recomputed locally from picks vs results
        "points": {"A": {mid: None}, "B": {mid: None}},
    }]
    st = recompute_standings(rounds, you="A", rules=RULES)
    by_name = {p["name"]: p for p in st["players"]}
    assert by_name["A"]["points"] == 2 and by_name["A"]["exactos"] == 1
    assert by_name["B"]["points"] == 1 and by_name["B"]["exactos"] == 0
    assert st["matches_resolved"] == 1
    assert belgium_first in (True, False)  # orientation asserted in the other test
