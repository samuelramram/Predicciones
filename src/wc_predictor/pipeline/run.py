"""End-to-end pipeline orchestrator — one command to refresh and produce picks.

This is the command the user runs before each round deadline during the World Cup:

    python -m wc_predictor.pipeline.run --round md1
    python -m wc_predictor.pipeline.run --round round_of_32 --skip-fetch

Stages (each is an isolated subprocess so a failure stops the run cleanly):
  1. ingest.martj42      — refetch latest international results (new scores).
  2. ingest.openfootball — refetch WC2026 fixtures (resolved bracket + scores).
  3. pipeline.fit_elo    — replay Elo over the updated history.
  4. pipeline.fit_model  — refit Poisson + Dixon-Coles on the updated history.
  5. pipeline.generate_picks --round R — emit picks for the requested round.

`--skip-fetch` skips stages 1-2 (use when offline or re-running without new data).
The fetch stages are the only ones that touch the network; everything else is
deterministic given the data in data/.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime


STAGES_FETCH = [
    (["-m", "wc_predictor.ingest.martj42", "--bootstrap", "--refetch"],
     "Ingesta martj42 (resultados internacionales)"),
    (["-m", "wc_predictor.ingest.openfootball", "--bootstrap", "--refetch"],
     "Ingesta openfootball (fixtures WC2026 + bracket)"),
]
STAGES_MODEL = [
    (["-m", "wc_predictor.pipeline.fit_elo"], "Replay Elo internacional"),
    (["-m", "wc_predictor.pipeline.fit_model"], "Fit Poisson + Dixon-Coles"),
]


def _run_stage(args: list[str], description: str) -> bool:
    print(f"\n{'='*70}\n>>> {description}\n{'='*70}")
    start = time.time()
    result = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    elapsed = time.time() - start
    # Echo the last few lines of stdout for visibility
    for line in result.stdout.splitlines()[-8:]:
        print(f"  {line}")
    if result.returncode != 0:
        print(f"  [ERROR] stage failed (exit {result.returncode}) after {elapsed:.1f}s")
        if result.stderr:
            print("  STDERR:")
            for line in result.stderr.splitlines()[-15:]:
                print(f"    {line}")
        return False
    print(f"  [OK] {elapsed:.1f}s")
    return True


def main():
    parser = argparse.ArgumentParser(description="WC2026 predictor — full pipeline orchestrator.")
    parser.add_argument("--round", default="all",
                        help="Round to generate picks for (all | group_stage | md1..md17 "
                             "| round_of_32 | round_of_16 | quarter_final | semi_final "
                             "| third_place | final).")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip the network ingest stages; use existing data/raw/.")
    args = parser.parse_args()

    started = datetime.utcnow()
    print(f"{'#'*70}")
    print(f"# WC2026 PREDICTOR — PIPELINE RUN")
    print(f"# Started: {started.isoformat()}Z   Round: {args.round}   Skip fetch: {args.skip_fetch}")
    print(f"{'#'*70}")

    stages: list[tuple[list[str], str]] = []
    if not args.skip_fetch:
        stages.extend(STAGES_FETCH)
    stages.extend(STAGES_MODEL)
    stages.append((
        ["-m", "wc_predictor.pipeline.generate_picks", "--round", args.round],
        f"Generación de picks (ronda: {args.round})",
    ))

    for stage_args, description in stages:
        if not _run_stage(stage_args, description):
            print(f"\n{'#'*70}\n# PIPELINE ABORTADO en: {description}\n{'#'*70}")
            sys.exit(1)

    elapsed = (datetime.utcnow() - started).total_seconds()
    print(f"\n{'#'*70}")
    print(f"# PIPELINE COMPLETADO en {elapsed:.1f}s")
    print(f"# Picks en outputs/picks_{args.round}.{{csv,json,md}}")
    print(f"{'#'*70}")


if __name__ == "__main__":
    main()
