"""Match-context adjustments specific to the World Cup setting.

These multiply or shift lambdas AFTER the base Poisson + Elo pull but BEFORE the
score-matrix is built.

Adjustments implemented (or pending):
- Host advantage (USA, Mexico, Canada) — only when playing on home soil.
- Altitude penalty — visiting teams underperform at >2000m (Mexico City 2240m,
  Guadalajara 1567m, Monterrey 537m — only CDMX really matters).
- Travel fatigue — km traveled in last 3 days since previous fixture.
- Squad availability — penalize lambdas by % minutes of unavailable starters,
  capped to avoid the Liga MX over-penalty bug we saw with Chivas in J6.
- Tournament fatigue — accumulate over rounds.

This is where the README "improvements" of the Liga MX model lives, generalized for
international play.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MatchContext:
    home: str
    away: str
    venue: str
    venue_country: str
    venue_altitude_m: float
    is_neutral: bool
    home_prev_km: float = 0.0
    away_prev_km: float = 0.0
    home_unavail_starter_pct: float = 0.0
    away_unavail_starter_pct: float = 0.0


def apply_context_adjustments(
    lambda_home: float,
    lambda_away: float,
    ctx: MatchContext,
    cfg,
) -> tuple[float, float]:
    """TODO Phase 3."""
    raise NotImplementedError("Context adjustments pending.")
