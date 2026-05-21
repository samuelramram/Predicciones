"""Ingest the martj42/international_results dataset → historical training set.

Source: https://github.com/martj42/international_results (CC0). ~49k rows since 1872,
updated daily. We filter to `>= 2014-01-01` (recency cutoff for model fitting).

For WC 2026 *fixtures* (the upcoming 104 matches), use `ingest.openfootball` instead —
it has official group letters and the full bracket placeholder structure. martj42
populates score columns post-match, so once group matches are played they appear
here and can be merged back.

Run from the repo root:

    python -m wc_predictor.ingest.martj42 --bootstrap
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import urllib.request
from datetime import datetime
from pathlib import Path

from wc_predictor.config import HISTORICAL_DIR, RAW_DIR

MARTJ42_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
HISTORICAL_TRAINING_START = datetime(2014, 1, 1).date()


def _truthy(value: str) -> bool:
    return value.strip().upper() in {"TRUE", "T", "1", "YES"}


def _match_id(date_str: str, home: str, away: str) -> str:
    """Deterministic short id. Same (date, home, away) → same id across runs and sources."""
    key = f"{date_str}|{home}|{away}".encode("utf-8")
    return "m_" + hashlib.sha1(key).hexdigest()[:10]


def fetch_raw(dst: Path | None = None) -> Path:
    """Download latest results.csv into data/raw/. Overwrites."""
    dst = dst or (RAW_DIR / "international_results.csv")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MARTJ42_URL) as response, dst.open("wb") as f:
        f.write(response.read())
    return dst


def _read_rows(src: Path) -> list[dict]:
    with src.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_historical_training_set(rows: list[dict], dst: Path) -> int:
    """Filter to played matches with date >= cutoff and write canonical CSV."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "match_id", "date", "home", "away", "home_score", "away_score",
        "neutral", "tournament", "city", "country",
    ]
    count = 0
    with dst.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            if row["home_score"] in ("NA", "", None) or row["away_score"] in ("NA", "", None):
                continue
            d = datetime.fromisoformat(row["date"]).date()
            if d < HISTORICAL_TRAINING_START:
                continue
            writer.writerow({
                "match_id": _match_id(row["date"], row["home_team"], row["away_team"]),
                "date": row["date"],
                "home": row["home_team"],
                "away": row["away_team"],
                "home_score": int(row["home_score"]),
                "away_score": int(row["away_score"]),
                "neutral": _truthy(row["neutral"]),
                "tournament": row["tournament"],
                "city": row["city"],
                "country": row["country"],
            })
            count += 1
    return count


def lookup_score(rows: list[dict], date_str: str, home: str, away: str) -> tuple[int, int] | None:
    """Find a played match by exact (date, home, away). Used to merge scores into
    the openfootball fixture list after results come in."""
    for row in rows:
        if (
            row["date"] == date_str
            and row["home_team"] == home
            and row["away_team"] == away
            and row["home_score"] not in ("NA", "", None)
        ):
            return int(row["home_score"]), int(row["away_score"])
    return None


def bootstrap(src: Path | None = None, refetch: bool = False) -> dict:
    src = src or (RAW_DIR / "international_results.csv")
    if refetch or not src.exists():
        print(f"Fetching {MARTJ42_URL} ...")
        src = fetch_raw(src)

    rows = _read_rows(src)
    print(f"Read {len(rows)} rows from {src}")

    historical_dst = HISTORICAL_DIR / "international_matches.csv"
    n = write_historical_training_set(rows, historical_dst)
    print(f"Wrote {n} historical matches >= {HISTORICAL_TRAINING_START} to {historical_dst}")

    return {"historical_rows": n}


def main():
    parser = argparse.ArgumentParser(description="Bootstrap historical training set from martj42.")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--refetch", action="store_true")
    args = parser.parse_args()

    if not args.bootstrap:
        parser.error("Pass --bootstrap to run.")
    print("Done.", bootstrap(refetch=args.refetch))


if __name__ == "__main__":
    main()
