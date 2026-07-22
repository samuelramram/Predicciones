"""Liga MX pipeline: Elo replay + Poisson·DC fit + EV-optimal picks per jornada.

Reuses the tournament-agnostic core (ratings/elo, model/poisson_dc,
model/blend, scoring/quiniela) with the Liga MX profile and data. It does NOT
touch the World-Cup pipeline — this is the "core común, perfil de liga" path
from docs/ligamx_apertura.md.

Two subcommands:

    python -m wc_predictor.pipeline.ligamx fit          # Elo + Poisson·DC → artifacts
    python -m wc_predictor.pipeline.ligamx picks --round j2

`fit` reads data/ligamx/matches_history.csv (from ingest.ligamx) and writes
data/ligamx/elo_current.json + data/ligamx/team_strengths.json.
`picks` reads those + data/ligamx/fixtures.json and writes
outputs/ligamx_picks_{round}.{json,md}.

Liga MX specifics vs the WC path:
  - Localía is per-team: the home side always gets the gamma boost (host="home").
  - Altitude is modelled by DIFFERENTIAL — the visitor loses λ proportional to
    (venue_altitude − visitor's own home altitude), so a CDMX side visiting
    Toluca is penalised far less than a sea-level side. Home side is acclimatised.
  - WC-only layers (host boost, goal inflation, mismatch ramp, J3 qualification)
    are neutralised in LIGAMX_APERTURA_PROFILE.model.
  - Atlante is a cold-start franchise (bought from Mazatlán, starts fresh); with
    ~1 match of history the ridge prior pins it near league average, wide — the
    intended behaviour. See docs/ligamx_apertura.md §Atlante cold-start.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, date
from pathlib import Path

from wc_predictor.config import OUTPUTS_DIR
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.model.blend import blend_three_sources
from wc_predictor.model.poisson_dc import (
    fit_dc_model,
    load_fit,
    predict_lambdas,
    profile_fit_rho,
    save_fit,
)
from wc_predictor.ratings.elo import elo_to_1x2_probs, replay_history
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

PROFILE = LIGAMX_APERTURA_PROFILE
LIGAMX_DIR = PROFILE.data_dir
HISTORY_CSV = LIGAMX_DIR / "matches_history.csv"
FIXTURES_JSON = LIGAMX_DIR / "fixtures.json"
TEAMS_JSON = LIGAMX_DIR / "teams.json"
VENUES_JSON = LIGAMX_DIR / "venues.json"
ELO_JSON = LIGAMX_DIR / "elo_current.json"
STRENGTHS_JSON = LIGAMX_DIR / "team_strengths.json"


# --- data loading -------------------------------------------------------------
def load_history_rows(src: Path = HISTORY_CSV) -> list[dict]:
    rows: list[dict] = []
    with src.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "date": r["date"],
                "home": r["home"],
                "away": r["away"],
                "home_score": int(r["home_score"]),
                "away_score": int(r["away_score"]),
                "neutral": r["neutral"].strip().lower() in {"true", "t", "1", "yes"},
                "tournament": r["tournament"],
            })
    rows.sort(key=lambda x: x["date"])
    return rows


def load_team_altitudes() -> dict[str, float]:
    """name_es → altitude (m) of its home stadium, via teams.json + venues.json."""
    teams = json.loads(TEAMS_JSON.read_text(encoding="utf-8"))["teams"]
    venues = json.loads(VENUES_JSON.read_text(encoding="utf-8"))["venues"]
    out: dict[str, float] = {}
    for t in teams:
        v = venues.get(t.get("home_venue") or "", {})
        out[t["name_es"]] = float(v.get("altitude_m", 0.0))
    return out


def _current_teams() -> list[dict]:
    return json.loads(TEAMS_JSON.read_text(encoding="utf-8"))["teams"]


# --- altitude (differential) --------------------------------------------------
def altitude_factor(venue_alt: float, visitor_home_alt: float, mcfg) -> float:
    """λ multiplier for the VISITOR, from the altitude they must climb to.

    Only the positive differential bites: a highland side visiting a lowland
    venue is unaffected. Floored at 0.5 like the WC altitude adjustment.
    """
    if mcfg.altitude_penalty_per_1000m <= 0:
        return 1.0
    diff = max(0.0, venue_alt - visitor_home_alt)
    return max(1.0 - mcfg.altitude_penalty_per_1000m * (diff / 1000.0), 0.5)


# --- fit ----------------------------------------------------------------------
def run_fit(fit_rho: bool | None = None) -> None:
    mcfg = PROFILE.model
    if not HISTORY_CSV.exists():
        raise SystemExit(
            f"Missing {HISTORY_CSV}. Run `python -m wc_predictor.ingest.ligamx --bootstrap` first."
        )
    rows = load_history_rows()
    print(f"Loaded {len(rows)} Liga MX matches ({rows[0]['date']} → {rows[-1]['date']})")

    # Elo replay over the club history (self-computed; clubelo is unreachable).
    track = {t["name_es"] for t in _current_teams()}
    elos, _ = replay_history(rows, mcfg, track_teams=track)
    as_of = rows[-1]["date"]
    ranked = [{"team": t, "elo": round(e, 2)} for t, e in sorted(elos.items(), key=lambda x: -x[1])]
    ELO_JSON.write_text(
        json.dumps({"as_of": as_of, "source": "replay_ligamx", "teams": ranked},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  wrote {ELO_JSON} (Elo for {len(ranked)} teams, as_of {as_of})")

    # Poisson + Dixon-Coles MLE. Ridge pins low-n sides (Atlante) to league avg.
    do_rho = mcfg.fit_rho if fit_rho is None else fit_rho
    if do_rho:
        print("Fitting Poisson + Dixon-Coles (profiling rho) ...")
        _, fit, _ = profile_fit_rho(rows, mcfg, ridge_lambda=mcfg.ridge_lambda)
    else:
        print("Fitting Poisson + Dixon-Coles ...")
        fit = fit_dc_model(rows, mcfg, ridge_lambda=mcfg.ridge_lambda)
    save_fit(fit, STRENGTHS_JSON, as_of=as_of)
    print(f"  wrote {STRENGTHS_JSON}  mu={fit.mu:.3f} gamma={fit.gamma:.3f} rho={fit.rho:.3f} "
          f"(e^gamma={pow(2.718281828, fit.gamma):.2f}x home)")

    # Sanity: strongest sides in the current field. Both latents are "higher =
    # better" (attack ↑ scores more, defense ↑ concedes less), so overall
    # strength ≈ attack + defense.
    cur = {t["name_es"] for t in _current_teams()}
    ranked_str = sorted(
        (s for t, s in fit.strengths.items() if t in cur),
        key=lambda s: -(s.attack + s.defense),
    )
    print("\nFuerza (attack + defense) del campo actual:")
    for i, s in enumerate(ranked_str, 1):
        elo = elos.get(s.team, 1500.0)
        print(f"  {i:2d}. {s.team:<12} atk={s.attack:+.2f} def={s.defense:+.2f} "
              f"Elo={elo:.0f} n={s.n_matches}")


# --- picks --------------------------------------------------------------------
def _odds_weights(mcfg, have_odds: bool) -> tuple[float, float, float]:
    """(w_poisson, w_elo, w_odds). Without odds → 2-way blend (≈0.70/0.30);
    with odds → odds take blend_odds_weight, Poisson:Elo keep their ratio on the
    remainder (same policy as the WC path)."""
    share = mcfg.blend_poisson_weight / (mcfg.blend_poisson_weight + mcfg.blend_elo_weight)
    if have_odds:
        rem = 1.0 - mcfg.blend_odds_weight
        return rem * share, rem * (1.0 - share), mcfg.blend_odds_weight
    return share, 1.0 - share, 0.0


def predict_fixture(fx: dict, fit, elos: dict[str, float], altitudes: dict[str, float],
                    mcfg, rules, odds: dict | None = None) -> dict | None:
    home, away = fx["home"], fx["away"]
    if home not in fit.strengths or away not in fit.strengths:
        return {"match_id": fx.get("match_id"), "home": home, "away": away,
                "error": "missing strengths"}

    # Poisson λ with per-team localía (home always gets gamma).
    lh, la = predict_lambdas(fit.strengths[home], fit.strengths[away], fit.mu, fit.gamma,
                             host="home")
    # Altitude differential: the visitor climbs to the home venue's altitude.
    venue_alt = altitudes.get(home, 0.0)
    la *= altitude_factor(venue_alt, altitudes.get(away, 0.0), mcfg)

    # Elo 1X2 with home bonus.
    r_h = elos.get(home, 1500.0)
    r_a = elos.get(away, 1500.0)
    elo_p1, elo_px, elo_p2 = elo_to_1x2_probs(r_h, r_a, mcfg.elo_home_bonus)

    # Bookmaker 1X2 for this match, if covered (de-vigged closing/live line).
    odds_entry = (odds or {}).get(f"{home}|{away}")
    odds_1x2 = (odds_entry["p1"], odds_entry["px"], odds_entry["p2"]) if odds_entry else None

    # Poisson·DC score matrix → blend with Elo (+ odds when available).
    w_po, w_el, w_od = _odds_weights(mcfg, odds_1x2 is not None)
    pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
    cells_b, p1_b, px_b, p2_b = blend_three_sources(
        pcells, (pp1, ppx, pp2), (elo_p1, elo_px, elo_p2), odds_1x2,
        w_poisson=w_po, w_elo=w_el, w_odds=w_od,
    )

    forbid = tuple(mcfg.forbid_outcomes)
    if px_b >= mcfg.draw_allow_min_prob and "X" in forbid:
        forbid = tuple(o for o in forbid if o != "X")
    pick = optimize_pick_from_cells(cells_b, p1_b, px_b, p2_b, pmass, pmax, rules, mcfg,
                                    forbid_outcomes=forbid)

    return {
        "match_id": fx.get("match_id"),
        "jornada": fx.get("jornada"),
        "date": fx.get("date"),
        "venue": fx.get("venue"),
        "home": home,
        "away": away,
        "elo_home": round(r_h, 1),
        "elo_away": round(r_a, 1),
        "lambda_home": round(lh, 3),
        "lambda_away": round(la, 3),
        "altitude_m": venue_alt,
        "odds_p1": round(odds_1x2[0], 3) if odds_1x2 else None,
        "odds_px": round(odds_1x2[1], 3) if odds_1x2 else None,
        "odds_p2": round(odds_1x2[2], 3) if odds_1x2 else None,
        "odds_n_books": odds_entry["n_books"] if odds_entry else 0,
        "blend_weights": {"poisson": round(w_po, 3), "elo": round(w_el, 3), "odds": round(w_od, 3)},
        "p_home_win": round(p1_b, 3),
        "p_draw": round(px_b, 3),
        "p_away_win": round(p2_b, 3),
        "pick_1x2": pick.pick_1x2,
        "pick_exact": pick.pick_exact,
        "p_exact": round(pick.prob_exact, 3),
        "ev": round(pick.ev, 3),
        "ev_gap": round(pick.ev_confidence_gap, 3),
        "abstain": pick.abstain,
        "contrarian_pick_1x2": pick.contrarian_pick_1x2,
        "contrarian_pick_exact": pick.contrarian_pick_exact,
        "contrarian_ev": round(pick.contrarian_ev, 3),
        "top_5_scores": [{"score": c["score"], "prob": round(c["prob"], 3)}
                         for c in pick.top_5_by_prob],
        "actual": (f"{fx['home_score']}-{fx['away_score']}"
                   if fx.get("home_score") is not None else None),
        # Transient (stripped before serialization) — inputs to the pool optimizer.
        "_cells": cells_b,
        "_elo_probs": (elo_p1, elo_px, elo_p2),
        "_alt_picks": list(pick.alt_picks or []),
    }


POOL_STANDINGS_JSON = LIGAMX_DIR / "pool_standings.json"
POOL_PICKS_JSON = LIGAMX_DIR / "pool_picks.json"


def _apply_pool_objective(picks: list[dict], fx_doc: dict, rules) -> None:
    """Re-select picks to maximize P(finishing 1st) in the pool instead of
    per-match EV. Mutates `picks` in place (mirrors the WC path, LMX data dirs).

    With data/ligamx/pool_standings.json the objective sees your gap to the
    field, exactos cushion and the horizon of matches still to come; with
    pool_picks.json the field is simulated on opponents' REAL submitted picks.
    Without the files it degrades to the single-round objective. See
    model.pool_optimizer / model.standings and docs/ligamx_apertura.md §Fase 2.
    """
    from wc_predictor.model.pool_optimizer import TicketMatch, optimize_ticket
    from wc_predictor.model.standings import attach_real_picks, compute_horizon, load_pool_context

    resolved_ids = {m["match_id"] for m in fx_doc["matches"]
                    if m.get("home_score") is not None}
    decidable = [p for p in picks if p["match_id"] not in resolved_ids]
    tmatches = [
        TicketMatch(
            match_id=p["match_id"], cells=p["_cells"], elo_probs=p["_elo_probs"],
            ev_pick=(p["pick_1x2"], p["pick_exact"]),
            contra_pick=(p["contrarian_pick_1x2"], p["contrarian_pick_exact"]),
            alt_picks=p.get("_alt_picks") or None,
        )
        for p in decidable
    ]

    ctx = load_pool_context(POOL_STANDINGS_JSON)
    if ctx is not None:
        horizon = compute_horizon(ctx, decision_pending=len(tmatches))
        gap = ctx.leader_points - ctx.your_points
        pos = (f"vas detrás del líder por {gap:.0f}" if gap > 0
               else f"lideras por {-gap:.0f}" if gap < 0 else "empatado en la cima")
        print(f"  standings: {ctx.you} {ctx.your_points:.0f} pts / {ctx.your_exactos:.0f} "
              f"exactos ({pos}), {len(ctx.opponents)} rivales; horizonte "
              f"{len(tmatches) + horizon} partidos")
        n_real = attach_real_picks(ctx, POOL_PICKS_JSON)
        print(f"  {'picks reales cargados para %d rivales' % n_real if n_real else 'sin pool_picks.json — campo sintético'}")
        result = optimize_ticket(tmatches, rules, your_points=ctx.your_points,
                                 your_exactos=ctx.your_exactos, opponents=ctx.opponents,
                                 your_q_rate=ctx.your_q_rate, your_e_rate=ctx.your_e_rate,
                                 horizon=horizon)
    else:
        print("  standings: sin data/ligamx/pool_standings.json — objetivo de un solo "
              "round (corre ingest.ligamx_pool para activar alcance/colchón).")
        result = optimize_ticket(tmatches, rules)

    swapped = set(result.swapped_to_contrarian)
    for p in picks:
        p["pool_swapped"] = p["match_id"] in swapped
        chosen = result.chosen.get(p["match_id"])
        if p["match_id"] in swapped and chosen is not None:
            p["pick_1x2"], p["pick_exact"] = chosen
    verdict = ("COLCHÓN: 0 swaps — tu ventaja se compone, EV puro" if not swapped
               else f"ALCANCE: {len(swapped)} swap(s) fuera del pick EV para maximizar P(1.º)")
    print(f"  pool objective: P(1.º) {result.win_prob_ev:.1%} (EV) → "
          f"{result.win_prob_pool:.1%} (pool) → {verdict}")


def run_picks(round_spec: str, objective: str = "ev") -> None:
    mcfg, rules = PROFILE.model, PROFILE.rules
    if not STRENGTHS_JSON.exists():
        raise SystemExit(f"Missing {STRENGTHS_JSON}. Run `... ligamx fit` first.")
    fit = load_fit(STRENGTHS_JSON)
    elos = {row["team"]: row["elo"]
            for row in json.loads(ELO_JSON.read_text(encoding="utf-8"))["teams"]}
    altitudes = load_team_altitudes()
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))

    odds = {}
    odds_h2h = LIGAMX_DIR / "odds_h2h.json"
    if odds_h2h.exists():
        odds = json.loads(odds_h2h.read_text(encoding="utf-8")).get("matches", {})
        print(f"  odds cargadas para {len(odds)} partidos (blend 3 vías, "
              f"{int(mcfg.blend_odds_weight*100)}% mercado)")
    else:
        print("  sin odds_h2h.json — blend 2 vías (corre ingest.ligamx_odds). ")

    spec = round_spec.strip().lower()
    if spec in ("all", ""):
        selected = fx_doc["matches"]
        label = "all"
    elif spec.startswith("j") and spec[1:].isdigit():
        n = int(spec[1:])
        selected = [m for m in fx_doc["matches"] if m.get("jornada") == n]
        label = f"j{n}"
    else:
        raise SystemExit(f"--round {round_spec!r} no válido para Liga MX. Usa j1..j17 o all.")
    if not selected:
        raise SystemExit(f"No hay partidos para --round {round_spec!r}.")

    picks, errors = [], []
    for fx in selected:
        r = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=odds)
        (errors if r and "error" in r else picks).append(r)

    if objective == "pool" and picks:
        _apply_pool_objective(picks, fx_doc, rules)

    # Strip transient pool-optimizer inputs before serialization.
    for p in picks:
        for k in ("_cells", "_elo_probs", "_alt_picks"):
            p.pop(k, None)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    json_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.json"
    json_dst.write_text(json.dumps({
        "as_of": datetime.utcnow().isoformat() + "Z",
        "league": "Liga MX", "round": label,
        "elo_as_of": json.loads(ELO_JSON.read_text(encoding="utf-8")).get("as_of"),
        "rules": {"points_exact": rules.points_exact, "points_1x2": rules.points_1x2},
        "picks": picks, "errors": errors,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    md_dst = OUTPUTS_DIR / f"ligamx_picks_{label}.md"
    md_dst.write_text(_render_md(picks, label, rules), encoding="utf-8")
    print(f"  wrote {json_dst}\n  wrote {md_dst}")

    print(f"\nBoleto {label} ({len(picks)} partidos):")
    for p in sorted(picks, key=lambda x: x.get("date") or ""):
        flag = " ★" if p["abstain"] else ""
        act = f"  (real {p['actual']})" if p.get("actual") else ""
        print(f"  {p['home']:<12} {p['pick_exact']:>4} {p['away']:<12} "
              f"[{p['pick_1x2']}] EV={p['ev']:.2f}{flag}{act}")


def _render_md(picks: list[dict], label: str, rules) -> str:
    lines = [f"# Picks Liga MX — {label.upper()}\n",
             f"_Generado {datetime.utcnow().isoformat()}Z · scoring "
             f"{rules.points_exact} exacto / {rules.points_1x2} 1X2 (excluyente, 90')._\n",
             "| Local | Marcador | Visitante | 1X2 | P(exacto) | EV | 1/X/2 | Real |",
             "|---|:--:|---|:--:|--:|--:|--|:--:|"]
    for p in sorted(picks, key=lambda x: x.get("date") or ""):
        star = " ★" if p["abstain"] else ""
        prob = f"{p['p_home_win']*100:.0f}/{p['p_draw']*100:.0f}/{p['p_away_win']*100:.0f}"
        lines.append(
            f"| {p['home']} | **{p['pick_exact']}** | {p['away']} | {p['pick_1x2']}{star} | "
            f"{p['p_exact']*100:.0f}% | {p['ev']:.2f} | {prob} | {p.get('actual') or '—'} |"
        )
    lines.append("\n★ = ABSTAIN (gap de EV bajo, poca confianza).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pipeline Liga MX (fit + picks).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("fit", help="Elo replay + Poisson·DC fit.")
    pf.add_argument("--no-fit-rho", dest="fit_rho", action="store_false", default=None)
    pp = sub.add_parser("picks", help="Genera picks de una jornada.")
    pp.add_argument("--round", default="all", help="j1..j17 | all")
    pp.add_argument("--objective", default="ev", choices=("ev", "pool"),
                    help="ev (default): cada pick maximiza sus propios puntos esperados. "
                         "pool: optimiza el boleto entero para P(quedar 1.º) usando "
                         "data/ligamx/pool_standings.json (+ pool_picks.json si existe).")
    args = parser.parse_args(argv)

    if args.cmd == "fit":
        run_fit(fit_rho=args.fit_rho)
    elif args.cmd == "picks":
        run_picks(args.round, objective=args.objective)


if __name__ == "__main__":
    main()
