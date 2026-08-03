"""Tracker de fuentes: log de 3 fuentes, liquidación 1X2 + puntos, y agregado."""
from __future__ import annotations

import json

from wc_predictor.pipeline import ligamx_source_tracker as T


def _seed(tmp_path, monkeypatch, entries):
    tracker = tmp_path / "source_tracker.json"
    tracker.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    monkeypatch.setattr(T, "TRACKER_JSON", tracker)
    return tracker


def _entry(match, home, away, model, blend, market, cong_h=False, cong_a=False):
    mk = lambda pick, exact=None: ({"pick": pick} if exact is None else {"pick": pick, "exact": exact})
    return {"round": "j4", "match": match, "home": home, "away": away,
            "commence_time": None,
            "model": {"pick": model[0], "exact": model[1], "p1": 0.5, "px": 0.25, "p2": 0.25},
            "blend": {"pick": blend[0], "exact": blend[1], "p1": 0.5, "px": 0.25, "p2": 0.25},
            "market": {"pick": market, "p1": 0.5, "px": 0.25, "p2": 0.25},
            "congested_home": cong_h, "congested_away": cong_a,
            "result": None, "home_score": None, "away_score": None}


def test_settle_scores_each_source_and_market_gets_no_exacto(tmp_path, monkeypatch):
    # A vs B ends 2-0 (home win). model nailed the exact; blend got 1X2 only; market picked away (miss).
    e = _entry("A vs B", "A", "B", model=("1", "2-0"), blend=("1", "1-0"), market="2")
    _seed(tmp_path, monkeypatch, [e])
    # fixtures + rules loaders
    fxdoc = {"matches": [{"home": "A", "away": "B", "home_score": 2, "away_score": 0}]}
    fxp = tmp_path / "fixtures.json"; fxp.write_text(json.dumps(fxdoc), encoding="utf-8")
    monkeypatch.setattr(T, "FIXTURES_JSON", fxp)
    from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE as P
    monkeypatch.setattr(T, "_load_model", lambda: (None, None, P.rules, None, None))

    T.cmd_settle()
    out = json.loads((tmp_path / "source_tracker.json").read_text())["entries"][0]
    assert out["result"] == "1"
    assert out["model"]["points"] == 2 and out["model"]["hit"] is True     # exacto
    assert out["blend"]["points"] == 1 and out["blend"]["hit"] is True      # 1X2 only
    assert out["market"]["points"] == 0 and out["market"]["hit"] is False   # wrong side


def test_market_cannot_score_an_exacto_even_if_scoreline_would_match(tmp_path, monkeypatch):
    # market pick "1" is correct 1X2; it must never earn the 2-pt exacto (no scoreline).
    e = _entry("A vs B", "A", "B", model=("1", "9-9"), blend=("1", "9-9"), market="1")
    _seed(tmp_path, monkeypatch, [e])
    fxdoc = {"matches": [{"home": "A", "away": "B", "home_score": 1, "away_score": 0}]}
    fxp = tmp_path / "fixtures.json"; fxp.write_text(json.dumps(fxdoc), encoding="utf-8")
    monkeypatch.setattr(T, "FIXTURES_JSON", fxp)
    from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE as P
    monkeypatch.setattr(T, "_load_model", lambda: (None, None, P.rules, None, None))
    T.cmd_settle()
    out = json.loads((tmp_path / "source_tracker.json").read_text())["entries"][0]
    assert out["market"]["points"] == 1     # only the 1X2 point, never 2


def test_agg_ranks_sources_and_splits_congestion(tmp_path, monkeypatch):
    settled = []
    # 3 matches, all home wins: market best (3/3 1X2), blend 2/3, model 1/3
    specs = [("1", "1", "1", "1"), ("1", "2", "1", "1"), ("1", "2", "2", "1")]
    #         result, model, blend, market
    for i, (res, mo, bl, mk) in enumerate(specs):
        e = _entry(f"H{i} vs A{i}", f"H{i}", f"A{i}", (mo, "9-9"), (bl, "9-9"), mk,
                   cong_h=(i == 0))
        e["result"] = res; e["home_score"], e["away_score"] = (1, 0) if res == "1" else (0, 1)
        e["model"]["hit"] = mo == res; e["model"]["points"] = 1 if mo == res else 0
        e["blend"]["hit"] = bl == res; e["blend"]["points"] = 1 if bl == res else 0
        e["market"]["hit"] = mk == res; e["market"]["points"] = 1 if mk == res else 0
        settled.append(e)
    a = T._agg(settled)
    assert a["sources"]["market"]["hit_1x2"] == 3
    assert a["sources"]["blend"]["hit_1x2"] == 2
    assert a["sources"]["model"]["hit_1x2"] == 1
    assert a["congestion"]["n_cong"] == 1 and a["congestion"]["n_non"] == 2
