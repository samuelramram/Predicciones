"""End-to-end pipeline orchestrator — one command to refresh and produce picks.

This is the command the user runs before each round deadline during the World Cup:

    python -m wc_predictor.pipeline.run --round md1
    python -m wc_predictor.pipeline.run --round round_of_32 --skip-fetch

Stages (each is an isolated subprocess so a failure stops the run cleanly):
  1. ingest.martj42      — refetch latest international results (new scores).
  2. ingest.openfootball — refetch WC2026 fixtures (resolved bracket + scores).
  3. ingest.fetch_odds   — fetch bookmaker odds (OPTIONAL: needs THE_ODDS_API_KEY;
                           a failure here only warns — the model degrades to the
                           backtested 2-way Poisson/Elo blend).
  4. pipeline.fit_elo    — replay Elo over the updated history.
  5. pipeline.fit_model  — refit Poisson + Dixon-Coles on the updated history.
  6. pipeline.generate_picks --round R — emit picks for the requested round.

`--skip-fetch` skips stages 1-3 (use when offline or re-running without new data).
The fetch stages are the only ones that touch the network; everything else is
deterministic given the data in data/.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime


# Each stage is (args, description, optional). An optional stage that fails only
# prints a warning and the pipeline carries on — used for the odds fetch, which
# needs an API key and whose absence the model handles gracefully.
STAGES_FETCH = [
    (["-m", "wc_predictor.ingest.martj42", "--bootstrap", "--refetch"],
     "Ingesta martj42 (resultados internacionales)", False),
    (["-m", "wc_predictor.ingest.openfootball", "--bootstrap", "--refetch"],
     "Ingesta openfootball (fixtures WC2026 + bracket)", False),
    (["-m", "wc_predictor.ingest.fetch_odds"],
     "Ingesta de odds de bookmakers (opcional — requiere THE_ODDS_API_KEY)", True),
]
STAGES_MODEL = [
    (["-m", "wc_predictor.pipeline.fit_elo"], "Replay Elo internacional", False),
    (["-m", "wc_predictor.pipeline.fit_model"], "Fit Poisson + Dixon-Coles", False),
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
                        help="Round to generate picks for (all | group_stage | j1..j3 "
                             "| md1..md17 | round_of_32 | round_of_16 | quarter_final "
                             "| semi_final | third_place | final).")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip the network ingest stages; use existing data/raw/.")
    args = parser.parse_args()

    started = datetime.utcnow()
    print(f"{'#'*70}")
    print(f"# WC2026 PREDICTOR — PIPELINE RUN")
    print(f"# Started: {started.isoformat()}Z   Round: {args.round}   Skip fetch: {args.skip_fetch}")
    print(f"{'#'*70}")

    stages: list[tuple[list[str], str, bool]] = []
    if not args.skip_fetch:
        stages.extend(STAGES_FETCH)
    stages.extend(STAGES_MODEL)
    stages.append((
        ["-m", "wc_predictor.pipeline.generate_picks", "--round", args.round],
        f"Generación de picks (ronda: {args.round})",
        False,
    ))

    for stage_args, description, optional in stages:
        if not _run_stage(stage_args, description):
            if optional:
                print("  [AVISO] etapa opcional falló — se continúa sin ella "
                      "(el modelo cae al blend 70/30 Poisson/Elo).")
                continue
            print(f"\n{'#'*70}\n# PIPELINE ABORTADO en: {description}\n{'#'*70}")
            sys.exit(1)

    elapsed = (datetime.utcnow() - started).total_seconds()
    print(f"\n{'#'*70}")
    print(f"# PIPELINE COMPLETADO en {elapsed:.1f}s")
    print(f"# Picks en outputs/picks_{args.round}.{{csv,json,md}}")
    print(f"{'#'*70}")


if __name__ == "__main__":
    main()
