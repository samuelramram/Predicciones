"""Backtest the mismatch (skill-gap) inflation against real WC 2018 + 2022 blowouts.

For each hand-picked mismatch fixture, compute the EV-optimal pick under three
configurations:

  baseline   – wc_lambda_inflation only (mismatch_strong_boost=1.0, damp=1.0,
               mismatch_pick_min_dominant=2.0 so the override never fires)
  inflation  – mismatch inflation ON, pick override OFF
  full       – mismatch inflation ON, pick override ON

Then score each pick under the production QuinielaRules (exact=2, 1x2=1,
exclusive) against the real 90-minute score, and report per-config totals.

The 'real' score is the 90-minute result (no ET/penalties), matching the pool's
scoring convention.

Usage:
    PYTHONPATH=src python scripts/backtest_mismatch.py
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, PROCESSED_DIR
from wc_predictor.model.adjustments import apply_wc_lambdas
from wc_predictor.model.poisson_dc import load_fit, predict_lambdas
from wc_predictor.scoring.quiniela import (
    build_score_matrix,
    optimize_pick_from_cells,
    score_actual,
)


# 90-minute results of one-sided WC 2018 + 2022 group-stage matches.
# Excluded: penalty shootouts and ET (we score on 90' only).
BLOWOUTS = [
    # World Cup 2022 (group stage, 90' results)
    ("Spain",    "Costa Rica",   7, 0, "WC22 G3"),
    ("England",  "Iran",         6, 2, "WC22 G2"),
    ("Portugal", "Switzerland",  6, 1, "WC22 R16"),
    ("France",   "Australia",    4, 1, "WC22 G1"),
    ("Brazil",   "South Korea",  4, 1, "WC22 R16"),
    ("Spain",    "Germany",      1, 1, "WC22 G2 (control)"),
    ("Argentina","Saudi Arabia", 1, 2, "WC22 G1 (UPSET — control)"),
    # World Cup 2018
    ("Belgium",  "Tunisia",      5, 2, "WC18 G2"),
    ("Russia",   "Saudi Arabia", 5, 0, "WC18 G1"),
    ("England",  "Panama",       6, 1, "WC18 G2"),
    ("France",   "Croatia",      4, 2, "WC18 Final"),
    ("Brazil",   "Costa Rica",   2, 0, "WC18 G2"),
    ("Germany",  "South Korea",  0, 2, "WC18 G3 (UPSET — control)"),
]


def _pick_under(cfg, fit, home: str, away: str):
    """Return (pick_1x2, pick_exact, lh, la, ev) under the given ModelConfig."""
    if home not in fit.strengths or away not in fit.strengths:
        return None
    lh, la = predict_lambdas(fit.strengths[home], fit.strengths[away],
                             fit.mu, fit.gamma, host=None)
    lh, la = apply_wc_lambdas(lh, la, cfg.model)
    cells, p1, px, p2, mass, gmax = build_score_matrix(lh, la, cfg.model)
    pick = optimize_pick_from_cells(
        cells, p1, px, p2, mass, gmax, cfg.rules, cfg.model,
        forbid_outcomes=("X",),
    )
    return pick.pick_1x2, pick.pick_exact, lh, la, pick.ev


def _make_cfg(mismatch_on: bool, override_on: bool):
    base = DEFAULT_CONFIG
    overrides = {}
    if not mismatch_on:
        overrides.update(
            mismatch_strong_boost=1.0,
            mismatch_weak_damp=1.0,
        )
    if not override_on:
        overrides.update(mismatch_pick_min_dominant=2.0)
    new_model = replace(base.model, **overrides)
    return replace(base, model=new_model)


def main():
    fit_src = PROCESSED_DIR / "team_strengths.json"
    fit = load_fit(fit_src)

    configs = {
        "baseline":  _make_cfg(mismatch_on=False, override_on=False),
        "inflation": _make_cfg(mismatch_on=True,  override_on=False),
        "full":      _make_cfg(mismatch_on=True,  override_on=True),
    }

    totals = {name: 0 for name in configs}
    rows = []

    for home, away, hg, ag, tag in BLOWOUTS:
        row = {"match": f"{home} {hg}-{ag} {away}", "tag": tag}
        for name, cfg in configs.items():
            r = _pick_under(cfg, fit, home, away)
            if r is None:
                row[name] = "—"
                continue
            pk_1x2, pk_exact, lh, la, ev = r
            pts = score_actual(hg, ag, pk_1x2, pk_exact, cfg.rules)
            totals[name] += pts
            if name == "baseline":
                row["lambdas_base"] = f"({lh:.2f}, {la:.2f})"
            if name == "inflation":
                row["lambdas_infl"] = f"({lh:.2f}, {la:.2f})"
            row[name] = f"{pk_exact} ({pts}pt)"
        rows.append(row)

    # Print table
    col_widths = {"match": 32, "tag": 22, "lambdas_base": 14, "lambdas_infl": 14,
                  "baseline": 14, "inflation": 14, "full": 14}
    cols = ["match", "tag", "lambdas_base", "lambdas_infl",
            "baseline", "inflation", "full"]
    header = " | ".join(c.ljust(col_widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(str(row.get(c, "")).ljust(col_widths[c]) for c in cols))
    print("-" * len(header))
    print()
    print(f"{'TOTAL':<32} | " +
          " " * 16 + " | " +
          " " * 14 + " | " + " " * 14 + " | " +
          " | ".join(f"{totals[c]:>3} pts".ljust(col_widths[c]) for c in ("baseline", "inflation", "full")))
    n = len(BLOWOUTS)
    max_pts = n * configs["baseline"].rules.points_exact
    print(f"{n} matches · max possible = {max_pts} pts · "
          f"baseline {totals['baseline']/max_pts*100:.0f}% / "
          f"inflation {totals['inflation']/max_pts*100:.0f}% / "
          f"full {totals['full']/max_pts*100:.0f}%")


if __name__ == "__main__":
    main()
