"""Tests de las variantes del modelo: momios previos, xG, prior de ascendidos."""
from __future__ import annotations

import csv
import io

import pytest

from wc_predictor.config import ModelConfig
from wc_predictor.ingest import europa_fd as fd
from wc_predictor.ingest import understat_xg as us
from wc_predictor.liga.europa import promoted_prior, replay_promoted, season_turnover, with_xg
from wc_predictor.model.poisson_dc import fit_dc_model


def _rows():
    teams = ["A", "B", "C", "D"]
    out, day = [], 1
    for rep in range(6):
        for h in teams:
            for a in teams:
                if h != a:
                    hs = 2 if h == "A" else 1
                    out.append({"date": f"2025-0{1 + rep}-{day % 28 + 1:02d}", "home": h, "away": a,
                                "home_score": hs, "away_score": 1 if a == "A" else 0,
                                "neutral": False, "tournament": "liga", "season": "2425",
                                "league": "E0"})
                    day += 1
    return out


def test_ingest_keeps_closing_and_prematch_lines():
    hdr = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,PSH,PSD,PSA,AvgH,AvgD,AvgA,PSCH,PSCD,PSCA,"
           "AvgCH,AvgCD,AvgCA,AvgC>2.5,AvgC<2.5,Avg>2.5,Avg<2.5,AHh,AHCh,AvgAHH,AvgAHA,AvgCAHH,AvgCAHA")
    line = ("E0,16/08/2025,20:00,Liverpool,Bournemouth,4,2,1.4,5,7,1.38,4.8,6.8,1.3,6,9.5,1.28,5.8,9,"
            "1.42,2.8,1.5,2.6,-1.5,-1.75,1.9,1.95,1.92,1.93")
    r = fd.normalize_rows(list(csv.DictReader(io.StringIO(hdr + "\n" + line + "\n"))), "E0", "2526")[0]
    assert r["avg_o1"] == 1.28 and r["avg_o1_pre"] == 1.38          # closing vs pre-match
    assert r["ah_line"] == -1.75 and r["ah_line_pre"] == -1.5
    assert r["fair_p1_pre"] < r["fair_p1"]                           # the line moved toward Liverpool
    assert r["avg_over25_pre"] == 1.5


def test_xg_target_changes_fit_and_default_is_identical():
    rows, cfg = _rows(), ModelConfig()
    base = fit_dc_model(rows, cfg, verbose=False, rho=-0.1)
    same = fit_dc_model([{**r, "home_target": r["home_score"], "away_target": r["away_score"]}
                         for r in rows], cfg, verbose=False, rho=-0.1)
    assert base.final_neg_log_lik == pytest.approx(same.final_neg_log_lik)
    # pretend D created a lot more than it scored → its attack goes up
    xg = [{**r, "home_target": r["home_score"] + (1.5 if r["home"] == "D" else 0)} for r in rows]
    shifted = fit_dc_model(xg, cfg, verbose=False, rho=-0.1)
    assert shifted.strengths["D"].attack > base.strengths["D"].attack


def test_prior_pulls_a_team_toward_its_center():
    rows, cfg = _rows(), ModelConfig()
    base = fit_dc_model(rows, cfg, verbose=False, rho=-0.1, ridge_lambda=5.0)
    pulled = fit_dc_model(rows, cfg, verbose=False, rho=-0.1, ridge_lambda=5.0,
                          prior={"B": (-1.0, -1.0)})
    assert pulled.strengths["B"].attack < base.strengths["B"].attack


def test_turnover_and_promoted_elo_start():
    teams = {"2324": {"A", "B", "Z"}, "2425": {"A", "B", "N"}}
    t = season_turnover(teams)
    assert t["2425"] == ({"N"}, {"Z"})
    rows = [  # Z loses everything in 23/24, N arrives in 24/25
        {"season": "2324", "home": "A", "away": "Z", "home_score": 3, "away_score": 0, "neutral": False, "tournament": "liga"},
        {"season": "2324", "home": "B", "away": "Z", "home_score": 2, "away_score": 0, "neutral": False, "tournament": "liga"},
        {"season": "2425", "home": "N", "away": "A", "home_score": 0, "away_score": 0, "neutral": False, "tournament": "liga"},
    ]
    from wc_predictor.ratings.elo import replay_history
    plain, _ = replay_history(rows, ModelConfig())
    promo = replay_promoted(rows, ModelConfig(), t)
    assert promo["N"] < plain["N"]                 # N started at Z's (low) level, not 1500


def test_promoted_prior_uses_relegated_strengths():
    fit = fit_dc_model(_rows(), ModelConfig(), verbose=False, rho=-0.1)
    pr = promoted_prior(fit, {"2526": ({"N"}, {"D"})}, "2526")
    assert pr == {"N": (fit.strengths["D"].attack, fit.strengths["D"].defense)}
    assert promoted_prior(None, {}, "2526") is None


def test_understat_normalize_and_with_xg():
    doc = {"dates": [
        {"isResult": True, "h": {"title": "Manchester City"}, "a": {"title": "Wolverhampton Wanderers"},
         "goals": {"h": "1", "a": "0"}, "xG": {"h": "2.5", "a": "0.3"}, "datetime": "2025-08-16 14:00:00"},
        {"isResult": False, "h": {"title": "X"}, "a": {"title": "Y"}, "goals": {"h": None, "a": None},
         "xG": {"h": None, "a": None}, "datetime": "2026-12-01 14:00:00"}]}
    rows = us.normalize(doc, "EPL")
    assert rows == [{"league": "E0", "date": "2025-08-16", "home": "Man City", "away": "Wolves",
                     "home_goals": 1, "away_goals": 0, "xg_home": 2.5, "xg_away": 0.3}]
    m = [{"league": "E0", "date": "2025-08-17", "home": "Man City", "away": "Wolves",
          "home_score": 1, "away_score": 0}]
    out = with_xg(m, us.index(rows), 0.5)[0]
    assert out["home_target"] == pytest.approx(1.75) and out["away_target"] == pytest.approx(0.15)


def test_committed_xg_file_joins_history():
    idx = us.index(us.load())
    hist = fd.load()
    miss = sum(1 for r in hist if us.lookup(idx, r["league"], r["home"], r["away"], r["date"]) is None)
    assert miss <= 0.005 * len(hist)


def test_ingest_drops_corrupt_prices():
    hdr = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,AHh,AvgAHH,AvgAHA"
    line = "E0,29/11/2025,15:00,Everton,Newcastle,1,1,2.9,3.4,2.5,0,1.93,5.19"   # AHA corrupt
    r = fd.normalize_rows(list(csv.DictReader(io.StringIO(hdr + "\n" + line + "\n"))),
                          "E0", "2526")[0]
    assert r["ah_line_pre"] == "" and r["avg_aha_pre"] == ""
    assert r["avg_o1_pre"] == 2.9                       # the sane 1X2 survives
