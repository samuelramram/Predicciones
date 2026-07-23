"""Ingest the pool webapp's per-jornada CSV exports for Liga MX.

Simpler than the WC `ingest.pool_picks`: Liga MX regular-season results come
from TheSportsDB (already merged into fixtures.json by `ingest.ligamx`), so the
knockout extra-time result-inference machinery isn't needed here — we only read
players' picks and their app points to build the leaderboard.

Export columns (same Lovable app as the WC):

    Usuario,Partido,Predicción,Resultado Real,Puntos

- `Partido` is "Local vs Visitante" in app display order (may be flipped vs
  fixtures.json). Team names are resolved to the canonical `name_es` via
  teams.json (accepts full name, name_es or short).
- `Puntos` is the app's own scoring (2 exact / 1 result / 0).

Round is inferred from the filename (`j1`..`j17`).

Outputs (versioned, shape consumed by model.standings / model.pool_optimizer):
    data/ligamx/pool_picks.json      real picks per player per match_id
    data/ligamx/pool_standings.json  leaderboard (points + exactos)

Usage:
    python -m wc_predictor.ingest.ligamx_pool data/ligamx/pool_exports/*.csv --you Samuel
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

from wc_predictor.pipeline.ligamx import FIXTURES_JSON, TEAMS_JSON, POOL_PICKS_JSON, POOL_STANDINGS_JSON


def _name_resolver() -> dict[str, str]:
    """Any known spelling (name / name_es / short, case-insensitive) → name_es."""
    teams = json.loads(TEAMS_JSON.read_text(encoding="utf-8"))["teams"]
    m: dict[str, str] = {}
    for t in teams:
        for key in (t["name"], t["name_es"], t["short"]):
            m[key.strip().lower()] = t["name_es"]
    return m


def resolve_team(raw: str, resolver: dict[str, str]) -> str:
    return resolver.get((raw or "").strip().lower(), (raw or "").strip())


def round_from_filename(path: Path) -> int:
    m = re.search(r"j(\d{1,2})", path.name.lower())
    if not m:
        raise SystemExit(f"No puedo inferir la jornada del nombre {path.name!r}; "
                         f"inclúyela como j1..j17.")
    return int(m.group(1))


def _parse_score(txt: str) -> tuple[int, int] | None:
    txt = (txt or "").strip()
    if not txt or txt.lower() == "pendiente":
        return None
    h, sep, a = txt.partition("-")
    if not sep or not h.strip().isdigit() or not a.strip().isdigit():
        return None
    return int(h.strip()), int(a.strip())


def _fixture_index(jornada: int) -> dict[frozenset, dict]:
    doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    return {frozenset((m["home"], m["away"])): m
            for m in doc["matches"] if m.get("jornada") == jornada}


def parse_export(path: Path, resolver: dict[str, str]) -> dict:
    """Parse one jornada export → {picks, points} keyed by player and match_id,
    oriented to each fixture's home/away."""
    jornada = round_from_filename(path)
    index = _fixture_index(jornada)
    picks: dict[str, dict[str, str]] = {}
    points: dict[str, dict[str, int | None]] = {}
    unmatched: set[str] = set()

    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            es_home, _, es_away = row["Partido"].partition(" vs ")
            home, away = resolve_team(es_home, resolver), resolve_team(es_away, resolver)
            fx = index.get(frozenset((home, away)))
            if fx is None:
                unmatched.add(row["Partido"].strip())
                continue
            flipped = fx["home"] == away
            pred = _parse_score(row.get("Predicción", ""))
            if pred is not None and flipped:
                pred = (pred[1], pred[0])
            mid = fx["match_id"]
            player = row["Usuario"].strip()
            pts_txt = (row.get("Puntos") or "").strip()
            pts = int(pts_txt) if pts_txt.lstrip("-").isdigit() else None
            if pred is not None:
                picks.setdefault(player, {})[mid] = f"{pred[0]}-{pred[1]}"
            points.setdefault(player, {})[mid] = pts

    if unmatched:
        print(f"  WARNING [{path.name}]: sin fixture para: {sorted(unmatched)}")
    return {"jornada": jornada, "picks": picks, "points": points}


def build_standings(rounds: list[dict], you: str, total_matches: int) -> dict:
    totals: dict[str, int] = {}
    exactos: dict[str, int] = {}
    resolved: set[str] = set()
    for rd in rounds:
        for per_match in rd["points"].values():
            for mid, pts in per_match.items():
                if pts is not None:
                    resolved.add(mid)
        for player, per_match in rd["points"].items():
            for mid, pts in per_match.items():
                if pts is None:
                    continue
                totals[player] = totals.get(player, 0) + pts
                if pts >= 2:  # exact-score points
                    exactos[player] = exactos.get(player, 0) + 1
    players = [{"name": n, "points": totals[n], "exactos": exactos.get(n, 0)} for n in totals]
    players.sort(key=lambda p: (-p["points"], -p["exactos"], p["name"]))
    return {
        "as_of": date.today().isoformat(),
        "you": you,
        "matches_resolved": len(resolved),
        "total_matches": total_matches,
        "total_participants": len(players),
        "players": players,
    }


def pool_total_matches(start_round: int, liguilla_matches: int) -> int:
    """How many matches the POOL will score in total — the horizon anchor for
    the P(1.º) optimizer. The pool starts at `start_round` (J1/J2 are never
    scored when the pool joined late) and runs through the liguilla, whose
    fixtures don't exist yet in fixtures.json, so their count is passed in.
    Counting the full 153-match calendar here (the old behaviour) overstated
    the horizon and biased the optimizer toward playing it too safe."""
    doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    regular = sum(1 for m in doc["matches"] if (m.get("jornada") or 0) >= start_round)
    return regular + liguilla_matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest exports del pool Liga MX.")
    parser.add_argument("csvs", nargs="+", help="CSVs por jornada (nombre con j1..j17).")
    parser.add_argument("--you", default="Samuel", help="tu nombre en la app.")
    parser.add_argument("--start-round", type=int, default=3,
                        help="primera jornada que la quiniela puntúa (default 3: "
                             "este pool arrancó en la J3; J1-J2 no cuentan).")
    parser.add_argument("--liguilla-matches", type=int, default=17,
                        help="partidos de liguilla que puntuará la quiniela (default 17: "
                             "3 de reclasificación + 8 QF + 4 SF + 2 final; ajusta si "
                             "la app no puntúa la reclasificación → 14).")
    args = parser.parse_args()

    resolver = _name_resolver()
    total_matches = pool_total_matches(args.start_round, args.liguilla_matches)
    print(f"  pool: puntúa desde J{args.start_round} → total {total_matches} partidos "
          f"({total_matches - args.liguilla_matches} de regular + "
          f"{args.liguilla_matches} de liguilla)")

    rounds = [parse_export(Path(p), resolver) for p in args.csvs]
    for rd, p in zip(rounds, args.csvs):
        print(f"  {Path(p).name}: J{rd['jornada']}, {len(rd['picks'])} jugadores")

    # pool_picks.json
    players_all: dict[str, dict[str, str]] = {}
    for rd in rounds:
        for player, per_match in rd["picks"].items():
            players_all.setdefault(player, {}).update(per_match)
    POOL_PICKS_JSON.write_text(json.dumps({
        "as_of": date.today().isoformat(), "you": args.you,
        "players": {n: dict(sorted(v.items())) for n, v in sorted(players_all.items())},
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {POOL_PICKS_JSON} ({len(players_all)} jugadores)")

    # pool_standings.json
    standings = build_standings(rounds, args.you, total_matches)
    POOL_STANDINGS_JSON.write_text(json.dumps(standings, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    top = standings["players"][:5]
    print(f"  wrote {POOL_STANDINGS_JSON} ({standings['matches_resolved']} resueltos): " +
          "; ".join(f"{p['name']} {p['points']}/{p['exactos']}ex" for p in top))


if __name__ == "__main__":
    main()
