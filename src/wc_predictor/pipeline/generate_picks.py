"""Generate picks for the group stage from the fitted Poisson+DC model.

Run from repo root, after fit_model has produced team_strengths.json:

    python -m wc_predictor.pipeline.generate_picks

Reads:
    data/processed/team_strengths.json
    data/wc2026/fixtures.json
    data/wc2026/venues.json

Writes:
    outputs/picks_group_stage.csv          one row per match (for spreadsheets)
    outputs/picks_group_stage.json         richer payload (for the webapp / paste)
    outputs/picks_group_stage.md           human-readable report
    outputs/fingerprint_group_stage.json   reproducibility hash

For each LOCKED fixture (group stage + any resolved knockouts):
  1. Determine neutral flag: not neutral iff venue country == home_team country.
  2. Predict (lambda_home, lambda_away) from fitted strengths.
  3. Run optimize_pick to choose the (1X2, exact) pair maximizing EV.
  4. Flag ABSTAIN if the EV gap to the second-best candidate is small.

Knockout fixtures whose teams aren't decided yet (home_locked=False) are listed
in the report as "pending bracket resolution" and re-run after each round.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, OUTPUTS_DIR, PROCESSED_DIR, WC_DIR
from wc_predictor.model.poisson_dc import load_fit, predict_lambdas
from wc_predictor.scoring.quiniela import optimize_pick
from wc_predictor.utils import config_hash, file_sha256, git_commit, git_dirty


def _load_venues() -> dict:
    with (WC_DIR / "venues.json").open(encoding="utf-8") as f:
        return json.load(f)["venues"]


def _load_fixtures() -> dict:
    with (WC_DIR / "fixtures.json").open(encoding="utf-8") as f:
        return json.load(f)


def _host_role(fixture: dict, venues: dict) -> str | None:
    """Returns 'home', 'away', or None depending on whether the venue's country
    matches the home team, the away team, or neither. Captures the asymmetric WC
    case where openfootball labels the host nation in the AWAY column (e.g.
    "Czech Republic vs Mexico" at Estadio Azteca — host=Mexico=away column)."""
    venue = fixture.get("venue")
    if not venue or venue not in venues:
        return None
    vc = venues[venue]["country"]
    if vc == fixture["home"]:
        return "home"
    if vc == fixture["away"]:
        return "away"
    return None


def predict_match(fixture: dict, fit, venues: dict, rules, mcfg):
    """Return a pick dict for a locked fixture, or None if not predictable yet."""
    if not (fixture["home_locked"] and fixture["away_locked"]):
        return None
    home_name = fixture["home"]
    away_name = fixture["away"]
    if home_name not in fit.strengths or away_name not in fit.strengths:
        return {
            "match_id": fixture["match_id"],
            "error": f"team strengths missing: home={home_name in fit.strengths}, away={away_name in fit.strengths}",
        }

    host = _host_role(fixture, venues)
    lh, la = predict_lambdas(fit.strengths[home_name], fit.strengths[away_name],
                             fit.mu, fit.gamma, host=host)
    pick = optimize_pick(lh, la, rules, mcfg)

    return {
        "match_id": fixture["match_id"],
        "stage": fixture["stage"],
        "group": fixture.get("group"),
        "date": fixture["date"],
        "date_utc": fixture.get("date_utc"),
        "venue": fixture.get("venue"),
        "home": home_name,
        "away": away_name,
        "host": host,
        "lambda_home": round(lh, 3),
        "lambda_away": round(la, 3),
        "p_home_win": round(pick.prob_home_win, 3),
        "p_draw": round(pick.prob_draw, 3),
        "p_away_win": round(pick.prob_away_win, 3),
        "pick_1x2": pick.pick_1x2,
        "pick_exact": pick.pick_exact,
        "p_exact": round(pick.prob_exact, 3),
        "ev": round(pick.ev, 3),
        "ev_gap": round(pick.ev_confidence_gap, 3),
        "abstain": pick.abstain,
        "top_5_scores": [{"score": c["score"], "prob": round(c["prob"], 3)} for c in pick.top_5_by_prob],
    }


def _write_csv(picks: list[dict], dst: Path) -> None:
    cols = ["date", "stage", "group", "home", "away", "venue",
            "pick_1x2", "pick_exact", "ev", "ev_gap", "abstain",
            "p_home_win", "p_draw", "p_away_win", "p_exact",
            "lambda_home", "lambda_away", "match_id"]
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in picks:
            w.writerow(p)


def _write_markdown(picks: list[dict], pending: list[dict], rules, mcfg, dst: Path) -> None:
    lines = ["# Picks — Mundial 2026 (fase de grupos)\n"]
    lines.append(f"Generado: {datetime.utcnow().isoformat()}Z  ")
    lines.append(f"Scoring: {rules.points_exact} pts exacto / {rules.points_1x2} pt 1X2 (excluyente={rules.exclusive})\n")
    lines.append(f"Modelo: Poisson + Dixon-Coles (ρ={mcfg.dc_rho}), grilla adaptativa, optimizer EV.\n")

    # Sumary numbers
    total_ev = sum(p["ev"] for p in picks)
    abstain_count = sum(1 for p in picks if p["abstain"])
    lines.append(f"**EV total esperado:** {total_ev:.2f} puntos sobre {len(picks)} partidos "
                 f"(max teórico = {len(picks) * rules.points_exact}).\n")
    lines.append(f"**Picks con flag ABSTAIN (gap < {mcfg.ev_abstain_gap}):** {abstain_count}\n")

    # Group by group letter
    by_group: dict[str, list[dict]] = {}
    for p in picks:
        by_group.setdefault(p.get("group") or "_", []).append(p)
    for g in sorted(by_group):
        lines.append(f"\n## Grupo {g}\n")
        lines.append("| Fecha | Partido | Pick | EV | P(1) | P(X) | P(2) | λ home | λ away | Abstain |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|:-:|")
        for p in sorted(by_group[g], key=lambda x: x["date"]):
            star = "★" if p["abstain"] else ""
            lines.append(
                f"| {p['date']} | {p['home']} vs {p['away']} | **{p['pick_1x2']}** ({p['pick_exact']}) | "
                f"{p['ev']:.2f} | {p['p_home_win']:.2f} | {p['p_draw']:.2f} | {p['p_away_win']:.2f} | "
                f"{p['lambda_home']:.2f} | {p['lambda_away']:.2f} | {star} |"
            )

    if pending:
        lines.append(f"\n## Pendientes ({len(pending)} partidos de eliminatorias)\n")
        lines.append("Se predecirán después de la fase de grupos cuando se resuelvan los placeholders.\n")
        lines.append("| Fecha | Stage | Placeholder home | Placeholder away | Venue |")
        lines.append("|---|---|---|---|---|")
        for p in pending:
            lines.append(
                f"| {p['date']} | {p['stage']} | {p['home_placeholder']} | {p['away_placeholder']} | {p.get('venue', '?')} |"
            )

    dst.write_text("\n".join(lines), encoding="utf-8")


def main():
    fit_src = PROCESSED_DIR / "team_strengths.json"
    if not fit_src.exists():
        raise SystemExit(
            f"Missing {fit_src}. Run `python -m wc_predictor.pipeline.fit_model` first."
        )

    print(f"Loading fit from {fit_src} ...")
    fit = load_fit(fit_src)
    print(f"  mu={fit.mu:.3f}  gamma={fit.gamma:.3f}  rho={fit.rho:.3f}  "
          f"({fit.n_teams} teams, {fit.n_matches} matches)")

    venues = _load_venues()
    fixtures_doc = _load_fixtures()
    print(f"Loaded {len(fixtures_doc['matches'])} fixtures, {len(venues)} venues")

    rules = DEFAULT_CONFIG.rules
    mcfg = DEFAULT_CONFIG.model

    picks: list[dict] = []
    pending: list[dict] = []
    errors: list[dict] = []

    for fixture in fixtures_doc["matches"]:
        result = predict_match(fixture, fit, venues, rules, mcfg)
        if result is None:
            pending.append(fixture)
            continue
        if "error" in result:
            errors.append(result)
            continue
        picks.append(result)

    print(f"  picked {len(picks)} matches, {len(pending)} pending knockout, {len(errors)} errors")
    if errors:
        for e in errors:
            print(f"    ERROR: {e}")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    csv_dst = OUTPUTS_DIR / "picks_group_stage.csv"
    _write_csv(picks, csv_dst)
    print(f"  wrote {csv_dst}")

    json_dst = OUTPUTS_DIR / "picks_group_stage.json"
    with json_dst.open("w", encoding="utf-8") as f:
        json.dump({
            "as_of": datetime.utcnow().isoformat() + "Z",
            "rules": {"points_exact": rules.points_exact, "points_1x2": rules.points_1x2,
                      "exclusive": rules.exclusive},
            "model": {"mu": fit.mu, "gamma": fit.gamma, "rho": fit.rho,
                      "n_teams": fit.n_teams, "n_matches": fit.n_matches},
            "picks": picks,
            "pending_knockouts": [
                {"date": f["date"], "stage": f["stage"],
                 "home_placeholder": f["home_placeholder"], "away_placeholder": f["away_placeholder"],
                 "venue": f.get("venue"), "match_id": f["match_id"]}
                for f in pending
            ],
        }, f, indent=2, ensure_ascii=False)
    print(f"  wrote {json_dst}")

    md_dst = OUTPUTS_DIR / "picks_group_stage.md"
    _write_markdown(picks, pending, rules, mcfg, md_dst)
    print(f"  wrote {md_dst}")

    fp_dst = OUTPUTS_DIR / "fingerprint_group_stage.json"
    with fp_dst.open("w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "git_commit": git_commit(),
            "git_dirty": git_dirty(),
            "config_hash": config_hash(DEFAULT_CONFIG),
            "inputs": {
                str(fit_src.relative_to(fit_src.parent.parent)): file_sha256(fit_src),
                "data/wc2026/fixtures.json": file_sha256(WC_DIR / "fixtures.json"),
                "data/wc2026/venues.json": file_sha256(WC_DIR / "venues.json"),
            },
            "outputs": {
                "picks_group_stage.csv": file_sha256(csv_dst),
                "picks_group_stage.json": file_sha256(json_dst),
                "picks_group_stage.md": file_sha256(md_dst),
            },
            "n_picks": len(picks),
            "n_pending": len(pending),
        }, f, indent=2)
    print(f"  wrote {fp_dst}")

    # Sanity print: most confident, least confident, lowest EV gaps
    by_ev = sorted(picks, key=lambda p: -p["ev"])
    by_gap = sorted(picks, key=lambda p: p["ev_gap"])
    print("\nMOST confident picks (highest EV):")
    for p in by_ev[:5]:
        print(f"  {p['date']} | {p['home']:<20s} vs {p['away']:<20s} → {p['pick_1x2']} ({p['pick_exact']}) EV={p['ev']:.2f}")
    print("\nLEAST confident picks (smallest gap to second-best):")
    for p in by_gap[:5]:
        flag = " ★ABSTAIN" if p["abstain"] else ""
        print(f"  {p['date']} | {p['home']:<20s} vs {p['away']:<20s} → {p['pick_1x2']} ({p['pick_exact']}) "
              f"gap={p['ev_gap']:.3f} EV={p['ev']:.2f}{flag}")


if __name__ == "__main__":
    main()
