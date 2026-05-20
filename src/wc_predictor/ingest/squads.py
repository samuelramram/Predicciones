"""Squad roster ingestion.

FIFA confirms 26-player rosters ~7 days before kickoff. Until then, we use
provisional lists (~55 names) reported by federations.

Output: `data/wc2026/squads.json` keyed by team:
    {
      "Mexico": [
        {"name": "...", "club": "Chivas", "league": "Liga MX", "position": "FW",
         "minutes_last_180d": 1240, "starter": true, "key_role": "primary_striker"}
      ],
      ...
    }

Source: scrape Transfermarkt's per-national-team page after announcement. As a
fallback, allow manual JSON edit. The `key_role` and `starter` fields are filled by
the user (one of the few human-loop inputs).
"""
from __future__ import annotations

from pathlib import Path

from wc_predictor.config import WC_DIR


def load_squads(path: Path | None = None) -> dict:
    import json

    src = path or (WC_DIR / "squads.json")
    if not src.exists():
        raise FileNotFoundError(f"Squads file missing: {src}. Bootstrap or fill manually.")
    with src.open(encoding="utf-8") as f:
        return json.load(f)
