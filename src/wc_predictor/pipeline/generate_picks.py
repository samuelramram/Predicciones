"""Generate picks from the fitted model for a chosen round of the tournament.

Run from repo root, after fit_model + fit_elo have produced their artifacts:

    python -m wc_predictor.pipeline.generate_picks                 # all locked matches
    python -m wc_predictor.pipeline.generate_picks --round group_stage
    python -m wc_predictor.pipeline.generate_picks --round j1      # jornada 1: 24 partidos (ronda 1 de todos los grupos)
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

from wc_predictor.config import DEFAULT_CONFIG, HISTORICAL_DIR, OUTPUTS_DIR, PROCESSED_DIR, RAW_DIR, WC_DIR
from wc_predictor.ingest.odds import load_cached_odds
from wc_predictor.model.adjustments import apply_wc_lambdas
from wc_predictor.model.blend import blend_three_sources
from wc_predictor.model.poisson_dc import load_fit, predict_lambdas
from wc_predictor.model.qualification import TOP2_SECURED, j3_stakes
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


def _annotate_group_rounds(matches: list[dict]) -> None:
    """Tag each group-stage fixture with `group_round` (1..6): its chronological
    index within its own group.

    Each group of 4 teams plays 6 matches total (3 rounds × 2 matches/group).
    Jornada N covers group_round values 2N-1 and 2N, giving 2×12=24 fixtures
    per jornada across the 12 WC2026 groups."""
    by_group: dict[str, list[dict]] = {}
    for m in matches:
        if m.get("stage") == "group_stage" and m.get("group"):
            by_group.setdefault(m["group"], []).append(m)
    for group_matches in by_group.values():
        ordered = sorted(group_matches, key=lambda x: (x["date"], x.get("date_utc", "")))
        for idx, m in enumerate(ordered, start=1):
            m["group_round"] = idx


def _load_fixtures() -> dict:
    with (WC_DIR / "fixtures.json").open(encoding="utf-8") as f:
        doc = json.load(f)
    _annotate_group_rounds(doc["matches"])
    return doc


KNOCKOUT_STAGES = ("round_of_32", "round_of_16", "quarter_final", "semi_final", "third_place", "final")


def build_j3_contexts(all_matches: list[dict], elos: dict[str, float]) -> dict:
    """Map match_id → StakesContext for every jornada-3 fixture whose group
    already has its four jornada-1 and jornada-2 results in `fixtures.json`.

    Empty before the tournament reaches jornada 3 — so the qualification-aware
    path is a no-op until the J1+J2 scores have been ingested.
    """
    by_group: dict[str, list[dict]] = {}
    for m in all_matches:
        if m.get("stage") == "group_stage" and m.get("group"):
            by_group.setdefault(m["group"], []).append(m)

    contexts: dict = {}
    for group, gms in by_group.items():
        teams = sorted({t for m in gms for t in (m["home"], m["away"])})
        if len(teams) != 4:
            continue
        played_j12 = [
            m for m in gms
            if m.get("group_round", 99) <= 4
            and m.get("home_score") is not None and m.get("away_score") is not None
        ]
        if len(played_j12) < 4:
            continue
        for m in gms:
            if m.get("group_round") in (5, 6):
                ctx = j3_stakes(group, teams, played_j12, m["home"], m["away"], elos)
                if ctx is not None:
                    contexts[m["match_id"]] = ctx
    return contexts


def resolve_round_filter(round_spec: str):
    """Return (predicate, label) for a --round argument.

    Accepted values:
      all                          → every fixture (default)
      group_stage                  → all 72 group matches
      j1 .. j3                     → "jornada N": one full group-stage round
                                     j1 = group_round ∈ {1,2}, j2 = {3,4}, j3 = {5,6}
                                     Each jornada covers 2 matches/group × 12 groups = 24 fixtures
      md1 .. md17                  → a single FIFA calendar matchday
      round_of_32 / round_of_16 / quarter_final / semi_final / third_place / final
    """
    spec = round_spec.strip().lower()
    if spec in ("all", ""):
        return (lambda fx: True), "all"
    if spec == "group_stage":
        return (lambda fx: fx["stage"] == "group_stage"), "group_stage"
    if spec.startswith("j") and spec[1:].isdigit():
        n = int(spec[1:])
        # Each group plays 2 matches per round: group_round 1&2 = jornada 1, 3&4 = j2, 5&6 = j3
        low, high = 2 * n - 1, 2 * n
        return (lambda fx, lo=low, hi=high: fx.get("group_round") in {lo, hi}), f"j{n}"
    if spec.startswith("md") and spec[2:].isdigit():
        n = int(spec[2:])
        label_target = f"Matchday {n}"
        return (lambda fx: fx.get("round_label") == label_target), f"md{n}"
    if spec in KNOCKOUT_STAGES:
        return (lambda fx: fx["stage"] == spec), spec
    raise SystemExit(
        f"Unknown --round value: {round_spec!r}. "
        f"Use: all, group_stage, j1..j3, md1..md17, or one of {', '.join(KNOCKOUT_STAGES)}."
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


def predict_match(fixture: dict, fit, venues: dict, elos: dict, odds: dict, rules, mcfg,
                  qual=None):
    """Return a pick dict for a locked fixture, or None if not predictable yet.

    Pipeline:
      1. Compute (lambda_home, lambda_away) from the Poisson + DC fit.
      2. Compute (P_1, P_X, P_2) from Elo using pre-match ratings + host bonus.
      3. Look up bookmaker odds for this match (if available).
      4. Log-pool Poisson + Elo + Odds 1X2 marginals (odds dropped gracefully
         if not covered → falls back to the backtested 70/30 Poisson/Elo blend).
      5. Rescale the Poisson score-matrix to the blended marginals.
      6. optimize_pick_from_cells with forbid_outcomes=("X",) — never pick draws.

    `qual` is the jornada-3 StakesContext (or None). When present it damps a
    team's λ if its top-2 spot is already locked (likely rotation) and lifts the
    no-draw constraint when a draw would send both teams through.
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

    # WC inflation + skill-gap (mismatch) inflation — single entry point for the
    # two layers that shape the score matrix (see adjustments.apply_wc_lambdas).
    lh, la = apply_wc_lambdas(lh, la, mcfg)

    # Jornada-3 qualification incentive: a team whose top-2 finish is already
    # mathematically locked tends to rotate its XI for the dead-rubber final
    # group match — damp its expected goals (see ModelConfig.qual_rotation_lambda_mult).
    if qual is not None:
        if qual.home_status == TOP2_SECURED:
            lh *= mcfg.qual_rotation_lambda_mult
        if qual.away_status == TOP2_SECURED:
            la *= mcfg.qual_rotation_lambda_mult

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
    # Draws are normally forbidden (backtested net-negative), but in a J3 match
    # where a draw qualifies both teams the calculated-draw incentive makes X a
    # live outcome — allow it there.
    forbid = () if (qual is not None and qual.mutual_draw_safe) else PROD_FORBID
    pick = optimize_pick_from_cells(
        cells_b, p1_b, px_b, p2_b, pmass, pmax, rules, mcfg,
        forbid_outcomes=forbid,
    )

    contrarian_differs = pick.contrarian_pick_1x2 != pick.pick_1x2
    ev_sacrifice = pick.ev - pick.contrarian_ev

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
        "contrarian_pick_1x2": pick.contrarian_pick_1x2,
        "contrarian_pick_exact": pick.contrarian_pick_exact,
        "contrarian_ev": round(pick.contrarian_ev, 3),
        "contrarian_score": round(pick.contrarian_score, 3),
        "contrarian_differs": contrarian_differs,
        "contrarian_ev_sacrifice": round(ev_sacrifice, 3),
        "contrarian_actionable": contrarian_differs and ev_sacrifice <= mcfg.contrarian_max_ev_sacrifice,
        "top_5_scores": [{"score": c["score"], "prob": round(c["prob"], 3)} for c in pick.top_5_by_prob],
        "dead_rubber": bool(qual is not None and qual.dead_rubber),
        "qualification": (
            {
                "home_status": qual.home_status,
                "away_status": qual.away_status,
                "dead_rubber": qual.dead_rubber,
                "mutual_draw_safe": qual.mutual_draw_safe,
                "note": qual.note,
            }
            if qual is not None else None
        ),
    }


def _write_csv(picks: list[dict], dst: Path) -> None:
    cols = ["date", "stage", "group", "home", "away", "venue",
            "pick_1x2", "pick_exact", "ev", "ev_gap", "abstain", "dead_rubber",
            "contrarian_pick_1x2", "contrarian_pick_exact", "contrarian_ev", "contrarian_score",
            "contrarian_differs", "contrarian_ev_sacrifice", "contrarian_actionable",
            "p_home_win", "p_draw", "p_away_win", "p_exact",
            "lambda_home", "lambda_away", "match_id"]
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in picks:
            w.writerow(p)


ROUND_TITLES = {
    "all": "Todas las rondas",
    "group_stage": "Fase de grupos",
    "round_of_32": "Dieciseisavos de final",
    "round_of_16": "Octavos de final",
    "quarter_final": "Cuartos de final",
    "semi_final": "Semifinales",
    "third_place": "Partido por el tercer lugar",
    "final": "Final",
}


def _round_title(label: str) -> str:
    if label in ROUND_TITLES:
        return ROUND_TITLES[label]
    if label.startswith("md") and label[2:].isdigit():
        return f"Matchday {label[2:]} (FIFA)"
    if label.startswith("j") and label[1:].isdigit():
        return f"Jornada {label[1:]} · Fase de grupos"
    return label


# Nombres de selección en español, solo para el reporte .md. La capa de datos
# (modelo, Elo, CSV, JSON) conserva los nombres en inglés de las fuentes
# martj42/openfootball — esto es presentación, no se toca la fuente de verdad.
TEAM_ES = {
    "Mexico": "México", "South Africa": "Sudáfrica", "Czech Republic": "República Checa",
    "South Korea": "Corea del Sur", "Canada": "Canadá", "Switzerland": "Suiza",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina", "Bosnia & Herzegovina": "Bosnia y Herzegovina",
    "Qatar": "Catar", "Brazil": "Brasil", "Scotland": "Escocia", "Morocco": "Marruecos",
    "Haiti": "Haití", "United States": "Estados Unidos", "Australia": "Australia",
    "Paraguay": "Paraguay", "Turkey": "Turquía", "Germany": "Alemania", "Ecuador": "Ecuador",
    "Ivory Coast": "Costa de Marfil", "Curaçao": "Curazao", "Netherlands": "Países Bajos",
    "Sweden": "Suecia", "Japan": "Japón", "Tunisia": "Túnez", "Belgium": "Bélgica",
    "Egypt": "Egipto", "Iran": "Irán", "New Zealand": "Nueva Zelanda", "Spain": "España",
    "Uruguay": "Uruguay", "Saudi Arabia": "Arabia Saudita", "Cape Verde": "Cabo Verde",
    "France": "Francia", "Senegal": "Senegal", "Norway": "Noruega", "Iraq": "Irak",
    "Argentina": "Argentina", "Austria": "Austria", "Algeria": "Argelia", "Jordan": "Jordania",
    "Portugal": "Portugal", "Colombia": "Colombia", "DR Congo": "RD Congo",
    "Uzbekistan": "Uzbekistán", "England": "Inglaterra", "Croatia": "Croacia",
    "Ghana": "Ghana", "Panama": "Panamá",
}


def _team_es(name: str) -> str:
    """Nombre de selección en español; si no está mapeado, devuelve el original."""
    return TEAM_ES.get(name, name)


def _fmt_score(exact: str) -> str:
    """'2-0' -> '2 - 0' for the boleto display."""
    h, _, a = exact.partition("-")
    return f"{h} - {a}"


def _outcome_es(outcome: str, home: str, away: str) -> str:
    return {"1": f"victoria de {home}", "X": "empate",
            "2": f"victoria de {away}"}[outcome]


def _boleto_block(picks: list[dict], round_label: str, rules) -> str:
    """Monospace 'boleto' — the copy-to-quiniela section, EV-optimal + contrarian columns."""
    name_w = max(max(len(_team_es(p["home"])), len(_team_es(p["away"]))) for p in picks)
    prefix_w = 15 + 2 * name_w               # up to (but not including) the score columns
    width = prefix_w + 7 + 3 + 7 + 3

    rows = ["═" * width,
            f"  TU BOLETO · {_round_title(round_label)} · Mundial 2026",
            "═" * width,
            " " * prefix_w + f"{'EV-ÓPT':>7}   {'CONTRA':>7}",
            "─" * width]

    total_ev = 0.0
    abstain_n = contra_n = 0
    for i, p in enumerate(picks, start=1):
        total_ev += p["ev"]
        flag = "★" if p["abstain"] else ""
        if p["abstain"]:
            abstain_n += 1
        con_mark = ""
        if p.get("contrarian_actionable"):
            con_mark = " ◆"
            contra_n += 1
        line = (f"  {i:>2}  {_team_es(p['home']):>{name_w}}  vs  "
                f"{_team_es(p['away']):<{name_w}}   "
                f"{_fmt_score(p['pick_exact']):>7}   "
                f"{_fmt_score(p['contrarian_pick_exact']):>7}{con_mark} {flag}")
        rows.append(line.rstrip())

    max_pts = len(picks) * rules.points_exact
    rows.append("─" * width)
    rows.append(f"  {len(picks)} partidos · EV total {total_ev:.2f} / {max_pts} máx · "
                f"{abstain_n}★ ABSTAIN · {contra_n}◆ contrarian accionable")
    rows.append("═" * width)
    return "\n".join(rows)


def _reasoning(p: dict, rules, mcfg) -> str:
    """One paragraph explaining why the optimizer landed on this pick."""
    home, away = _team_es(p["home"]), _team_es(p["away"])
    pe = p["pick_exact"]
    top = p.get("top_5_scores", [])
    modal = top[0]["score"] if top else None
    modal_prob = top[0]["prob"] * 100 if top else 0.0
    p1x2_pct = {"1": p["p_home_win"], "X": p["p_draw"], "2": p["p_away_win"]}[p["pick_1x2"]]

    parts: list[str] = []
    if pe == modal:
        parts.append(
            f"El marcador {pe} es además el más probable de toda la grilla "
            f"({modal_prob:.1f}%): el optimizador EV y el marcador modal coinciden."
        )
    else:
        parts.append(
            f"El optimizador elige {pe} (EV {p['ev']:.2f}) por encima del marcador modal "
            f"{modal} ({modal_prob:.1f}%): {pe} cae dentro de "
            f"{_outcome_es(p['pick_1x2'], home, away)} (P={p1x2_pct * 100:.0f}%) y maximiza "
            f"el EV combinado de marcador exacto + resultado 1X2."
        )

    if p["abstain"]:
        parts.append(
            f"⚠ ABSTAIN: el gap de EV al segundo candidato es {p['ev_gap']:.3f} "
            f"(< {mcfg.ev_abstain_gap}); confianza baja, conviene contrastarlo con criterio propio."
        )

    if p.get("contrarian_differs"):
        c_pct = {"1": p["p_home_win"], "X": p["p_draw"],
                 "2": p["p_away_win"]}[p["contrarian_pick_1x2"]]
        ev_sac = p.get("contrarian_ev_sacrifice", p["ev"] - p["contrarian_ev"])
        if p.get("contrarian_actionable"):
            parts.append(
                f"◆ Jugada contrarian accionable: {p['contrarian_pick_exact']} "
                f"({_outcome_es(p['contrarian_pick_1x2'], home, away)}, P={c_pct * 100:.0f}%). "
                f"Solo sacrificas {ev_sac:.2f} de EV individual y, si la sorpresa entra, te "
                f"diferencias de casi todo el pool. Recomendable si vas atrás en la tabla."
            )
        else:
            parts.append(
                f"El contrarian apuntaría a {p['contrarian_pick_exact']} "
                f"({_outcome_es(p['contrarian_pick_1x2'], home, away)}, P={c_pct * 100:.0f}%), "
                f"pero el costo es alto: sacrificarías {ev_sac:.2f} de EV individual "
                f"(> {mcfg.contrarian_max_ev_sacrifice}). No es una jugada recomendada; "
                f"quédate con el EV-óptimo."
            )

    qual = p.get("qualification")
    if qual and qual["dead_rubber"]:
        parts.append(
            "⚑ Partido sin nada en juego para la clasificación: ambas selecciones "
            "ya tienen definida su suerte en el top-2, así que el resultado es "
            "especialmente ruidoso (rotaciones, ritmo bajo) — baja la confianza en "
            "este pick y considera la jugada contrarian."
        )
    elif qual and qual["mutual_draw_safe"]:
        parts.append(
            "A las dos selecciones les sirve el empate para avanzar, así que aquí "
            "el modelo no descarta la X (riesgo de empate de conveniencia)."
        )
    return " ".join(parts)


def _match_card(idx: int, p: dict, rules, mcfg) -> list[str]:
    """Full technical card for one match."""
    home, away = _team_es(p["home"]), _team_es(p["away"])
    lines = [f"### {idx} · {home} vs {away}"]

    meta = []
    if p.get("group"):
        meta.append(f"Grupo {p['group']}")
    meta.append(p["date"])
    if p.get("venue"):
        meta.append(p["venue"])
    if p.get("host"):
        meta.append(f"anfitrión: {home if p['host'] == 'home' else away}")
    lines.append("_" + " · ".join(meta) + "_\n")

    lines.append(f"**Marcador EV-óptimo: {p['pick_exact']}** "
                 f"({_outcome_es(p['pick_1x2'], home, away)})  ")
    lines.append(f"EV {p['ev']:.2f} · P(marcador exacto) {p['p_exact'] * 100:.1f}% · "
                 f"gap al 2.º candidato {p['ev_gap']:.3f}\n")

    if p.get("contrarian_differs"):
        ev_sac = p.get("contrarian_ev_sacrifice", p["ev"] - p["contrarian_ev"])
        mark = " ◆" if p.get("contrarian_actionable") else ""
        tag = "accionable" if p.get("contrarian_actionable") else "no recomendada (costo alto)"
        lines.append(f"**Alternativa contrarian: {p['contrarian_pick_exact']}**{mark} "
                     f"({_outcome_es(p['contrarian_pick_1x2'], home, away)}) — {tag}  ")
        lines.append(f"EV {p['contrarian_ev']:.2f} · C-score {p['contrarian_score']:.2f} · "
                     f"sacrificas {ev_sac:.2f} de EV individual\n")
    else:
        lines.append("_El pick contrarian coincide con el EV-óptimo en este partido._\n")

    lines.append("| Métrica | Valor |")
    lines.append("|---|---|")
    lines.append(f"| Goles esperados (λ) | {home} {p['lambda_home']:.2f} — "
                 f"{p['lambda_away']:.2f} {away} |")
    elo_note = ""
    if p.get("host") == "home":
        elo_note = " · +80 anfitrión (local)"
    elif p.get("host") == "away":
        elo_note = " · +80 anfitrión (visitante)"
    lines.append(f"| Rating Elo | {p['elo_home']:.0f} vs {p['elo_away']:.0f}{elo_note} |")
    lines.append(f"| Probabilidad 1 / X / 2 | {p['p_home_win'] * 100:.0f}% / "
                 f"{p['p_draw'] * 100:.0f}% / {p['p_away_win'] * 100:.0f}% |")
    bw = p.get("blend_weights", {})
    lines.append(f"| Pesos de la mezcla | {bw.get('poisson', 0) * 100:.0f}% Poisson · "
                 f"{bw.get('elo', 0) * 100:.0f}% Elo · {bw.get('odds', 0) * 100:.0f}% cuotas |")
    if p.get("odds_n_books"):
        lines.append(f"| Cuotas implícitas casas | {p['odds_p1']:.0%} / {p['odds_px']:.0%} / "
                     f"{p['odds_p2']:.0%} ({p['odds_n_books']} casas) |")
    lines.append("")

    top = p.get("top_5_scores", [])
    if top:
        top_str = " · ".join(f"`{c['score']}` {c['prob'] * 100:.1f}%" for c in top)
        lines.append(f"**Top-5 marcadores más probables:** {top_str}\n")

    qual = p.get("qualification")
    if qual:
        marker = "⚑ " if qual["dead_rubber"] else ""
        lines.append(f"**{marker}Contexto de clasificación (J3):** {qual['note']}\n")

    lines.append(f"> {_reasoning(p, rules, mcfg)}\n")
    return lines


def _write_markdown(picks: list[dict], pending: list[dict], rules, mcfg, dst: Path,
                    round_label: str = "all") -> None:
    picks_sorted = sorted(picks, key=lambda x: (x["date"], x.get("match_id", 0)))

    lines = [f"# Quiniela Mundial 2026 — {_round_title(round_label)}\n"]
    lines.append(f"_Generado {datetime.utcnow().isoformat()}Z · scoring "
                 f"{rules.points_exact} pts marcador exacto / {rules.points_1x2} pt resultado "
                 f"1X2 (excluyente, 90 min)._\n")

    # --- Boleto: marcadores listos para copiar ---
    if picks_sorted:
        lines.append("```")
        lines.append(_boleto_block(picks_sorted, round_label, rules))
        lines.append("```\n")

    # --- Cómo leer ---
    lines.append("## Cómo leer esto\n")
    lines.append("- **EV-ÓPT** — marcador que maximiza el valor esperado de puntos. Es la "
                 "recomendación por defecto, partido a partido.")
    lines.append("- **CONTRA** — marcador de alto *apalancamiento* en el pool "
                 "(C-score = EV / popularidad del resultado). El contrarian casi siempre "
                 "apunta a la sorpresa; la columna lo muestra en todos los partidos como "
                 "referencia.")
    lines.append(f"- **◆ contrarian accionable** — el contrarian solo se marca ◆ cuando el "
                 f"sacrificio de EV es ≤ {mcfg.contrarian_max_ev_sacrifice}: ahí pierdes "
                 f"poco valor individual y, si la sorpresa entra, te diferencias del pool. "
                 f"Esas son tus jugadas de diferenciación reales.")
    lines.append(f"- **★ ABSTAIN** — el gap de EV entre el 1.º y 2.º candidato es menor a "
                 f"{mcfg.ev_abstain_gap}; pick de baja confianza.\n")

    # --- Resumen ejecutivo ---
    total_ev = sum(p["ev"] for p in picks_sorted)
    abstain_count = sum(1 for p in picks_sorted if p["abstain"])
    dead_rubbers = [p for p in picks_sorted if p.get("dead_rubber")]
    actionable = [p for p in picks_sorted if p.get("contrarian_actionable")]
    max_pts = len(picks_sorted) * rules.points_exact
    lines.append("## Resumen ejecutivo\n")
    if picks_sorted:
        lines.append(f"- **{len(picks_sorted)} partidos** · EV total **{total_ev:.2f}** / "
                     f"{max_pts} máx teórico ({total_ev / max_pts * 100:.0f}% del techo).")
        lines.append(f"- **{abstain_count}** picks marcados ABSTAIN (baja confianza).")
        if dead_rubbers:
            lines.append(f"- **{len(dead_rubbers)}** partidos sin nada en juego "
                         f"(⚑ dead rubber) — clasificación ya definida, picks de baja "
                         f"confianza.")
        lines.append(f"- **{len(actionable)}** jugadas contrarian accionables (◆) — "
                     f"sacrificio de EV ≤ {mcfg.contrarian_max_ev_sacrifice}; tus "
                     f"oportunidades reales de diferenciación.")
        if actionable:
            tags = ", ".join(f"{_team_es(p['home'])}–{_team_es(p['away'])} "
                             f"({p['contrarian_pick_exact']})" for p in actionable)
            lines.append(f"  - Accionables: {tags}.")
        best = max(picks_sorted, key=lambda p: p["ev"])
        worst = min(picks_sorted, key=lambda p: p["ev_gap"])
        lines.append(f"- Pick más sólido: **{_team_es(best['home'])} vs "
                     f"{_team_es(best['away'])}** → {best['pick_exact']} (EV {best['ev']:.2f}).")
        lines.append(f"- Pick más frágil: **{_team_es(worst['home'])} vs "
                     f"{_team_es(worst['away'])}** → {worst['pick_exact']} "
                     f"(gap {worst['ev_gap']:.3f}).")
    else:
        lines.append("- Sin partidos predecibles en esta ronda todavía.")
    lines.append("")

    # --- Fichas técnicas ---
    if picks_sorted:
        lines.append("## Fichas técnicas por partido\n")
        for i, p in enumerate(picks_sorted, start=1):
            lines.extend(_match_card(i, p, rules, mcfg))

    # --- Pendientes ---
    if pending:
        lines.append(f"## Pendientes — {len(pending)} partidos de eliminatorias\n")
        lines.append("Se predicen cuando se resuelvan los placeholders del bracket "
                     "(tras la ronda previa).\n")
        lines.append("| Fecha | Ronda | Local | Visitante | Sede |")
        lines.append("|---|---|---|---|---|")
        for p in pending:
            lines.append(
                f"| {p['date']} | {_round_title(p['stage'])} | {p['home_placeholder']} | "
                f"{p['away_placeholder']} | {p.get('venue', '?')} |"
            )
        lines.append("")

    dst.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate WC2026 quiniela picks for a round.")
    parser.add_argument("--round", default="all",
                        help="all | group_stage | j1..j3 (jornada = ronda completa de fase de grupos, 24 partidos) "
                             "| md1..md17 (matchday FIFA) | round_of_32 | round_of_16 "
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

    j3_contexts = build_j3_contexts(fixtures_doc["matches"], elos)
    if j3_contexts:
        print(f"Jornada-3 qualification context ready for {len(j3_contexts)} fixtures")

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
        result = predict_match(fixture, fit, venues, elos, odds, rules, mcfg,
                               qual=j3_contexts.get(fixture["match_id"]))
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
                "data/historical/elo_current.json": file_sha256(HISTORICAL_DIR / "elo_current.json"),
                "data/raw/odds_the_odds_api.json": file_sha256(RAW_DIR / "odds_the_odds_api.json"),
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
