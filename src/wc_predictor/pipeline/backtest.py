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

from wc_predictor.config import DEFAULT_CONFIG, OUTPUTS_DIR, RAW_DIR
from wc_predictor.model.backtest import run_tournament_backtest


def _load_all_rows() -> list[dict]:
    src = RAW_DIR / "international_results.csv"
    if not src.exists():
        raise SystemExit(f"Missing {src}. Run ingest.martj42 first.")
    rows = []
    with src.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["home_score"] in ("NA", "", None) or row["away_score"] in ("NA", "", None):
                continue
            rows.append({
                "date": row["date"], "home": row["home_team"], "away": row["away_team"],
                "home_score": int(row["home_score"]), "away_score": int(row["away_score"]),
                "neutral": row["neutral"].strip().lower() in {"true", "t", "1", "yes"},
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
            lines.append(
                f"| `{s.strategy}`{star} | **{s.total_points}** | {s.pts_per_match:.2f} | "
                f"{s.exact_hits}/{s.n_matches} ({100*s.exact_hits/s.n_matches:.0f}%) | "
                f"{s.outcome_hits}/{s.n_matches} ({100*s.outcome_hits/s.n_matches:.0f}%) | "
                f"{s.pick_dist['1']}/{s.pick_dist['X']}/{s.pick_dist['2']} |"
            )

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
            lines.append(
                f"| `{name}`{star} | **{a['total']}** | {a['total']/a['n']:.2f} | "
                f"{a['exact']}/{a['n']} ({100*a['exact']/a['n']:.0f}%) | "
                f"{a['outcome']}/{a['n']} ({100*a['outcome']/a['n']:.0f}%) |"
            )

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("Loading raw match history ...")
    rows = _load_all_rows()
    print(f"  {len(rows)} played matches")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    backtests = []
    for year in (2018, 2022):
        b = run_tournament_backtest(
            rows, "FIFA World Cup", year,
            DEFAULT_CONFIG.rules, DEFAULT_CONFIG.model,
            training_years=5, verbose=True,
        )
        backtests.append(b)
        _dump_backtest(b, OUTPUTS_DIR / f"backtest_wc{year}.json")
        print(f"  → wrote outputs/backtest_wc{year}.json")

    _write_summary(backtests, OUTPUTS_DIR / "backtest_summary.md")
    print(f"\n→ wrote outputs/backtest_summary.md")


if __name__ == "__main__":
    main()
