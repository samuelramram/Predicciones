"""International Elo computation.

Standard World Football Elo update with goal-difference multiplier (Hill, 2009):

    expected_home = 1 / (1 + 10^(-(R_home + H - R_away)/400))
    update = K * G * (actual - expected)

where:
    H = home advantage in Elo points (default 80; 0 for neutral venues — most WC games)
    K = stage-dependent constant (friendly < qualifier < tournament < knockout)
    G = goal-difference scalar (1 for ±1, 1.5 for ±2, (11 + |gd|) / 8 for ≥3)

We expose two entry points:

1. `compute_elo_history(matches, cfg)` — replay an entire match history to build
   per-team trajectories. Used once during bootstrap.
2. `update_elo(elos, match, cfg)` — incremental single-match update. Used during the
   tournament to keep ratings live as results come in.
"""
from __future__ import annotations

from dataclasses import dataclass

from wc_predictor.config import ModelConfig


def _goal_diff_multiplier(gd: int) -> float:
    g = abs(gd)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8.0


def _k_for_stage(stage: str, cfg: ModelConfig) -> float:
    stage_l = stage.lower()
    if "friendly" in stage_l:
        return cfg.elo_k_friendly
    if "qualifier" in stage_l or "qualification" in stage_l:
        return cfg.elo_k_qualifier
    if "knockout" in stage_l or "final" in stage_l or "semi" in stage_l or "quarter" in stage_l or "round_of" in stage_l:
        return cfg.elo_k_wc_knockout
    return cfg.elo_k_tournament


@dataclass
class EloMatch:
    home: str
    away: str
    home_score: int
    away_score: int
    neutral: bool
    stage: str


def update_elo(
    elos: dict[str, float],
    match: EloMatch,
    cfg: ModelConfig,
    default_elo: float = 1500.0,
) -> dict[str, float]:
    r_home = elos.get(match.home, default_elo)
    r_away = elos.get(match.away, default_elo)
    h = 0.0 if match.neutral else cfg.elo_home_bonus

    e_home = 1.0 / (1.0 + 10 ** (-(r_home + h - r_away) / 400.0))
    e_away = 1.0 - e_home

    gd = match.home_score - match.away_score
    if gd > 0:
        s_home, s_away = 1.0, 0.0
    elif gd < 0:
        s_home, s_away = 0.0, 1.0
    else:
        s_home = s_away = 0.5

    k = _k_for_stage(match.stage, cfg)
    g = _goal_diff_multiplier(gd)
    delta_home = k * g * (s_home - e_home)
    delta_away = k * g * (s_away - e_away)

    new = dict(elos)
    new[match.home] = r_home + delta_home
    new[match.away] = r_away + delta_away
    return new
