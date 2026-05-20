"""International Elo computation.

Standard World Football Elo update with goal-difference multiplier (Hill, 2009):

    expected_home = 1 / (1 + 10^(-(R_home + H - R_away)/400))
    update = K * G * (actual - expected)

where:
    H = home advantage in Elo points (default 80; 0 for neutral venues — most WC games)
    K = stage-dependent constant (friendly < qualifier < tournament < knockout)
    G = goal-difference scalar (1 for ±1, 1.5 for ±2, (11 + |gd|) / 8 for ≥3)

Two entry points:

1. `update_elo(elos, match, cfg)` — incremental single-match update. Used during the
   tournament to keep ratings live as results come in. Mutates `elos` in place.
2. `replay_history(matches, cfg)` — replay an entire history, in chronological order,
   to build current ratings + (optionally) per-team trajectories.
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


@dataclass(frozen=True)
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
    """Apply one Elo update. Mutates `elos` in place AND returns it for chaining."""
    r_home = elos.setdefault(match.home, default_elo)
    r_away = elos.setdefault(match.away, default_elo)
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

    elos[match.home] = r_home + delta_home
    elos[match.away] = r_away + delta_away
    return elos


def replay_history(
    matches: list[dict],
    cfg: ModelConfig,
    default_elo: float = 1500.0,
    track_teams: set[str] | None = None,
) -> tuple[dict[str, float], dict[str, list[dict]]]:
    """Walk a chronologically-sorted match list, applying Elo updates.

    Args:
        matches: each dict has keys date, home, away, home_score, away_score,
                 neutral (bool), tournament (str).
        cfg: ModelConfig with elo_k_* and elo_home_bonus.
        default_elo: starting rating for any team not yet seen.
        track_teams: if given, accumulate trajectories for these teams only.

    Returns:
        elos: final rating per team (str → float).
        trajectories: per tracked team, list of {date, elo, opponent, vs_elo, result}.
    """
    elos: dict[str, float] = {}
    trajectories: dict[str, list[dict]] = {t: [] for t in (track_teams or set())}

    for row in matches:
        match = EloMatch(
            home=row["home"],
            away=row["away"],
            home_score=int(row["home_score"]),
            away_score=int(row["away_score"]),
            neutral=bool(row["neutral"]),
            stage=row["tournament"],
        )
        # Snapshot opponent strength BEFORE the update for trajectory clarity.
        pre_home = elos.get(match.home, default_elo)
        pre_away = elos.get(match.away, default_elo)
        update_elo(elos, match, cfg, default_elo)

        if track_teams:
            if match.home in track_teams:
                trajectories[match.home].append({
                    "date": row["date"],
                    "elo": elos[match.home],
                    "opponent": match.away,
                    "vs_elo": pre_away,
                    "venue": "home" if not match.neutral else "neutral",
                    "result": f"{match.home_score}-{match.away_score}",
                    "tournament": match.stage,
                })
            if match.away in track_teams:
                trajectories[match.away].append({
                    "date": row["date"],
                    "elo": elos[match.away],
                    "opponent": match.home,
                    "vs_elo": pre_home,
                    "venue": "away" if not match.neutral else "neutral",
                    "result": f"{match.away_score}-{match.home_score}",
                    "tournament": match.stage,
                })

    return elos, trajectories
