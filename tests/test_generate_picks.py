"""Tests for the generate_picks pipeline — round filtering and host detection."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.pipeline.generate_picks import _host_role, resolve_round_filter


# --- Round filter ---

def test_round_filter_all():
    pred, label = resolve_round_filter("all")
    assert label == "all"
    assert pred({"stage": "group_stage"}) is True
    assert pred({"stage": "final"}) is True


def test_round_filter_group_stage():
    pred, label = resolve_round_filter("group_stage")
    assert label == "group_stage"
    assert pred({"stage": "group_stage"}) is True
    assert pred({"stage": "round_of_32"}) is False


def test_round_filter_matchday():
    pred, label = resolve_round_filter("md7")
    assert label == "md7"
    assert pred({"round_label": "Matchday 7"}) is True
    assert pred({"round_label": "Matchday 8"}) is False


def test_round_filter_knockout_stage():
    pred, label = resolve_round_filter("quarter_final")
    assert label == "quarter_final"
    assert pred({"stage": "quarter_final"}) is True
    assert pred({"stage": "semi_final"}) is False


def test_round_filter_rejects_unknown():
    with pytest.raises(SystemExit):
        resolve_round_filter("nonsense_round")


# --- Host role detection ---

VENUES = {
    "Estadio Azteca": {"country": "Mexico"},
    "MetLife Stadium": {"country": "United States"},
    "BC Place": {"country": "Canada"},
}


def test_host_role_home_team_is_host():
    fx = {"venue": "Estadio Azteca", "home": "Mexico", "away": "South Africa"}
    assert _host_role(fx, VENUES) == "home"


def test_host_role_away_team_is_host():
    # Asymmetric case: openfootball labels the host in the away column.
    fx = {"venue": "Estadio Azteca", "home": "Czech Republic", "away": "Mexico"}
    assert _host_role(fx, VENUES) == "away"


def test_host_role_neutral_venue():
    fx = {"venue": "MetLife Stadium", "home": "Brazil", "away": "Argentina"}
    assert _host_role(fx, VENUES) is None


def test_host_role_unknown_venue_is_neutral():
    fx = {"venue": "Some Unknown Stadium", "home": "Brazil", "away": "Argentina"}
    assert _host_role(fx, VENUES) is None
