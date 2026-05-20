"""Best-effort odds ingestion (no paid Odds API).

Strategy:

1. football-data.co.uk publishes historical closing odds per league as CSV — but only
   leagues, not internationals. Used for training the odds→prob calibration only.

2. For live WC 2026 odds, scrape (politely, with delay + UA) one or two public
   aggregators that publish opening lines without auth. If we can't get clean closing
   lines, we drop the odds component of the blend automatically and reweight Elo +
   Poisson.

3. If user upgrades to a paid Odds API later, the loader interface stays the same.

The output of any source is a normalized DataFrame:
    match_id, ts, bookmaker, p_home, p_draw, p_away, overround
We compute the implied probabilities by removing the overround (multiplicative) and
average across bookmakers, weighted by inverse-overround.
"""
from __future__ import annotations


def implied_probs_from_decimal(odds_home: float, odds_draw: float, odds_away: float) -> tuple[float, float, float]:
    """Remove overround multiplicatively. Returns probs that sum to 1."""
    raw = (1 / odds_home, 1 / odds_draw, 1 / odds_away)
    s = sum(raw)
    return (raw[0] / s, raw[1] / s, raw[2] / s)


def fetch_current_odds(match_ids: list[str]) -> dict:
    """TODO Phase 3."""
    raise NotImplementedError("Live odds fetcher pending.")
