"""Pipeline step: fit Poisson + Dixon-Coles MLE on the historical training set.

Run from repo root:

    python -m wc_predictor.pipeline.fit_model

Reads:
    data/historical/international_matches.csv      (training set, 2014→)
    data/wc2026/teams.json                         (for sanity prints)

Writes:
    data/processed/team_strengths.json             (fitted params for all teams seen)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, HISTORICAL_DIR, PROCESSED_DIR, WC_DIR
from wc_predictor.model.poisson_dc import fit_dc_model, save_fit


def _load_training_rows(src: Path) -> list[dict]:
    rows: list[dict] = []
    with src.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "date": row["date"],
                "home": row["home"],
                "away": row["away"],
                "home_score": int(row["home_score"]),
                "away_score": int(row["away_score"]),
                "neutral": row["neutral"].strip().lower() in {"true", "t", "1", "yes"},
                "tournament": row["tournament"],
            })
    return rows


def _load_wc_teams() -> set[str]:
    with (WC_DIR / "teams.json").open(encoding="utf-8") as f:
        teams = json.load(f)
    return {t for group in teams["groups"].values() for t in group}


def main():
    src = HISTORICAL_DIR / "international_matches.csv"
    if not src.exists():
        raise SystemExit(
            f"Missing {src}. Run `python -m wc_predictor.ingest.martj42 --bootstrap` first."
        )

    print(f"Loading training set from {src} ...")
    rows = _load_training_rows(src)
    print(f"  {len(rows)} matches")

    print("Fitting Poisson + Dixon-Coles MLE ...")
    fit = fit_dc_model(rows, DEFAULT_CONFIG.model, ridge_lambda=DEFAULT_CONFIG.model.ridge_lambda)
    print(f"  converged={fit.converged}, final NLL={fit.final_neg_log_lik:.1f}")
    print(f"  mu={fit.mu:.3f} (implies league-avg goals ≈ {pow(2.718281828, fit.mu):.2f}/team in neutral)")
    print(f"  gamma={fit.gamma:.3f} (home advantage in log-lambda; e^gamma={pow(2.718281828, fit.gamma):.2f}x)")
    print(f"  rho={fit.rho:.3f} (Dixon-Coles draw inflator)")

    dst = PROCESSED_DIR / "team_strengths.json"
    save_fit(fit, dst, as_of=datetime.utcnow().date().isoformat())
    print(f"  wrote {dst}")

    # Sanity: top-15 attackers and toughest defenses in WC2026 field
    wc_teams = _load_wc_teams()
    attackers = sorted(
        (s for t, s in fit.strengths.items() if t in wc_teams),
        key=lambda s: -s.attack,
    )
    defenders = sorted(
        (s for t, s in fit.strengths.items() if t in wc_teams),
        key=lambda s: -s.defense,
    )
    print("\nTop 15 attack strengths in WC2026 field:")
    for i, s in enumerate(attackers[:15], 1):
        print(f"  {i:2d}. {s.team:<28} attack={s.attack:+.3f}  defense={s.defense:+.3f}  n={s.n_matches}")
    print("\nTop 15 defense strengths (largest = best defense):")
    for i, s in enumerate(defenders[:15], 1):
        print(f"  {i:2d}. {s.team:<28} defense={s.defense:+.3f}  attack={s.attack:+.3f}  n={s.n_matches}")


if __name__ == "__main__":
    main()
