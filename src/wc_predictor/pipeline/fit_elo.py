"""Pipeline step: replay the full martj42 history → current Elo per team + trajectories.

Run from repo root:

    python -m wc_predictor.pipeline.fit_elo

Reads:
    data/raw/international_results.csv      (canonical raw, not the filtered training set,
                                             because Elo benefits from full history depth)
    data/wc2026/teams.json                  (to know which teams to track in detail)

Writes:
    data/historical/elo_current.json        all teams, sorted by Elo desc
    data/wc2026/elo_snapshot.json           just the 48 WC2026 teams
    data/wc2026/elo_trajectory.json         per-team trajectory (last 30 matches each)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from wc_predictor.config import (
    DEFAULT_CONFIG,
    HISTORICAL_DIR,
    RAW_DIR,
    WC_DIR,
)
from wc_predictor.ratings.elo import replay_history


def _load_raw_matches(src: Path) -> list[dict]:
    """Read martj42 results.csv, drop unplayed rows, return chronologically-sorted list."""
    rows = []
    with src.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["home_score"] in ("NA", "", None) or row["away_score"] in ("NA", "", None):
                continue
            rows.append({
                "date": row["date"],
                "home": row["home_team"],
                "away": row["away_team"],
                "home_score": int(row["home_score"]),
                "away_score": int(row["away_score"]),
                "neutral": row["neutral"].strip().upper() in {"TRUE", "T", "1", "YES"},
                "tournament": row["tournament"],
            })
    rows.sort(key=lambda r: r["date"])
    return rows


def _load_wc_teams() -> set[str]:
    with (WC_DIR / "teams.json").open(encoding="utf-8") as f:
        teams = json.load(f)
    return {t for group in teams["groups"].values() for t in group}


def main():
    raw_src = RAW_DIR / "international_results.csv"
    if not raw_src.exists():
        raise SystemExit(
            f"Missing {raw_src}. Run `python -m wc_predictor.ingest.martj42 --bootstrap` first."
        )

    print(f"Loading raw matches from {raw_src} ...")
    matches = _load_raw_matches(raw_src)
    print(f"  {len(matches)} played international matches")

    wc_teams = _load_wc_teams()
    print(f"  tracking {len(wc_teams)} WC2026 teams")

    print(f"Running Elo replay (K_friendly={DEFAULT_CONFIG.model.elo_k_friendly}, "
          f"K_qualifier={DEFAULT_CONFIG.model.elo_k_qualifier}, "
          f"K_tournament={DEFAULT_CONFIG.model.elo_k_tournament}, "
          f"K_wc_ko={DEFAULT_CONFIG.model.elo_k_wc_knockout}, "
          f"home_bonus={DEFAULT_CONFIG.model.elo_home_bonus})...")
    elos, trajectories = replay_history(matches, DEFAULT_CONFIG.model, track_teams=wc_teams)
    print(f"  computed Elo for {len(elos)} distinct teams")

    last_date = matches[-1]["date"] if matches else "n/a"

    # Write all teams sorted by Elo
    all_dst = HISTORICAL_DIR / "elo_current.json"
    sorted_elos = [{"team": t, "elo": round(e, 2)} for t, e in sorted(elos.items(), key=lambda x: -x[1])]
    with all_dst.open("w", encoding="utf-8") as f:
        json.dump({
            "as_of": last_date,
            "params": {
                "k_friendly": DEFAULT_CONFIG.model.elo_k_friendly,
                "k_qualifier": DEFAULT_CONFIG.model.elo_k_qualifier,
                "k_tournament": DEFAULT_CONFIG.model.elo_k_tournament,
                "k_wc_knockout": DEFAULT_CONFIG.model.elo_k_wc_knockout,
                "home_bonus": DEFAULT_CONFIG.model.elo_home_bonus,
            },
            "teams": sorted_elos,
        }, f, indent=2, ensure_ascii=False)
    print(f"  wrote {all_dst} ({len(sorted_elos)} teams)")

    # WC snapshot: ranked subset of WC2026 teams
    wc_dst = WC_DIR / "elo_snapshot.json"
    wc_elos = [
        {"team": t, "elo": round(elos.get(t, 1500.0), 2)}
        for t in sorted(wc_teams, key=lambda x: -elos.get(x, 1500.0))
    ]
    with wc_dst.open("w", encoding="utf-8") as f:
        json.dump({"as_of": last_date, "teams": wc_elos}, f, indent=2, ensure_ascii=False)
    print(f"  wrote {wc_dst} ({len(wc_elos)} WC2026 teams)")

    # Trajectory: last 30 matches per WC team (keeps file size reasonable)
    traj_dst = WC_DIR / "elo_trajectory.json"
    trimmed = {t: traj[-30:] for t, traj in trajectories.items()}
    with traj_dst.open("w", encoding="utf-8") as f:
        json.dump({"as_of": last_date, "last_n_matches": 30, "trajectories": trimmed},
                  f, indent=2, ensure_ascii=False)
    print(f"  wrote {traj_dst}")

    # Print top-20 and bottom-5 of WC field for sanity
    print("\nTop 20 (Elo) in WC2026 field:")
    for i, row in enumerate(wc_elos[:20], 1):
        print(f"  {i:2d}. {row['team']:<28} {row['elo']:.0f}")
    print("\nBottom 5 (Elo) in WC2026 field:")
    for row in wc_elos[-5:]:
        print(f"     {row['team']:<28} {row['elo']:.0f}")


if __name__ == "__main__":
    main()
