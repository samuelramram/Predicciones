"""Hyperparameters and scoring rules for the World Cup 2026 predictor.

Single source of truth. Anything that affects model output goes through here so the
fingerprint hash captures the run reproducibly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
WC_DIR = DATA_DIR / "wc2026"
HISTORICAL_DIR = DATA_DIR / "historical"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = REPO_ROOT / "outputs"

WC2026_LEAGUE_ID_THESPORTSDB = 4429
WC2026_LEAGUE_ID_API_FOOTBALL = 1  # API-Football's league id for the World Cup
WC2026_SEASON = 2026


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader so we don't depend on python-dotenv for one feature."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def get_thesportsdb_key() -> str | None:
    return os.environ.get("THESPORTSDB_API_KEY") or None


def get_api_football_key() -> str | None:
    return os.environ.get("API_FOOTBALL_KEY") or None


def get_odds_api_key() -> str | None:
    return os.environ.get("THE_ODDS_API_KEY") or None


@dataclass(frozen=True)
class QuinielaRules:
    """Scoring rules of the pool we are trying to win.

    Mutually-exclusive scoring: exact score awards `points_exact` (and NOT also the 1X2
    point); a correct 1X2 with wrong exact awards `points_1x2`; otherwise 0.

    Per user's pool (May 2026): exact=2, 1x2=1, exclusive=True, 90-minute result only.
    """

    points_exact: int = 2
    points_1x2: int = 1
    exclusive: bool = True
    use_90min_only: bool = True
    stage_multipliers: dict[str, float] = field(default_factory=dict)
    pool_participants: int = 30
    pool_buyin_mxn: int = 500


@dataclass(frozen=True)
class ModelConfig:
    """Hyperparameters for the Poisson + Dixon-Coles model and friends."""

    dc_rho: float = -0.10
    poisson_grid_target_mass: float = 0.995
    poisson_grid_min_goals: int = 5
    poisson_grid_max_cap: int = 12

    # Dixon-Coles rho was inherited as -0.10 from the Liga MX model and never
    # re-fit for international football. `fit_model` now profiles it by penalized
    # likelihood over this grid and persists the winner into team_strengths.json;
    # `generate_picks` then honours the fitted value (the score-matrix SHAPE — and
    # therefore the exact-score half of the quiniela points — depends on rho).
    fit_rho: bool = True
    rho_grid_lo: float = -0.25
    rho_grid_hi: float = 0.05
    rho_grid_step: float = 0.025

    # Per-competition weight multipliers applied ON TOP of the exponential recency
    # decay in the Poisson+DC fit. Recency alone weights a two-day-old friendly the
    # same as a two-day-old World-Cup match, yet the WC game is far more informative
    # for WC prediction. Up-weighting competitive matches means that, once the
    # tournament is under way, freshly-played WC results actually move team
    # strengths for the next round's picks (the in-tournament refit loop) instead of
    # being drowned out by years of friendlies. `competition_weight_wc` only bites
    # mid-tournament, since WC2026 matches aren't in the training CSV until played.
    competition_weight_friendly: float = 1.0
    competition_weight_qualifier: float = 1.5
    competition_weight_tournament: float = 2.0
    competition_weight_wc: float = 3.0

    # L2 ridge penalty on attack/defense latents (zero-mean prior). Lower values
    # let teams with fewer / more lopsided observations push further from zero —
    # important for African/Asian sides whose ratings were otherwise compressed
    # by the strong prior (Morocco/Senegal/Algeria looked like top-5 defenses
    # because the penalty dragged everyone toward the mean).
    ridge_lambda: float = 0.3

    elo_k_friendly: float = 20.0
    elo_k_qualifier: float = 30.0
    elo_k_tournament: float = 40.0
    elo_k_wc_knockout: float = 60.0
    elo_home_bonus: float = 80.0

    # Production blend weights — THE single source of truth (generate_picks reads
    # these directly; no module-level duplicate constants).
    #   no odds available → Poisson `blend_poisson_weight` / Elo `blend_elo_weight`
    #                       (the two must sum to 1.0; backtested optimum ≈ 0.70/0.30).
    #   odds available     → odds take `blend_odds_weight`, and the Poisson:Elo pair
    #                       keeps its ratio on the remaining (1 - blend_odds_weight).
    # `blend_odds_weight` is a literature-based default (closing odds are near
    # efficient; market Brier ≈0.23 vs our model ≈0.55). Tune via The Odds API
    # historical endpoint once a key exists.
    blend_elo_weight: float = 0.30
    blend_poisson_weight: float = 0.70
    blend_odds_weight: float = 0.55

    # Outcomes the production optimizer may NOT pick by default. Draws are net
    # negative in the backtest (the model picks the right NUMBER of draws but not
    # the right MATCHES) so "X" is excluded — EXCEPT when the blended P(X) clears
    # `draw_allow_min_prob`, where the draw signal is strong enough to be worth a
    # forfeit of pool differentiation. A J3 mutual-draw-safe match also lifts the ban.
    forbid_outcomes: tuple[str, ...] = ("X",)
    draw_allow_min_prob: float = 0.42

    # --- Match-context adjustments (model/adjustments.apply_context_adjustments) ---
    # World-Cup host nations enjoy a documented home boost BEYOND the generic gamma
    # the Poisson+DC fit already applies to the side on home soil. These multipliers
    # are layered ON TOP of that gamma for the host nation only.
    host_advantage_usa: float = 1.10
    host_advantage_mexico: float = 1.18
    host_advantage_canada: float = 1.06
    # Visiting (non-acclimatized) side loses this fraction of λ per 1000 m of venue
    # altitude. Only Mexico City (Estadio Azteca, 2240 m) moves the needle materially
    # (~9% at the default 0.04); sea-level US/Canada venues are ~0 by construction.
    altitude_penalty_per_1000m: float = 0.04
    # λ lost per 1000 km a team travelled since its previous fixture (no-op until a
    # travel feed populates MatchContext.{home,away}_prev_km).
    travel_penalty_per_1000km: float = 0.015
    # Squad availability: λ is scaled by (1 - unavailable_starter_pct), capped at this
    # fraction so a wave of withdrawals can't zero a team out (the Liga MX Chivas-J6 bug).
    injury_max_lambda_penalty: float = 0.25

    ev_abstain_gap: float = 0.02

    # Contrarian (pool-leverage) pick is flagged "actionable" only when the
    # individual-EV sacrifice vs the EV-optimal pick stays under this threshold.
    # contrarian_score = ev / p_outcome always favours the underdog, so without
    # this cap ~99% of matches would flag — the cap restricts the ◆ marker to
    # plays where the EV given up is small enough to be worth the differentiation.
    contrarian_max_ev_sacrifice: float = 0.15

    # WC group stage matches score ~2.81 goals/match (2010-2026) vs ~2.46 predicted
    # from a model trained on all international results (qualifiers, friendlies).
    # This multiplier inflates both λ_home and λ_away proportionally before the
    # score-matrix is built, correcting the ~12% systematic underestimate.
    wc_lambda_inflation: float = 1.12

    # Skill-gap (mismatch) inflation. The base fit underestimates blowouts because
    # weak nations (Cape Verde, Saudi Arabia, Curaçao, …) accumulate their defensive
    # rating against intra-confederation rivals of similar level; the model never
    # observes them being torched by a top side. When the predicted λ_strong / λ_weak
    # ratio crosses `mismatch_ratio_threshold`, ramp linearly to saturation: boost
    # the stronger team's λ up to `mismatch_strong_boost` and damp the weaker side
    # down to `mismatch_weak_damp`. Calibrated against WC 2018+2022 blowouts
    # (Spain 7-0 Costa Rica, Russia 5-0 Saudi, England 6-1 Panama, …).
    mismatch_ratio_threshold: float = 3.0
    mismatch_ratio_saturation: float = 5.0
    mismatch_strong_boost: float = 1.50
    mismatch_weak_damp: float = 0.65

    # Mismatch-aware pick override. When the dominant outcome's marginal exceeds
    # this threshold, expand the EV search beyond the modal cell: among home-win
    # cells whose individual EV gap to the modal pick is below
    # `mismatch_pick_ev_tolerance`, prefer the cell whose (h-a) is closest to
    # round(λ_strong - λ_weak). Addresses the residual case where modal "2-0" wins
    # on EV by a hair over "3-0" but a blowout is the more realistic outcome.
    mismatch_pick_min_dominant: float = 0.75
    mismatch_pick_ev_tolerance: float = 0.05

    # Jornada-3 qualification incentive. Once J1+J2 are played the group table
    # is known; a team whose top-2 finish is already mathematically locked
    # tends to rotate its XI for the dead-rubber final group match. This
    # multiplier damps such a team's expected goals. Heuristic prior — not
    # backtested (no per-match motivation dataset exists) — kept mild on purpose.
    qual_rotation_lambda_mult: float = 0.90


@dataclass(frozen=True)
class RunConfig:
    rules: QuinielaRules = field(default_factory=QuinielaRules)
    model: ModelConfig = field(default_factory=ModelConfig)
    seed: int = 20260611


DEFAULT_CONFIG = RunConfig()


def load_config() -> RunConfig:
    """Hook to load config overrides from disk later. Returns defaults for now."""
    return DEFAULT_CONFIG
