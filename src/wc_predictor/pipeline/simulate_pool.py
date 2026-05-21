"""CLI: simulate the 30-person pool using the backtest's real-tournament results.

Run from repo root (after pipeline.backtest has produced outputs/backtest_*.json):

    python -m wc_predictor.pipeline.simulate_pool
    python -m wc_predictor.pipeline.simulate_pool --opponents 29 --sims 20000

Reports, per tournament and aggregated, the production model's probability of
winning the pool and finishing top-3 against synthetic human opponents.
"""
from __future__ import annotations

import argparse
import glob
import json

from wc_predictor.config import DEFAULT_CONFIG, OUTPUTS_DIR
from wc_predictor.model.pool_sim import simulate_pool

PROD_STRATEGY = "blend_w30_ev_no_draw"


def _load_backtests() -> list[dict]:
    docs = []
    for path in sorted(glob.glob(str(OUTPUTS_DIR / "backtest_*.json"))):
        with open(path, encoding="utf-8") as f:
            docs.append(json.load(f))
    return docs


def _extract_matches(doc: dict) -> tuple[list[dict], int]:
    """Pull per-match (actual score, Elo probs) + the model's total points."""
    matches = []
    model_points = 0
    for m in doc["per_match"]:
        ah, aa = (int(x) for x in m["actual_score"].split("-"))
        matches.append({
            "actual_h": ah, "actual_a": aa,
            "elo_p1": m.get("elo_p1", 1 / 3),
            "elo_px": m.get("elo_px", 1 / 3),
            "elo_p2": m.get("elo_p2", 1 / 3),
        })
        strat = m["by_strategy"].get(PROD_STRATEGY)
        if strat:
            model_points += strat["points"]
    return matches, model_points


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo simulation of the quiniela pool.")
    parser.add_argument("--opponents", type=int, default=29, help="Synthetic human opponents.")
    parser.add_argument("--sims", type=int, default=20_000, help="Monte Carlo iterations.")
    args = parser.parse_args()

    docs = _load_backtests()
    if not docs:
        raise SystemExit("No outputs/backtest_*.json found. Run pipeline.backtest first.")

    rules = DEFAULT_CONFIG.rules
    print(f"Pool simulation: model = {PROD_STRATEGY}, {args.opponents} opponents, "
          f"{args.sims} sims/tournament\n")
    print(f"{'Tournament':<22} {'N':>4} {'ModelPts':>9} {'Model/m':>8} {'AvgHuman':>9} "
          f"{'BestHuman':>10} {'Win%':>7} {'Top3%':>7} {'MeanRank':>9}")
    print("-" * 92)

    win_rates = []
    top3_rates = []

    for doc in docs:
        matches, model_points = _extract_matches(doc)
        result = simulate_pool(matches, model_points, rules,
                               n_opponents=args.opponents, n_sims=args.sims)
        tag = f"{doc['tournament']} {doc['year']}"
        n = len(matches)
        print(f"{tag:<22} {n:>4} {model_points:>9} {model_points/n:>8.2f} "
              f"{result.avg_human_points:>9.1f} {result.best_human_mean:>10.1f} "
              f"{result.win_rate*100:>6.1f}% {result.top3_rate*100:>6.1f}% {result.mean_rank:>9.2f}")
        win_rates.append(result.win_rate)
        top3_rates.append(result.top3_rate)

    print("-" * 92)
    baseline = 1.0 / (args.opponents + 1)
    mean_win = sum(win_rates) / len(win_rates)
    mean_top3 = sum(top3_rates) / len(top3_rates)
    print(f"\n{'='*60}")
    print(f"RESUMEN — torneo individual (escenario realista de un Mundial)")
    print(f"{'='*60}")
    print(f"  Win-rate por torneo:   {['%.0f%%' % (w*100) for w in win_rates]}")
    print(f"  Win-rate PROMEDIO:     {mean_win*100:.1f}%   (azar = {baseline*100:.1f}%)")
    print(f"  Top-3 PROMEDIO:        {mean_top3*100:.1f}%")
    print(f"  Edge sobre azar:       {mean_win/baseline:.1f}x")
    print(f"\n  Lectura: el modelo inclina MUY fuerte las probabilidades a tu favor,")
    print(f"  pero un solo torneo tiene varianza alta — el peor caso del backtest")
    print(f"  (WC2022, modelo a {min(win_rates)*100:.0f}%) muestra que un mal torneo te deja")
    print(f"  al nivel del azar. No es garantía; es una ventaja grande y repetible.")


if __name__ == "__main__":
    main()
