"""Tests del Reportero: multiplicadores acotados sobre el calibrado."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wc_predictor.liga import reportero as rep
from wc_predictor.liga.europa import EUROPA_MODEL

BASE = {"pick_1x2": "2", "pick_exact": "1-2", "p1x2": [0.35, 0.26, 0.39],
        "p_over25": 0.60, "p_btts": 0.62, "goals": [1.35, 1.55]}
RND = {"round_id": "eu-2026-W41", "matches": [
    {"n": 1, "league": "E0", "date": "2026-10-11", "kickoff_utc": "2026-10-11T15:30+00:00",
     "home": "Liverpool", "away": "Man City", "market": {"avg_1x2": [2.7, 3.6, 2.5]},
     "bots": {"calibrado": BASE}},
    {"n": 2, "league": "E0", "date": "2026-10-10", "kickoff_utc": "2026-10-10T11:30+00:00",
     "home": "Arsenal", "away": "Leeds", "market": {}, "bots": {"calibrado": {**BASE, "pick_exact": "2-0"}}},
    {"league": "E0", "date": "2026-10-10", "home": "X", "away": "Y", "bots": {}},   # not on ticket
]}
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def test_no_news_is_exactly_calibrado():
    out = rep.adjust(BASE, 1.0, 1.0, EUROPA_MODEL)
    assert out["p1x2"] == BASE["p1x2"] and out["pick_exact"] == BASE["pick_exact"]


def test_news_moves_probabilities_the_right_way():
    weaker_home = rep.adjust(BASE, 0.8, 1.0, EUROPA_MODEL)
    assert weaker_home["p1x2"][0] < BASE["p1x2"][0] and weaker_home["p1x2"][2] > BASE["p1x2"][2]
    assert sum(weaker_home["p1x2"]) == pytest.approx(1.0, abs=2e-3)
    assert weaker_home["p_over25"] < BASE["p_over25"]          # fewer goals expected


def test_ticket_clamps_skips_started_and_ignores_mismatched_notes():
    notes = {"matches": [
        {"n": 1, "home": "Liverpool", "away": "Man City", "home_mult": 5, "away_mult": 0.1,
         "nota": "x", "fuentes": ["https://a"]},
        {"n": 2, "home": "Chelsea", "away": "Leeds", "home_mult": 0.8}]}
    picks, msgs = rep.build_ticket(RND, notes, NOW)
    assert [p["n"] for p in picks] == [1, 2]
    assert (picks[0]["home_mult"], picks[0]["away_mult"]) == (1.25, 0.75)
    assert picks[1]["home_mult"] == 1.0 and any("no cuadra" in m for m in msgs)
    assert picks[0]["fuentes"] == ["https://a"]
    later = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    picks2, msgs2 = rep.build_ticket(RND, notes, later)
    assert [p["n"] for p in picks2] == [1] and any("ya empezó" in m for m in msgs2)


def test_falls_back_to_implied_goals_for_old_rounds():
    old = {k: v for k, v in BASE.items() if k != "goals"}
    out = rep.adjust(old, 0.9, 1.0, EUROPA_MODEL)
    assert out["p1x2"][0] < old["p1x2"][0]
