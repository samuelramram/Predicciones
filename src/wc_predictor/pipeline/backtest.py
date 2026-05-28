"""CLI for backtesting the Poisson+DC model against past World Cups.

Run from repo root:

    python -m wc_predictor.pipeline.backtest

Writes:
    outputs/backtest_wc2018.json
    outputs/backtest_wc2022.json
    outputs/backtest_summary.md
"""
from __future__ import annotations

import csv
import json
from datetime import datetime

from wc_predictor.config import DEFAULT_CONFIG, HISTORICAL_DIR, OUTPUTS_DIR, RAW_DIR
from wc_predictor.model.backtest import run_tournament_backtest


def _load_all_rows() -> list[dict]:
    """Load played matches for the backtest.

    Reads the COMMITTED, canonical training set
    `data/historical/international_matches.csv` (columns home/away/...) so the
    backtest is reproducible from a clean clone — no network re-fetch needed.
    Falls back to the raw martj42 dump (`data/raw/international_results.csv`,
    columns home_team/away_team) only if the canonical file is missing.
    """
    canonical = HISTORICAL_DIR / "international_matches.csv"
    raw = RAW_DIR / "international_results.csv"
    if canonical.exists():
        src, home_col, away_col = canonical, "home", "away"
    elif raw.exists():
        src, home_col, away_col = raw, "home_team", "away_team"
    else:
        raise SystemExit(
            f"Missing {canonical} (and raw fallback {raw}). "
            f"Run `python -m wc_predictor.ingest.martj42 --bootstrap` first."
        )
    rows = []
    with src.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["home_score"] in ("NA", "", None) or row["away_score"] in ("NA", "", None):
                continue
            rows.append({
                "date": row["date"], "home": row[home_col], "away": row[away_col],
                "home_score": int(row["home_score"]), "away_score": int(row["away_score"]),
                "neutral": str(row["neutral"]).strip().lower() in {"true", "t", "1", "yes"},
                "tournament": row["tournament"],
            })
    return rows


def _dump_backtest(b, dst):
    payload = {
        "tournament": b.tournament, "year": b.year,
        "training_cutoff": b.training_cutoff,
        "n_training": b.n_training, "n_matches": b.n_matches,
        "by_strategy": {
            name: {
                "total_points": s.total_points,
                "pts_per_match": round(s.pts_per_match, 3),
                "exact_hits": s.exact_hits,
                "outcome_hits": s.outcome_hits,
                "pick_dist": s.pick_dist,
            }
            for name, s in b.by_strategy.items()
        },
        "by_model_calibration": {
            name: {
                "brier": round(c.brier, 5),
                "log_loss": round(c.log_loss, 5),
                "n": c.n,
            }
            for name, c in b.by_model_calibration.items()
        },
        "per_match": b.per_match,
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _write_summary(backtests, dst):
    rules = DEFAULT_CONFIG.rules
    lines = ["# Backtest del modelo Poisson + Dixon-Coles sobre Mundiales pasados\n"]
    lines.append(f"Generado: {datetime.utcnow().isoformat()}Z  ")
    lines.append(f"Scoring: {rules.points_exact} pts exacto / {rules.points_1x2} pt 1X2 (excluyente={rules.exclusive})\n")
    lines.append("Comparación de 5 estrategias sobre los partidos reales del Mundial. Cada estrategia "
                 "ve los MISMOS lambdas del modelo (Poisson + DC fit con datos PRE-torneo); lo que cambia "
                 "es CÓMO convierte lambdas → pick.\n")

    for b in backtests:
        lines.append(f"\n## {b.tournament} {b.year}")
        lines.append(f"Training cutoff: `{b.training_cutoff}` ({b.n_training} matches)  ")
        lines.append(f"Partidos del torneo: **{b.n_matches}**\n")
        lines.append("| Estrategia | Total pts | Pts/partido | Exactos | Outcome (1X2) | Picks 1/X/2 |")
        lines.append("|---|---:|---:|---:|---:|---|")
        sorted_strats = sorted(b.by_strategy.values(), key=lambda s: -s.total_points)
        for s in sorted_strats:
            star = " ★" if s.strategy == "ev_optimal" else ""
            n = s.n_matches or 1  # guard: a strategy with 0 scored matches
            lines.append(
                f"| `{s.strategy}`{star} | **{s.total_points}** | {s.pts_per_match:.2f} | "
                f"{s.exact_hits}/{s.n_matches} ({100*s.exact_hits/n:.0f}%) | "
                f"{s.outcome_hits}/{s.n_matches} ({100*s.outcome_hits/n:.0f}%) | "
                f"{s.pick_dist['1']}/{s.pick_dist['X']}/{s.pick_dist['2']} |"
            )

    # Calibration table aggregating across tournaments
    if len(backtests) > 1:
        cal_agg: dict[str, dict] = {}
        for b in backtests:
            for name, c in b.by_model_calibration.items():
                a = cal_agg.setdefault(name, {"brier_sum": 0.0, "ll_sum": 0.0, "n": 0})
                a["brier_sum"] += c.brier * c.n
                a["ll_sum"] += c.log_loss * c.n
                a["n"] += c.n
        lines.append("\n## Calibración del modelo (probabilidades 1X2)\n")
        lines.append("Brier y log-loss medidos sobre la marginal P(1)/P(X)/P(2) que produce cada modelo. "
                     "Random uniforme: Brier=0.667, log-loss=1.099. Más bajo = mejor calibrado.\n")
        lines.append("| Modelo | Brier | log-loss | n |")
        lines.append("|---|---:|---:|---:|")
        for name, a in sorted(cal_agg.items(), key=lambda x: x[1]["brier_sum"] / max(x[1]["n"], 1)):
            n = a["n"] or 1
            lines.append(f"| `{name}` | {a['brier_sum']/n:.4f} | {a['ll_sum']/n:.4f} | {a['n']} |")

    # Aggregate across tournaments
    if len(backtests) > 1:
        lines.append("\n## Agregado (todos los Mundiales)\n")
        agg: dict[str, dict[str, int]] = {}
        for b in backtests:
            for name, s in b.by_strategy.items():
                a = agg.setdefault(name, {"total": 0, "n": 0, "exact": 0, "outcome": 0})
                a["total"] += s.total_points
                a["n"] += s.n_matches
                a["exact"] += s.exact_hits
                a["outcome"] += s.outcome_hits
        lines.append("| Estrategia | Total pts | Pts/partido | Exactos | Outcome (1X2) |")
        lines.append("|---|---:|---:|---:|---:|")
        for name, a in sorted(agg.items(), key=lambda x: -x[1]["total"]):
            star = " ★" if name == "ev_optimal" else ""
            n = a["n"] or 1
            lines.append(
                f"| `{name}`{star} | **{a['total']}** | {a['total']/n:.2f} | "
                f"{a['exact']}/{a['n']} ({100*a['exact']/n:.0f}%) | "
                f"{a['outcome']}/{a['n']} ({100*a['outcome']/n:.0f}%) |"
            )

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("Loading raw match history ...")
    rows = _load_all_rows()
    print(f"  {len(rows)} played matches")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    backtests = []
    tournaments = [
        ("FIFA World Cup", 2014, "wc2014"),
        ("FIFA World Cup", 2018, "wc2018"),
        ("FIFA World Cup", 2022, "wc2022"),
        ("UEFA Euro", 2024, "euro2024"),
        ("Copa América", 2024, "copa2024"),
    ]
    for name, year, tag in tournaments:
        try:
            b = run_tournament_backtest(
                rows, name, year,
                DEFAULT_CONFIG.rules, DEFAULT_CONFIG.model,
                training_years=5, verbose=True,
            )
            backtests.append(b)
            _dump_backtest(b, OUTPUTS_DIR / f"backtest_{tag}.json")
            print(f"  → wrote outputs/backtest_{tag}.json")
        except ValueError as e:
            print(f"  SKIP {name} {year}: {e}")

    _write_summary(backtests, OUTPUTS_DIR / "backtest_summary.md")
    print(f"\n→ wrote outputs/backtest_summary.md")


if __name__ == "__main__":
    main()
