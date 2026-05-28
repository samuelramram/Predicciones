"""Match-context adjustments specific to the World Cup setting.

These multiply or shift lambdas AFTER the base Poisson + Elo pull but BEFORE the
score-matrix is built.

Adjustments implemented:
- `apply_wc_lambdas`: WC-wide goal inflation + skill-gap (mismatch) inflation.
- `apply_context_adjustments`: host advantage (USA/Mexico/Canada), altitude
  penalty (Estadio Azteca 2240 m), travel fatigue, and squad availability.

Layering / order (single source of truth so the score matrix is built on one
consistent λ pair):
    raw fit → predict_lambdas(host=…)  # generic home gamma
            → apply_wc_lambdas         # WC goal inflation + skill-gap
            → apply_context_adjustments# host nation, altitude, travel, injuries

`apply_context_adjustments` is a no-op for fields it has no data for (travel km
and unavailable-starter % default to 0), so it degrades gracefully before those
feeds exist.
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


def _host_multiplier(country: str, cfg: ModelConfig) -> float:
    """Extra WC-host boost for the host nation, layered on top of the generic
    gamma the Poisson fit already applied. 1.0 (no-op) for any non-host country."""
    return {
        "United States": cfg.host_advantage_usa,
        "Mexico": cfg.host_advantage_mexico,
        "Canada": cfg.host_advantage_canada,
    }.get(country, 1.0)


def apply_context_adjustments(
    lambda_home: float,
    lambda_away: float,
    ctx: MatchContext,
    cfg: ModelConfig,
) -> tuple[float, float]:
    """Apply host advantage, altitude, travel, and squad-availability λ shifts.

    All multiplicative, all single-pass. Each layer is a no-op when its data is
    absent (neutral venue / 0 km travelled / 0% starters out), so this is safe to
    call on every fixture.

    Host advantage
        If the venue country is one of the three hosts AND that host is playing,
        its λ is multiplied by the host-specific factor (`host_advantage_*`). This
        is the WC-host boost *beyond* the generic home gamma already in λ.

    Altitude
        The non-acclimatized side loses `altitude_penalty_per_1000m` of λ per
        1000 m. The host (or, at a neutral venue, neither team is acclimatized so
        both are penalized) is treated as acclimatized. Only Estadio Azteca
        (2240 m) is high enough to matter; sea-level venues are ≈0 by construction.

    Travel
        Each side loses `travel_penalty_per_1000km` of λ per 1000 km since its
        previous fixture (no-op until a travel feed populates the ctx fields).

    Squad availability
        Each side's λ is scaled by (1 - unavailable_starter_pct), the penalty
        capped at `injury_max_lambda_penalty` so a withdrawal wave can't zero a
        team out (the Liga MX Chivas-J6 over-penalty bug).
    """
    lh, la = lambda_home, lambda_away

    # --- Host advantage (host nation only) ---
    host_mult = _host_multiplier(ctx.venue_country, cfg)
    if host_mult != 1.0:
        if ctx.venue_country == ctx.home:
            lh *= host_mult
        elif ctx.venue_country == ctx.away:
            la *= host_mult

    # --- Altitude: penalize whoever is NOT acclimatized to the venue ---
    if ctx.venue_altitude_m > 0 and cfg.altitude_penalty_per_1000m > 0:
        alt_factor = max(
            1.0 - cfg.altitude_penalty_per_1000m * (ctx.venue_altitude_m / 1000.0),
            0.5,
        )
        host_is_home = ctx.venue_country == ctx.home
        host_is_away = ctx.venue_country == ctx.away
        if host_is_home:            # away side is the visitor at altitude
            la *= alt_factor
        elif host_is_away:          # home side is the visitor at altitude
            lh *= alt_factor
        else:                       # neutral high-altitude venue: both unacclimatized
            lh *= alt_factor
            la *= alt_factor

    # --- Travel fatigue (no-op when km == 0) ---
    if cfg.travel_penalty_per_1000km > 0:
        lh *= max(1.0 - cfg.travel_penalty_per_1000km * (ctx.home_prev_km / 1000.0), 0.5)
        la *= max(1.0 - cfg.travel_penalty_per_1000km * (ctx.away_prev_km / 1000.0), 0.5)

    # --- Squad availability (capped; no-op when 0%) ---
    cap = cfg.injury_max_lambda_penalty
    lh *= 1.0 - min(max(ctx.home_unavail_starter_pct, 0.0), cap)
    la *= 1.0 - min(max(ctx.away_unavail_starter_pct, 0.0), cap)

    return lh, la


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
