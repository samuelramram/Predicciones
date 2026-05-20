"""Top-level pipeline entry: produce picks for a given World Cup round.

Usage (Phase 4):

    python -m wc_predictor.pipeline.generate_picks --round group_stage_md1
    python -m wc_predictor.pipeline.generate_picks --round round_of_32 --as-of 2026-06-30

For each fixture in the round:
    1. Resolve teams (knockouts use bracket state).
    2. Compute lambdas from Poisson+DC, Elo-implied lambdas, odds-implied 1X2.
    3. Apply match-context adjustments (host, altitude, travel, squad).
    4. Blend into final (lambda_home, lambda_away).
    5. Call `scoring.quiniela.optimize_pick` to get the (1X2, exact) pair.
    6. Flag ABSTAIN if EV gap is small.

Writes:
    outputs/picks_{round}_{config_hash}.csv
    outputs/report_{round}_{config_hash}.md
    outputs/fingerprint_{round}_{config_hash}.json
"""
from __future__ import annotations


def main():
    """TODO Phase 4."""
    raise NotImplementedError("Pipeline orchestrator pending.")


if __name__ == "__main__":
    main()
