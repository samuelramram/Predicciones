"""Generate picks from the fitted model for a chosen round of the tournament.

Run from repo root, after fit_model + fit_elo have produced their artifacts:

    python -m wc_predictor.pipeline.generate_picks                 # all locked matches
    python -m wc_predictor.pipeline.generate_picks --round group_stage
    python -m wc_predictor.pipeline.generate_picks --round md1     # FIFA Matchday 1
    python -m wc_predictor.pipeline.generate_picks --round round_of_32

Reads:
    data/processed/team_strengths.json
    data/wc2026/fixtures.json
    data/wc2026/venues.json
    data/historical/elo_current.json

Writes (suffix = the round label):
    outputs/picks_{round}.csv          one row per match (for spreadsheets)
    outputs/picks_{round}.json         richer payload (for the webapp / paste)
    outputs/picks_{round}.md           human-readable report
    outputs/fingerprint_{round}.json   reproducibility hash

For each LOCKED fixture in the round:
  1. Determine host role from venue country vs the two teams.
  2. Predict (lambda_home, lambda_away) from fitted strengths.
  3. Blend Poisson 1X2 with Elo 1X2 (log-pool, w_elo=0.30).
  4. Run the EV optimizer (forbidding draws) to pick (1X2, exact).
  5. Flag ABSTAIN if the EV gap to the second-best candidate is small.

Knockout fixtures whose teams aren't decided yet (home_locked=False) are listed
as "pending bracket resolution" and re-run after each round.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, HISTORICAL_DIR, OUTPUTS_DIR, PROCESSED_DIR, WC_DIR
from wc_predictor.ingest.odds import load_cached_odds
from wc_predictor.model.blend import blend_three_sources
from wc_predictor.model.poisson_dc import load_fit, predict_lambdas
from wc_predictor.ratings.elo import elo_to_1x2_probs
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells
from wc_predictor.utils import config_hash, file_sha256, git_commit, git_dirty


# Production blend. Without odds: Poisson 70% / Elo 30% (= blend_w30, backtested
# optimal over 275 matches). With odds available, bookmaker probabilities take a
# fixed slice and the Poisson:Elo pair keeps its 70:30 ratio on the remainder.
#
# PROD_W_ODDS is a literature-based default (closing odds are near-efficient;
# market Brier ~0.23 vs our model ~0.58). It is NOT backtested — no free historical
# international odds dataset exists. Tune it later via The Odds API historical
# endpoint once a key is available. The pick is EV-optimal, draws forbidden.
PROD_W_ODDS = 0.55
PROD_POISSON_ELO_SPLIT = 0.70  # Poisson share of the non-odds weight
PROD_FORBID = ("X",)


def _load_venues() -> dict:
    with (WC_DIR / "venues.json").open(encoding="utf-8") as f:
        return json.load(f)["venues"]


def _load_fixtures() -> dict:
    with (WC_DIR / "fixtures.json").open(encoding="utf-8") as f:
        return json.load(f)


KNOCKOUT_STAGES = ("round_of_32", "round_of_16", "quarter_final", "semi_final", "third_place", "final")


def resolve_round_filter(round_spec: str):
    """Return (predicate, label) for a --round argument.

    Accepted values:
      all                          → every fixture (default)
      group_stage                  → all 72 group matches
      md1 .. md17                  → a single FIFA matchday
      round_of_32 / round_of_16 / quarter_final / semi_final / third_place / final
    """
    spec = round_spec.strip().lower()
    if spec in ("all", ""):
        return (lambda fx: True), "all"
    if spec == "group_stage":
        return (lambda fx: fx["stage"] == "group_stage"), "group_stage"
    if spec.startswith("md") and spec[2:].isdigit():
        n = int(spec[2:])
        label_target = f"Matchday {n}"
        return (lambda fx: fx.get("round_label") == label_target), f"md{n}"
    if spec in KNOCKOUT_STAGES:
        return (lambda fx: fx["stage"] == spec), spec
    raise SystemExit(
        f"Unknown --round value: {round_spec!r}. "
        f"Use: all, group_stage, md1..md17, or one of {', '.join(KNOCKOUT_STAGES)}."
    )


def _load_elos() -> dict[str, float]:
    """Load the Elo snapshot computed by `pipeline.fit_elo`. Falls back to 1500.0
    for any missing team."""
    src = HISTORICAL_DIR / "elo_current.json"
    if not src.exists():
        return {}
    with src.open(encoding="utf-8") as f:
        data = json.load(f)
    return {row["team"]: row["elo"] for row in data["teams"]}


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


def _odds_weights(have_odds: bool) -> tuple[float, float, float]:
    """Return (w_poisson, w_elo, w_odds). With odds the Poisson:Elo pair keeps its
    70:30 ratio on the (1 - w_odds) remainder; without odds it collapses to the
    backtested blend_w30 (0.70 / 0.30 / 0.0)."""
    if have_odds:
        rem = 1.0 - PROD_W_ODDS
        return rem * PROD_POISSON_ELO_SPLIT, rem * (1.0 - PROD_POISSON_ELO_SPLIT), PROD_W_ODDS
    return PROD_POISSON_ELO_SPLIT, 1.0 - PROD_POISSON_ELO_SPLIT, 0.0


def predict_match(fixture: dict, fit, venues: dict, elos: dict, odds: dict, rules, mcfg):
    """Return a pick dict for a locked fixture, or None if not predictable yet.

    Pipeline:
      1. Compute (lambda_home, lambda_away) from the Poisson + DC fit.
      2. Compute (P_1, P_X, P_2) from Elo using pre-match ratings + host bonus.
      3. Look up bookmaker odds for this match (if available).
      4. Log-pool Poisson + Elo + Odds 1X2 marginals (odds dropped gracefully
         if not covered → falls back to the backtested 70/30 Poisson/Elo blend).
      5. Rescale the Poisson score-matrix to the blended marginals.
      6. optimize_pick_from_cells with forbid_outcomes=("X",) — never pick draws.
    """
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

    # Elo 1X2 from current snapshot
    r_h = elos.get(home_name, 1500.0)
    r_a = elos.get(away_name, 1500.0)
    home_adv_elo = 0.0
    if host == "home":
        home_adv_elo = mcfg.elo_home_bonus
    elif host == "away":
        home_adv_elo = -mcfg.elo_home_bonus
    elo_p1, elo_px, elo_p2 = elo_to_1x2_probs(r_h, r_a, home_adv_elo)

    # Bookmaker odds for this match, if covered.
    odds_entry = odds.get(f"{home_name}|{away_name}")
    odds_1x2 = None
    if odds_entry:
        odds_1x2 = (odds_entry["p1"], odds_entry["px"], odds_entry["p2"])

    w_poisson, w_elo, w_odds = _odds_weights(odds_1x2 is not None)

    # Poisson + DC cells, then 3-way blend and rescale.
    pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
    cells_b, p1_b, px_b, p2_b = blend_three_sources(
        pcells, (pp1, ppx, pp2), (elo_p1, elo_px, elo_p2), odds_1x2,
        w_poisson=w_poisson, w_elo=w_elo, w_odds=w_odds,
    )
    pick = optimize_pick_from_cells(
        cells_b, p1_b, px_b, p2_b, pmass, pmax, rules, mcfg,
        forbid_outcomes=PROD_FORBID,
    )

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
        "elo_home": round(r_h, 1),
        "elo_away": round(r_a, 1),
        "elo_p1": round(elo_p1, 3),
        "elo_px": round(elo_px, 3),
        "elo_p2": round(elo_p2, 3),
        "odds_p1": round(odds_1x2[0], 3) if odds_1x2 else None,
        "odds_px": round(odds_1x2[1], 3) if odds_1x2 else None,
        "odds_p2": round(odds_1x2[2], 3) if odds_1x2 else None,
        "odds_n_books": odds_entry["n_books"] if odds_entry else 0,
        "blend_weights": {"poisson": round(w_poisson, 3), "elo": round(w_elo, 3),
                          "odds": round(w_odds, 3)},
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


def _write_markdown(picks: list[dict], pending: list[dict], rules, mcfg, dst: Path,
                    round_label: str = "all") -> None:
    lines = [f"# Picks — Mundial 2026 (ronda: {round_label})\n"]
    lines.append(f"Generado: {datetime.utcnow().isoformat()}Z  ")
    lines.append(f"Scoring: {rules.points_exact} pts exacto / {rules.points_1x2} pt 1X2 (excluyente={rules.exclusive})\n")
    lines.append(f"Modelo: Poisson + Dixon-Coles (ρ={mcfg.dc_rho}) blended 30% Elo, optimizer EV sin empates.\n")

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
    parser = argparse.ArgumentParser(description="Generate WC2026 quiniela picks for a round.")
    parser.add_argument("--round", default="all",
                        help="all | group_stage | md1..md17 | round_of_32 | round_of_16 "
                             "| quarter_final | semi_final | third_place | final")
    args = parser.parse_args()
    round_filter, round_label = resolve_round_filter(args.round)

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

    elos = _load_elos()
    if not elos:
        raise SystemExit("Missing data/historical/elo_current.json. Run "
                         "`python -m wc_predictor.pipeline.fit_elo` first.")
    print(f"Loaded Elo for {len(elos)} teams")

    odds = load_cached_odds()
    if odds:
        print(f"Loaded bookmaker odds for {len(odds)} matches "
              f"(3-way blend: {int((1-PROD_W_ODDS)*PROD_POISSON_ELO_SPLIT*100)}% Poisson / "
              f"{int((1-PROD_W_ODDS)*(1-PROD_POISSON_ELO_SPLIT)*100)}% Elo / "
              f"{int(PROD_W_ODDS*100)}% odds)")
    else:
        print("No cached odds (data/raw/odds_the_odds_api.json) — "
              "falling back to 70/30 Poisson/Elo blend. "
              "Run `python -m wc_predictor.ingest.fetch_odds` with THE_ODDS_API_KEY set to enable.")

    print(f"Round filter: {round_label}")

    rules = DEFAULT_CONFIG.rules
    mcfg = DEFAULT_CONFIG.model

    selected = [fx for fx in fixtures_doc["matches"] if round_filter(fx)]
    if not selected:
        raise SystemExit(f"No fixtures match --round {args.round!r}.")
    print(f"  {len(selected)} fixtures in round '{round_label}'")

    picks: list[dict] = []
    pending: list[dict] = []
    errors: list[dict] = []

    for fixture in selected:
        result = predict_match(fixture, fit, venues, elos, odds, rules, mcfg)
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

    csv_dst = OUTPUTS_DIR / f"picks_{round_label}.csv"
    _write_csv(picks, csv_dst)
    print(f"  wrote {csv_dst}")

    json_dst = OUTPUTS_DIR / f"picks_{round_label}.json"
    with json_dst.open("w", encoding="utf-8") as f:
        json.dump({
            "as_of": datetime.utcnow().isoformat() + "Z",
            "round": round_label,
            "rules": {"points_exact": rules.points_exact, "points_1x2": rules.points_1x2,
                      "exclusive": rules.exclusive},
            "model": {"mu": fit.mu, "gamma": fit.gamma, "rho": fit.rho,
                      "n_teams": fit.n_teams, "n_matches": fit.n_matches,
                      "strategy": "poisson+elo+odds blend, ev_no_draw",
                      "odds_matches": len(odds)},
            "picks": picks,
            "pending_knockouts": [
                {"date": f["date"], "stage": f["stage"],
                 "home_placeholder": f["home_placeholder"], "away_placeholder": f["away_placeholder"],
                 "venue": f.get("venue"), "match_id": f["match_id"]}
                for f in pending
            ],
        }, f, indent=2, ensure_ascii=False)
    print(f"  wrote {json_dst}")

    md_dst = OUTPUTS_DIR / f"picks_{round_label}.md"
    _write_markdown(picks, pending, rules, mcfg, md_dst, round_label)
    print(f"  wrote {md_dst}")

    fp_dst = OUTPUTS_DIR / f"fingerprint_{round_label}.json"
    with fp_dst.open("w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "round": round_label,
            "git_commit": git_commit(),
            "git_dirty": git_dirty(),
            "config_hash": config_hash(DEFAULT_CONFIG),
            "inputs": {
                str(fit_src.relative_to(fit_src.parent.parent)): file_sha256(fit_src),
                "data/wc2026/fixtures.json": file_sha256(WC_DIR / "fixtures.json"),
                "data/wc2026/venues.json": file_sha256(WC_DIR / "venues.json"),
            },
            "outputs": {
                csv_dst.name: file_sha256(csv_dst),
                json_dst.name: file_sha256(json_dst),
                md_dst.name: file_sha256(md_dst),
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
