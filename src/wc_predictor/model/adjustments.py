"""Match-context adjustments specific to the World Cup setting.

These multiply or shift lambdas AFTER the base Poisson + Elo pull but BEFORE the
score-matrix is built.

Adjustments implemented:
- `apply_wc_lambdas`: WC-wide goal inflation + skill-gap (mismatch) inflation.

Adjustments pending (Phase 3):
- Host advantage (USA, Mexico, Canada) — only when playing on home soil.
- Altitude penalty — visiting teams underperform at >2000m (Mexico City 2240m,
  Guadalajara 1567m, Monterrey 537m — only CDMX really matters).
- Travel fatigue — km traveled in last 3 days since previous fixture.
- Squad availability — penalize lambdas by % minutes of unavailable starters,
  capped to avoid the Liga MX over-penalty bug we saw with Chivas in J6.
- Tournament fatigue — accumulate over rounds.
"""
from __future__ import annotations

from dataclasses import dataclass

from wc_predictor.config import ModelConfig


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


def apply_wc_lambdas(lh: float, la: float, mcfg: ModelConfig) -> tuple[float, float]:
    """Apply all WC-specific λ adjustments. Single source of truth for the two
    layers that sit between the raw Poisson fit and the score-matrix builder.

    Layer 1 — uniform WC inflation (`wc_lambda_inflation`): corrects the ~12%
    systematic underestimate vs the historical-intl-matches training set.

    Layer 2 — mismatch inflation: when the predicted λ-ratio crosses
    `mismatch_ratio_threshold`, linearly ramp to saturation (`*_saturation`),
    boosting the stronger side up to `mismatch_strong_boost` and damping the
    weaker side down to `mismatch_weak_damp`. This compensates for the fact
    that weak nations' defensive ratings are anchored to intra-confederation
    games — they look defensively OK because they mostly face other weak sides.

    Both layers are multiplicative; the order is uniform first, mismatch second
    (so the mismatch threshold is computed on already-inflated λ — consistent
    with what feeds the score matrix downstream).
    """
    lh *= mcfg.wc_lambda_inflation
    la *= mcfg.wc_lambda_inflation

    lo, hi = (la, lh) if lh >= la else (lh, la)
    ratio = hi / max(lo, 1e-6)
    if ratio <= mcfg.mismatch_ratio_threshold:
        return lh, la

    span = max(mcfg.mismatch_ratio_saturation - mcfg.mismatch_ratio_threshold, 1e-6)
    t = min((ratio - mcfg.mismatch_ratio_threshold) / span, 1.0)
    boost = 1.0 + (mcfg.mismatch_strong_boost - 1.0) * t
    damp = 1.0 - (1.0 - mcfg.mismatch_weak_damp) * t
    if lh >= la:
        return lh * boost, la * damp
    return lh * damp, la * boost
