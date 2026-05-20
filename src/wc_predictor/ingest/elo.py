"""International team ratings.

Two complementary sources:

1. **World Football Elo** (eloratings.net) — Markov-style updates per match. Good for
   cross-confederation calibration. We snapshot the table weekly and recompute our own
   trajectory via `ratings.elo.update_elo` so the model stays reproducible.

2. **FIFA Men's Ranking** — weaker signal but trivial to fetch. Used as a secondary
   feature, never as primary.

Both are loaded into `data/historical/elo_history.csv` keyed by (team, date).
"""
from __future__ import annotations

from pathlib import Path

from wc_predictor.config import HISTORICAL_DIR


def bootstrap_eloratings_snapshot(out_path: Path | None = None) -> None:
    """TODO Phase 1: scrape https://www.eloratings.net/ current table and per-team
    history pages. Output schema:
        team, date, elo, rank, confederation
    """
    raise NotImplementedError("Elo snapshot scraper pending.")


def load_elo_history(path: Path | None = None):
    """Returns a pandas DataFrame of (team, date, elo, confederation)."""
    import pandas as pd

    src = path or (HISTORICAL_DIR / "elo_history.csv")
    if not src.exists():
        raise FileNotFoundError(f"Elo history missing: {src}.")
    return pd.read_csv(src, parse_dates=["date"])
