"""Ingest the pool webapp's per-round CSV exports (real picks of every player).

The Lovable app exports one CSV per round with columns:

    Usuario,Partido,Predicción,Resultado Real,Puntos

- `Partido` uses Spanish team names ("Bélgica vs Senegal") in app order, which
  may be flipped vs fixtures.json — picks/results are re-oriented to the
  fixture's home/away before persisting.
- `Resultado Real` is USUALLY the 90-minute score ("2-1") or "Pendiente" — but
  for knockout matches decided in extra time the app has been observed to
  display the FINAL (post-ET) score while still awarding `Puntos` on the 90'
  result (Bélgica-Senegal R32: displayed 3-2, points paid on 2-2). Since the
  quiniela is 90'-only and fixtures.json is the knockout source of truth, every
  displayed result is cross-checked against the app's own points and, when
  inconsistent (or still Pendiente), the 90' score is INFERRED as the unique
  scoreline that reproduces every player's points (see `_reconcile_results`).
- `Puntos` is the app's own scoring (2 exact / 1 result / 0), already applied
  even for matches the export still lists as Pendiente but that finished while
  the export was generated — so player totals are summed straight from it.

Outputs (all versioned):
    data/wc2026/pool_picks.json      real picks per player per match_id
    data/wc2026/pool_standings.json  full leaderboard (points + exactos) recomputed
    data/wc2026/fixtures.json        90' scores merged into the matched fixtures

Usage:
    python -m wc_predictor.ingest.pool_picks data/wc2026/pool_exports/*.csv \
        --you Claudio --set-result "Bélgica vs Senegal=2-2"

Round detection is by filename (j1/j2/j3, Dieciseisavos/round_of_32, Octavos/
round_of_16, Cuartos, Semifinal, Tercer, Final) so that a rematch of a group
pairing in a knockout round can't mis-match.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, WC_DIR
from wc_predictor.names import team_en
from wc_predictor.scoring.quiniela import score_actual

ROUND_HINTS = [
    ("j1", "j1"), ("j2", "j2"), ("j3", "j3"),
    ("dieciseisavos", "round_of_32"), ("round_of_32", "round_of_32"),
    ("octavos", "round_of_16"), ("round_of_16", "round_of_16"),
    ("cuartos", "quarter_final"), ("quarter", "quarter_final"),
    ("semifinal", "semi_final"), ("semi", "semi_final"),
    ("tercer", "third_place"), ("third", "third_place"),
    ("final", "final"),  # keep last: "final" is a substring of several hints
]


def round_from_filename(path: Path) -> str:
    name = path.name.lower()
    for hint, spec in ROUND_HINTS:
        if hint in name:
            return spec
    raise SystemExit(f"Cannot infer round from filename {path.name!r}; "
                     f"rename it to include j1/j2/j3/dieciseisavos/octavos/...")


def _parse_score(txt: str) -> tuple[int, int] | None:
    txt = (txt or "").strip()
    if not txt or txt.lower() == "pendiente":
        return None
    h, sep, a = txt.partition("-")
    if not sep:
        return None
    return int(h.strip()), int(a.strip())


def _fixture_index(round_spec: str) -> dict[frozenset, dict]:
    """Map {home, away} (English names) → fixture, restricted to one round."""
    # Local import: pipeline.generate_picks owns the round/jornada semantics.
    from wc_predictor.pipeline.generate_picks import _load_fixtures, resolve_round_filter

    round_filter, _ = resolve_round_filter(round_spec)
    doc = _load_fixtures()
    index: dict[frozenset, dict] = {}
    for fx in doc["matches"]:
        if round_filter(fx) and fx.get("home") and fx.get("away"):
            index[frozenset((fx["home"], fx["away"]))] = fx
    return index


def parse_export(path: Path, round_spec: str,
                 result_overrides: dict[frozenset, tuple[int, int]] | None = None) -> dict:
    """Parse one round export → {round, matches: {match_id: result|None},
    picks: {player: {match_id: (h, a)}}, points: {player: {match_id: int|None}}}.

    Picks, results and points are oriented to the FIXTURE's home/away.
    """
    index = _fixture_index(round_spec)
    result_overrides = result_overrides or {}

    picks: dict[str, dict[str, tuple[int, int]]] = {}
    points: dict[str, dict[str, int | None]] = {}
    results: dict[str, tuple[int, int] | None] = {}
    unmatched: set[str] = set()

    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            partido = row["Partido"].strip()
            es_home, _, es_away = partido.partition(" vs ")
            en_home, en_away = team_en(es_home), team_en(es_away)
            fx = index.get(frozenset((en_home, en_away)))
            if fx is None:
                unmatched.add(partido)
                continue
            flipped = fx["home"] == en_away  # app lists the fixture reversed

            def orient(score: tuple[int, int] | None) -> tuple[int, int] | None:
                if score is None:
                    return None
                return (score[1], score[0]) if flipped else score

            mid = fx["match_id"]
            pred = orient(_parse_score(row["Predicción"]))
            real = orient(_parse_score(row["Resultado Real"]))
            if real is None:
                real = result_overrides.get(frozenset((en_home, en_away)))
            if mid not in results or results[mid] is None:
                results[mid] = real
            pts_txt = (row.get("Puntos") or "").strip()
            pts = int(pts_txt) if pts_txt.isdigit() else None

            player = row["Usuario"].strip()
            if pred is not None:
                picks.setdefault(player, {})[mid] = pred
            points.setdefault(player, {})[mid] = pts

    if unmatched:
        print(f"  WARNING [{path.name}]: no fixture match for: {sorted(unmatched)}")

    _reconcile_results(results, picks, points, label=path.name)
    return {"round": round_spec, "results": results, "picks": picks, "points": points}


def _consistent_with_points(result: tuple[int, int],
                            scored: list[tuple[tuple[int, int], int]]) -> bool:
    """True iff `result` reproduces every (pick, app_points) pair under the rules."""
    rules = DEFAULT_CONFIG.rules
    for (ph, pa), pts in scored:
        outcome = "X" if ph == pa else ("1" if ph > pa else "2")
        if score_actual(result[0], result[1], outcome, f"{ph}-{pa}", rules) != pts:
            return False
    return True


def _reconcile_results(results: dict[str, tuple[int, int] | None],
                       picks: dict[str, dict[str, tuple[int, int]]],
                       points: dict[str, dict[str, int | None]],
                       label: str = "", max_goals: int = 10) -> None:
    """Cross-check each match's displayed result against the app's own points;
    infer the 90' score when they disagree (or when the result is Pendiente but
    points were already awarded). Mutates `results` in place.

    Why: `Puntos` is always scored on the 90' result, but for knockout matches
    decided in extra time the app can display the post-ET score (Bélgica-Senegal
    R32: displayed 3-2, points paid on 2-2). Ingesting the displayed score would
    corrupt fixtures.json — the knockout source of truth — and every backtest
    and refit downstream. With ~30 varied picks per match, the 90' scoreline is
    (in practice) the unique one that reproduces everyone's points, so it can be
    recovered even when the export still says Pendiente — no --set-result needed.
    """
    for mid, displayed in results.items():
        scored = []
        for player, per_match in points.items():
            pts = per_match.get(mid)
            pick = picks.get(player, {}).get(mid)
            if pts is not None and pick is not None:
                scored.append((pick, pts))
        if not scored:
            continue  # nothing awarded yet — keep whatever the export said
        if displayed is not None and _consistent_with_points(displayed, scored):
            continue

        candidates = [
            (h, a)
            for h in range(max_goals + 1)
            for a in range(max_goals + 1)
            if _consistent_with_points((h, a), scored)
        ]
        if len(candidates) == 1:
            inferred = candidates[0]
            was = f"{displayed[0]}-{displayed[1]}" if displayed else "Pendiente"
            print(f"  NOTE [{label}] {mid}: displayed result {was} does not match the "
                  f"app's points — using inferred 90' score "
                  f"{inferred[0]}-{inferred[1]} (likely an extra-time score, or a "
                  f"result the export still lists as Pendiente).")
            results[mid] = inferred
        elif displayed is not None:
            # Inconsistent AND ambiguous: refuse to guess, but do not ingest a
            # score the app's own points contradict.
            print(f"  WARNING [{label}] {mid}: displayed result "
                  f"{displayed[0]}-{displayed[1]} contradicts the app's points and "
                  f"{len(candidates)} scorelines fit — dropping it; re-export once "
                  f"the app settles or pass --set-result.")
            results[mid] = None


def merge_results_into_fixtures(all_results: dict[str, tuple[int, int]]) -> int:
    """Write 90' scores into data/wc2026/fixtures.json. Returns #updated."""
    src = WC_DIR / "fixtures.json"
    with src.open(encoding="utf-8") as f:
        doc = json.load(f)
    updated = 0
    for m in doc["matches"]:
        res = all_results.get(m["match_id"])
        if res is None:
            continue
        if m.get("home_score") != res[0] or m.get("away_score") != res[1]:
            m["home_score"], m["away_score"] = res[0], res[1]
            updated += 1
    with src.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return updated


def recompute_standings(rounds: list[dict], you: str, rules) -> dict:
    """Leaderboard from the app's own `Puntos` where present; for matches whose
    result arrived via --set-result (export said Pendiente), score locally with
    the pool-of-truth `score_actual`."""
    totals: dict[str, int] = {}
    exactos: dict[str, int] = {}
    resolved: set[str] = set()

    for rd in rounds:
        for mid, res in rd["results"].items():
            if res is not None:
                resolved.add(mid)
        for player, per_match in rd["points"].items():
            for mid, pts in per_match.items():
                res = rd["results"].get(mid)
                if pts is None and res is not None:
                    pick = rd["picks"].get(player, {}).get(mid)
                    if pick is not None:
                        outcome = "X" if pick[0] == pick[1] else ("1" if pick[0] > pick[1] else "2")
                        pts = score_actual(res[0], res[1], outcome, f"{pick[0]}-{pick[1]}", rules)
                if pts is None:
                    continue
                totals[player] = totals.get(player, 0) + pts
                if pts >= rules.points_exact:
                    exactos[player] = exactos.get(player, 0) + 1

    players = [{"name": n, "points": totals[n], "exactos": exactos.get(n, 0)}
               for n in totals]
    players.sort(key=lambda p: (-p["points"], -p["exactos"], p["name"]))
    return {
        "as_of": date.today().isoformat(),
        "you": you,
        "matches_resolved": len(resolved),
        "total_matches": 104,
        "total_participants": len(players),
        "_note": "Generado por ingest.pool_picks desde los exports de la app "
                 "(puntos de la app + exactos contados de Puntos==2). "
                 "Leaderboard completo: sin field_baseline.",
        "players": players,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest pool app CSV exports (real picks).")
    parser.add_argument("csvs", nargs="+", help="round export CSVs (filename must hint the round)")
    parser.add_argument("--you", default="Claudio", help="your player name in the app")
    parser.add_argument("--set-result", action="append", default=[],
                        metavar="'Local vs Visitante=h-a'",
                        help="90' result for a match the export lists as Pendiente "
                             "(Spanish names, app order). Repeatable.")
    args = parser.parse_args()

    overrides: dict[frozenset, tuple[int, int]] = {}
    for spec in args.set_result:
        partido, _, score_txt = spec.partition("=")
        es_home, _, es_away = partido.strip().partition(" vs ")
        score = _parse_score(score_txt)
        if score is None:
            raise SystemExit(f"Bad --set-result score: {spec!r}")
        overrides[frozenset((team_en(es_home), team_en(es_away)))] = score

    rules = DEFAULT_CONFIG.rules
    rounds: list[dict] = []
    for csv_path in args.csvs:
        path = Path(csv_path)
        spec = round_from_filename(path)
        rd = parse_export(path, spec, result_overrides=overrides)
        n_players = len(rd["picks"])
        n_res = sum(1 for r in rd["results"].values() if r is not None)
        print(f"  {path.name}: round={spec}, {len(rd['results'])} matches "
              f"({n_res} resolved), {n_players} players")
        rounds.append(rd)

    # --- pool_picks.json ---
    players_all: dict[str, dict[str, str]] = {}
    results_all: dict[str, tuple[int, int]] = {}
    rounds_map: dict[str, list[str]] = {}
    for rd in rounds:
        rounds_map[rd["round"]] = sorted(rd["results"].keys())
        for mid, res in rd["results"].items():
            if res is not None:
                results_all[mid] = res
        for player, per_match in rd["picks"].items():
            for mid, (h, a) in per_match.items():
                players_all.setdefault(player, {})[mid] = f"{h}-{a}"

    picks_dst = WC_DIR / "pool_picks.json"
    with picks_dst.open("w", encoding="utf-8") as f:
        json.dump({
            "as_of": date.today().isoformat(),
            "you": args.you,
            "rounds": rounds_map,
            "results": {mid: f"{h}-{a}" for mid, (h, a) in sorted(results_all.items())},
            "players": {n: dict(sorted(v.items())) for n, v in sorted(players_all.items())},
        }, f, indent=2, ensure_ascii=False)
    print(f"  wrote {picks_dst} ({len(players_all)} players, "
          f"{sum(len(v) for v in players_all.values())} picks)")

    n_fx = merge_results_into_fixtures(results_all)
    print(f"  merged {len(results_all)} results into fixtures.json ({n_fx} updated)")

    standings = recompute_standings(rounds, args.you, rules)
    st_dst = WC_DIR / "pool_standings.json"
    with st_dst.open("w", encoding="utf-8") as f:
        json.dump(standings, f, indent=2, ensure_ascii=False)
    top = standings["players"][:5]
    print(f"  wrote {st_dst} ({standings['matches_resolved']} resolved): " +
          "; ".join(f"{p['name']} {p['points']}pts/{p['exactos']}ex" for p in top))


if __name__ == "__main__":
    main()
