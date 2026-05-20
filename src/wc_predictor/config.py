"""Hyperparameters and scoring rules for the World Cup 2026 predictor.

Single source of truth. Anything that affects model output goes through here so the
fingerprint hash captures the run reproducibly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
WC_DIR = DATA_DIR / "wc2026"
HISTORICAL_DIR = DATA_DIR / "historical"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = REPO_ROOT / "outputs"


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

    elo_k_friendly: float = 20.0
    elo_k_qualifier: float = 30.0
    elo_k_tournament: float = 40.0
    elo_k_wc_knockout: float = 60.0
    elo_home_bonus: float = 80.0

    blend_elo_weight: float = 0.40
    blend_poisson_weight: float = 0.40
    blend_odds_weight: float = 0.20

    host_advantage_usa: float = 1.10
    host_advantage_mexico: float = 1.18
    host_advantage_canada: float = 1.06
    altitude_penalty_per_1000m: float = 0.04
    travel_penalty_per_1000km: float = 0.015

    ev_abstain_gap: float = 0.02


@dataclass(frozen=True)
class RunConfig:
    rules: QuinielaRules = field(default_factory=QuinielaRules)
    model: ModelConfig = field(default_factory=ModelConfig)
    seed: int = 20260611


DEFAULT_CONFIG = RunConfig()


def load_config() -> RunConfig:
    """Hook to load config overrides from disk later. Returns defaults for now."""
    return DEFAULT_CONFIG
