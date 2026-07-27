"""Tests for the Liga MX liguilla calibration.

The playoff is not the regular season with different opponents. Measured over
99 Liga MX playoff matches (2023-2026, isolated by the round the ingest now
keeps): 2.576 goals/match vs 2.860, and 32.3% level at 90' vs 23.9%. These tests
pin the three consequences — the goal damp, the lower draw gate with its modal
unlock, and the round/stage metadata that made the measurement possible at all.
"""
from __future__ import annotations

from dataclasses import replace

from wc_predictor.ingest.ligamx import (
    annotate_stages,
    event_to_history_row,
    stage_for_round,
)
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.poisson_dc import FitResult, TeamStrength
from wc_predictor.pipeline.ligamx import _liguilla_forbid, blended_matchup

MCFG = LIGAMX_APERTURA_PROFILE.model


# ------------------------------------------------------- round / stage data ---

def test_stage_for_round_splits_regular_from_liguilla():
    assert stage_for_round(1) == "regular"
    assert stage_for_round(17) == "regular"      # last jornada
    assert stage_for_round(125) == "liguilla"    # TheSportsDB playoff numbering
    assert stage_for_round(200) == "liguilla"
    assert stage_for_round(0) == ""              # source gave us nothing


def test_history_row_keeps_the_round():
    row = event_to_history_row({
        "dateEvent": "2026-05-10", "strHomeTeam": "Toluca", "strAwayTeam": "América",
        "intHomeScore": "2", "intAwayScore": "1", "intRound": "200",
        "strVenue": "Estadio Nemesio Díez",
    })
    assert row["round"] == 200
    assert row["stage"] == "liguilla"


def test_annotate_stages_backfills_playoffs_without_a_round():
    """TheSportsDB drops `intRound` on whole liguillas. Anything played after the
    torneo's last dated jornada is a playoff match — without this backfill the
    liguilla reads as regular season."""
    rows = [
        {"tournament": "Liga MX Apertura 2023", "date": "2023-11-12", "stage": "regular"},
        {"tournament": "Liga MX Apertura 2023", "date": "2023-11-29", "stage": ""},
        {"tournament": "Liga MX Apertura 2023", "date": "2023-12-17", "stage": ""},
        # A different torneo must not borrow the first one's cutoff.
        {"tournament": "Liga MX Clausura 2024", "date": "2024-02-01", "stage": ""},
    ]
    annotate_stages(rows)
    assert [r["stage"] for r in rows] == ["regular", "liguilla", "liguilla", ""]


# ------------------------------------------------------------- draw gating ---

def test_liguilla_uses_the_lower_draw_gate():
    """A P(X) that is not enough in the regular season can be enough in a leg."""
    px = (MCFG.ko_draw_allow_min_prob + MCFG.draw_allow_min_prob) / 2
    assert "X" in _liguilla_forbid(MCFG, px, modal_outcome="1", liguilla=False)
    assert "X" not in _liguilla_forbid(MCFG, px, modal_outcome="1", liguilla=True)


def test_modal_draw_unlocks_the_x_only_in_the_liguilla():
    """The blend rarely clears the probability gate outright, but a leg whose #1
    scoreline is itself a 0-0/1-1 is a draw signal. Regular season keeps the ban
    (the same rule backtests negative on non-knockout football)."""
    px = MCFG.ko_modal_draw_min_prob + 0.01
    assert px < MCFG.ko_draw_allow_min_prob      # only the modal path can lift it
    assert "X" not in _liguilla_forbid(MCFG, px, modal_outcome="X", liguilla=True)
    assert "X" in _liguilla_forbid(MCFG, px, modal_outcome="X", liguilla=False)


def test_weak_draw_signal_stays_banned_everywhere():
    px = MCFG.ko_modal_draw_min_prob - 0.05
    assert "X" in _liguilla_forbid(MCFG, px, modal_outcome="1", liguilla=True)
    assert "X" in _liguilla_forbid(MCFG, px, modal_outcome="1", liguilla=False)


# -------------------------------------------------------- goal environment ---

def _toy_fit() -> FitResult:
    return FitResult(
        mu=0.2, gamma=0.25, rho=-0.05,
        strengths={
            "A": TeamStrength(team="A", attack=0.10, defense=-0.05, n_matches=60),
            "B": TeamStrength(team="B", attack=0.00, defense=0.00, n_matches=60),
        },
        n_matches=120, n_teams=2, half_life_days=730, ridge_lambda=0.05,
        converged=True, final_neg_log_lik=0.0,
    )


def test_liguilla_damps_the_goal_environment():
    """Measured ratio is 0.90; the profile must carry it and the matrix must use
    it, or playoff legs get picked a goal too high."""
    assert MCFG.ko_goal_env_ratio == 0.90

    fit = _toy_fit()
    elos = {"A": 1550.0, "B": 1500.0}
    regular = blended_matchup("A", "B", fit, elos, {}, MCFG)
    playoff = blended_matchup("A", "B", fit, elos, {}, MCFG, liguilla=True)

    assert playoff["lambda_home"] < regular["lambda_home"]
    assert playoff["lambda_home"] / regular["lambda_home"] == MCFG.ko_goal_env_ratio
    # Fewer goals ⇒ more draws, which is the whole point.
    assert playoff["px"] > regular["px"]


def test_regular_season_calibration_is_untouched():
    """The liguilla flag must be opt-in: a jornada pick is byte-identical."""
    px = 0.30
    assert _liguilla_forbid(MCFG, px, "X", liguilla=False) == tuple(MCFG.forbid_outcomes)
    neutral = replace(MCFG, ko_goal_env_ratio=0.5)
    assert _liguilla_forbid(neutral, px, "1", liguilla=False) == tuple(MCFG.forbid_outcomes)
