"""Unit tests for international Elo updates and replay."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wc_predictor.config import ModelConfig
from wc_predictor.ratings.elo import EloMatch, _goal_diff_multiplier, _k_for_stage, replay_history, update_elo


CFG = ModelConfig()


def test_gd_multiplier():
    assert _goal_diff_multiplier(0) == 1.0
    assert _goal_diff_multiplier(1) == 1.0
    assert _goal_diff_multiplier(-1) == 1.0
    assert _goal_diff_multiplier(2) == 1.5
    assert _goal_diff_multiplier(-2) == 1.5
    assert _goal_diff_multiplier(3) == (11 + 3) / 8.0
    assert _goal_diff_multiplier(5) == (11 + 5) / 8.0


def test_k_resolves_stage():
    assert _k_for_stage("Friendly", CFG) == CFG.elo_k_friendly
    assert _k_for_stage("FIFA World Cup qualification", CFG) == CFG.elo_k_qualifier
    assert _k_for_stage("UEFA Euro qualification", CFG) == CFG.elo_k_qualifier
    assert _k_for_stage("FIFA World Cup", CFG) == CFG.elo_k_tournament
    assert _k_for_stage("UEFA Euro", CFG) == CFG.elo_k_tournament
    assert _k_for_stage("Copa América", CFG) == CFG.elo_k_tournament
    # Synthetic knockout label (not present in martj42 but used internally)
    assert _k_for_stage("Final", CFG) == CFG.elo_k_wc_knockout
    assert _k_for_stage("Round_of_16", CFG) == CFG.elo_k_wc_knockout


def test_equal_strength_neutral_draw_no_change():
    elos = {"A": 1500.0, "B": 1500.0}
    update_elo(elos, EloMatch("A", "B", 0, 0, neutral=True, stage="Friendly"), CFG)
    assert abs(elos["A"] - 1500.0) < 1e-9
    assert abs(elos["B"] - 1500.0) < 1e-9


def test_home_win_against_equal_strength_increases_home_elo():
    elos = {"A": 1500.0, "B": 1500.0}
    update_elo(elos, EloMatch("A", "B", 1, 0, neutral=True, stage="Friendly"), CFG)
    # Equal teams, neutral, A wins 1-0: A gains K*1*(1 - 0.5) = 10.
    assert abs(elos["A"] - 1510.0) < 1e-9
    assert abs(elos["B"] - 1490.0) < 1e-9


def test_home_advantage_increases_expected_score():
    elos_neutral = {"A": 1500.0, "B": 1500.0}
    elos_home = {"A": 1500.0, "B": 1500.0}
    update_elo(elos_neutral, EloMatch("A", "B", 1, 0, neutral=True, stage="Friendly"), CFG)
    update_elo(elos_home, EloMatch("A", "B", 1, 0, neutral=False, stage="Friendly"), CFG)
    # With home advantage (+80 Elo), winning was MORE expected → gain less than neutral case.
    assert elos_home["A"] - 1500.0 < elos_neutral["A"] - 1500.0


def test_blowout_multiplier_amplifies_gain():
    elos_1_0 = {"A": 1500.0, "B": 1500.0}
    elos_5_0 = {"A": 1500.0, "B": 1500.0}
    update_elo(elos_1_0, EloMatch("A", "B", 1, 0, neutral=True, stage="Friendly"), CFG)
    update_elo(elos_5_0, EloMatch("A", "B", 5, 0, neutral=True, stage="Friendly"), CFG)
    assert (elos_5_0["A"] - 1500.0) > (elos_1_0["A"] - 1500.0)


def test_update_mutates_in_place_and_seeds_unknown_teams():
    elos: dict[str, float] = {}
    update_elo(elos, EloMatch("Brazil", "Argentina", 1, 0, neutral=True, stage="Copa América"), CFG)
    assert "Brazil" in elos and "Argentina" in elos
    # Brazil gained from 1500 default; Argentina lost the same amount (neutral, equal start)
    assert abs((elos["Brazil"] - 1500.0) + (elos["Argentina"] - 1500.0)) < 1e-9


def test_replay_history_tracks_only_requested_teams():
    matches = [
        {"date": "2024-01-01", "home": "Brazil", "away": "Argentina",
         "home_score": 1, "away_score": 0, "neutral": True, "tournament": "Friendly"},
        {"date": "2024-02-01", "home": "Mexico", "away": "Brazil",
         "home_score": 0, "away_score": 2, "neutral": False, "tournament": "Friendly"},
    ]
    elos, traj = replay_history(matches, CFG, track_teams={"Brazil"})
    assert set(traj.keys()) == {"Brazil"}
    assert len(traj["Brazil"]) == 2
    assert traj["Brazil"][0]["opponent"] == "Argentina"
    assert traj["Brazil"][1]["opponent"] == "Mexico"
    # Brazil should now be > Mexico (won) and Argentina < Brazil (lost)
    assert elos["Brazil"] > elos["Argentina"]
    assert elos["Brazil"] > elos["Mexico"]
