"""Respaldo cuando Football-Data aún no publica la jornada (Odds API + calendario)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from wc_predictor.ingest import uefa_odds
from wc_predictor.pipeline import europa_live, ligamx_live


def _row(league, home, away, d="2026-10-17"):
    return {"league": league, "date": d, "kickoff_utc": f"{d}T14:00:00+00:00", "home": home,
            "away": away, "fair_p1": 0.5, "fair_px": 0.27, "fair_p2": 0.23, "avg_o1": 1.9,
            "avg_ox": 3.5, "avg_o2": 4.1, "fair_over25": 0.55, "avg_over25": 1.8,
            "avg_under25": 2.0, "ah_line": None, "avg_ahh": None, "avg_aha": None, "n_books": 5}


def test_missing_leagues_reads_both_fd_files(tmp_path):
    (tmp_path / "fixtures.csv").write_text(
        "Div,Date,Time,HomeTeam,AwayTeam\nE0,17/10/2026,12:30,Arsenal,Chelsea\n"
        "SP1,25/10/2026,20:00,Betis,Sevilla\n", encoding="utf-8")
    (tmp_path / "fixtures_new.csv").write_text(
        "Country,League,Date,Time,Home,Away\nMexico,Liga MX,17/10/2026,01:00,Necaxa,Atlas\n",
        encoding="utf-8")
    miss = uefa_odds.missing_leagues(tmp_path, today=date(2026, 10, 16))
    assert miss == ["SP1", "I1", "D1", "F1"]   # E0 y MX ya los trae FD; SP1 queda fuera de 4 días


def test_league_fallback_maps_names_and_fd_wins():
    hist = [{"league": "E0", "season": "2526", "home": "Man City", "away": "Arsenal"},
            {"league": "E0", "season": "2526", "home": "Liverpool", "away": "Chelsea"}]
    fd_rows = [{**_row("E0", "Liverpool", "Chelsea"), "neutral": False}]
    extra = [_row("E0", "Manchester City", "Arsenal"), _row("E0", "Liverpool", "Chelsea"),
             _row("E0", "Sunderland FC", "Arsenal"), _row("I1", "Inter Milan", "Juventus")]
    out, dropped = europa_live.league_fallback(fd_rows, extra, hist)
    pairs = [(f["home"], f["away"]) for f in out]
    assert pairs == [("Liverpool", "Chelsea"), ("Man City", "Arsenal")]
    assert dropped == ["Sunderland FC vs Arsenal"]   # sin modelo: fuera, y se reporta


def test_calendar_fallback_next_jornada_with_prices(tmp_path, monkeypatch):
    doc = {"matches": [
        {"stage": "regular", "jornada": 11, "date_utc": "2026-10-10T23:00:00", "home": "Necaxa",
         "away": "Atlas", "home_score": 1},
        {"stage": "regular", "jornada": 12, "date_utc": "2026-10-17T01:00:00", "home": "Necaxa",
         "away": "Atlas", "home_score": None},
        {"stage": "regular", "jornada": 12, "date_utc": "2026-10-18T01:00:00", "home": "León",
         "away": "América", "home_score": None},
        {"stage": "regular", "jornada": 13, "date_utc": "2026-10-21T01:00:00", "home": "Atlas",
         "away": "León", "home_score": None}]}
    (tmp_path / "fixtures.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(ligamx_live, "LIGAMX_DIR", tmp_path)
    now = datetime(2026, 10, 16, 3, tzinfo=timezone.utc)
    out = ligamx_live.calendar_fallback(now, odds_rows=[_row("MX", "Necaxa", "Atlas")])
    assert [(f["home"], f["away"]) for f in out] == [("Necaxa", "Atlas"), ("León", "América")]
    assert out[0]["fair"] == [0.5, 0.27, 0.23] and out[0]["date"] == "2026-10-16"  # hora de CDMX
    assert out[1]["fair"] is None


def test_round_without_odds_still_written_only_estadistico_plays():
    # J13 (oct 2026): sin momios en ningún partido el script abortaba antes de escribir
    # la jornada y el Notario no tenía dónde sellar el boleto de Samuel.
    fx = [{"league": "MX", "date": "2026-10-21", "kickoff_utc": "2026-10-22T01:00:00+00:00",
           "home": "Atlas", "away": "América", "fair": None, "avg": None}]
    rnd = ligamx_live.build_round(fx, w_aprendiz=0.6)
    bots = rnd["matches"][0]["bots"]
    assert "pick_exact" in bots["estadistico"]
    assert all("error" in bots[b] for b in ("calibrado", "aprendiz", "borrego"))
