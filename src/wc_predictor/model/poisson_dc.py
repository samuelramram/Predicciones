"""Bivariate Poisson with Dixon-Coles correction.

Phase 2 implementation will fit per-team attack/defense strengths via MLE on the full
international match history (down-weighted by recency, time half-life ~2 years), with
a separate home/neutral term:

    log(lambda_home) = mu + alpha_home + beta_away + gamma * I(home_advantage)
    log(lambda_away) = mu + alpha_away + beta_home

For now, this file just sketches the public API used by the rest of the pipeline.
The score-matrix builder and EV optimizer already live in `scoring.quiniela`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TeamStrength:
    team: str
    attack: float
    defense: float
    confederation: str | None = None


def fit_dc_model(matches, cfg, half_life_years: float = 2.0):
    """TODO Phase 2: weighted MLE fit. Returns dict[team -> TeamStrength] + mu (global)."""
    raise NotImplementedError("Poisson + DC MLE fit pending.")


def predict_lambdas(home: TeamStrength, away: TeamStrength, mu: float, home_advantage: float = 0.0) -> tuple[float, float]:
    """Returns (lambda_home, lambda_away) for a single fixture given team strengths."""
    import math

    lh = math.exp(mu + home.attack - away.defense + home_advantage)
    la = math.exp(mu + away.attack - home.defense)
    return lh, la
