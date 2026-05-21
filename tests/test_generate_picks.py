"""Tests for the generate_picks pipeline — round filtering and host detection."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.pipeline.generate_picks import (
    _boleto_block,
    _fmt_score,
    _host_role,
    _round_title,
    resolve_round_filter,
)
from wc_predictor.config import QuinielaRules


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


# --- Report helpers ---

def test_fmt_score_spaces_out_scoreline():
    assert _fmt_score("2-0") == "2 - 0"
    assert _fmt_score("0-1") == "0 - 1"


def test_round_title_known_and_matchday_and_fallback():
    assert _round_title("group_stage") == "Fase de grupos"
    assert _round_title("quarter_final") == "Cuartos de final"
    assert _round_title("md7") == "Jornada 7"
    assert _round_title("weird_label") == "weird_label"


def _pick(home, away, exact, c_exact, ev=0.9, abstain=False, differs=True, actionable=False):
    """Minimal pick dict for boleto/report rendering tests."""
    return {
        "home": home, "away": away, "date": "2026-06-11", "match_id": 1,
        "pick_1x2": "1", "pick_exact": exact, "ev": ev, "ev_gap": 0.3, "abstain": abstain,
        "contrarian_pick_1x2": "2", "contrarian_pick_exact": c_exact,
        "contrarian_ev": ev - 0.1, "contrarian_score": 1.2,
        "contrarian_differs": differs, "contrarian_ev_sacrifice": 0.1,
        "contrarian_actionable": actionable,
    }


def test_boleto_block_marks_only_actionable_contrarian():
    rules = QuinielaRules()
    picks = [
        _pick("Mexico", "South Africa", "2-0", "0-1", actionable=True),
        _pick("Brazil", "Morocco", "1-0", "0-1", actionable=False),
    ]
    block = _boleto_block(picks, "md1", rules)
    lines = block.splitlines()
    mexico_line = next(line for line in lines if "Mexico" in line)
    brazil_line = next(line for line in lines if "Brazil" in line)
    assert "◆" in mexico_line          # actionable → flagged
    assert "◆" not in brazil_line      # differs but not actionable → no flag
    assert "1◆ contrarian accionable" in block


def test_boleto_block_marks_abstain():
    rules = QuinielaRules()
    picks = [_pick("Mexico", "South Africa", "2-0", "0-1", abstain=True)]
    block = _boleto_block(picks, "md1", rules)
    assert "★" in block
    assert "1★ ABSTAIN" in block
