"""Historical international match results.

Output: `data/historical/international_matches.csv` with columns:
    date, home, away, home_score, away_score, neutral, tournament, stage, venue

Coverage target: 2014-01-01 → today. ~10k matches across friendlies, qualifiers,
WC, Euro, Copa America, AFC Asian Cup, Africa Cup of Nations, Gold Cup, Nations League.

Primary source: github.com/martj42/international_results (CC0 license, daily updated).
This is the cleanest dataset for cross-confederation international football and is the
backbone of most public Elo implementations.

Fallback / enrichment: FBref tournament pages for xG when available (only friendlies
and qualifiers in major confederations have xG; WC matches do).
"""
from __future__ import annotations

from pathlib import Path

from wc_predictor.config import HISTORICAL_DIR


def bootstrap_international_results(out_path: Path | None = None) -> None:
    """TODO Phase 1: pull
        https://raw.githubusercontent.com/martj42/international_results/master/results.csv
    and join shootouts + goalscorers + neutral-venue flags from companion CSVs in the
    same repo. Filter to date >= 2014-01-01.
    """
    raise NotImplementedError("Bootstrap historical matches pending.")


def load_international_matches(path: Path | None = None):
    import pandas as pd

    src = path or (HISTORICAL_DIR / "international_matches.csv")
    if not src.exists():
        raise FileNotFoundError(f"International matches dataset missing: {src}.")
    return pd.read_csv(src, parse_dates=["date"])
