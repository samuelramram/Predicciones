"""CLI: refresh ALL model inputs to the freshest available state, then refit.

Picks are only as fresh as the data behind them. `generate_picks` reads
precomputed artifacts (team_strengths.json, elo_current.json); it does NOT
refit. This command refreshes those artifacts end to end so a pick run reflects
the latest international results — including friendlies, which feed both the Elo
(K=20) and the Poisson + Dixon-Coles fit.

    python -m wc_predictor.pipeline.refresh_data

Steps (each best-effort — a failure prints a warning and falls back to the data
already on disk, never aborts):
  1. Refetch martj42 international_results.csv (upstream, updated daily) and
     rebuild the filtered training set.
  2. Recompute Elo (fit_elo)   → elo_current.json, elo_snapshot.json, trajectories.
  3. Refit Poisson + DC (fit_model) → team_strengths.json.

Run it right before generate_picks. If the network is down or the source is
unreachable the refetch is skipped and the refit runs on the most recent CSV
already on disk, so the command still produces artifacts from whatever data is
available. Mirrors the degrade-don't-abort contract of `snapshot_odds`.
"""
from __future__ import annotations

from wc_predictor.config import HISTORICAL_DIR, RAW_DIR
from wc_predictor.ingest.martj42 import bootstrap
from wc_predictor.pipeline.fit_elo import main as fit_elo_main
from wc_predictor.pipeline.fit_model import main as fit_model_main


def _step_refetch() -> None:
    """Refetch upstream results and rebuild the training set. Falls back to the
    saved raw CSV (and, failing that, the existing training set) on any error."""
    try:
        result = bootstrap(refetch=True)
        print(f"  [1/3] refetched upstream → {result['historical_rows']} historical matches")
        return
    except Exception as e:  # network down, source moved, disk error...
        print(f"  [1/3] WARNING: refetch failed ({e}); trying saved raw CSV")

    raw = RAW_DIR / "international_results.csv"
    if not raw.exists():
        print(f"  [1/3] no saved raw CSV at {raw}; keeping committed "
              f"{HISTORICAL_DIR / 'international_matches.csv'}")
        return
    try:
        result = bootstrap(refetch=False)
        print(f"  [1/3] rebuilt training set from saved raw → "
              f"{result['historical_rows']} matches")
    except Exception as e:
        print(f"  [1/3] WARNING: could not rebuild training set ({e}); "
              f"keeping committed artifacts")


def _step_fit_elo() -> None:
    try:
        fit_elo_main()
        print("  [2/3] Elo recomputed")
    except SystemExit as e:
        print(f"  [2/3] WARNING: fit_elo skipped ({e}); keeping committed elo_current.json")
    except Exception as e:
        print(f"  [2/3] WARNING: fit_elo failed ({e}); keeping committed elo_current.json")


def _step_fit_model() -> None:
    try:
        fit_model_main()
        print("  [3/3] Poisson + DC refit")
    except SystemExit as e:
        print(f"  [3/3] WARNING: fit_model skipped ({e}); keeping committed team_strengths.json")
    except Exception as e:
        print(f"  [3/3] WARNING: fit_model failed ({e}); keeping committed team_strengths.json")


def main() -> None:
    print("Refreshing model inputs (martj42 → Elo → Poisson/DC) ...")
    _step_refetch()
    _step_fit_elo()
    _step_fit_model()
    print("Refresh done. generate_picks will read the updated artifacts.")


if __name__ == "__main__":
    main()
