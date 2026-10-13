"""Copas UEFA en la liga de Europa: ingest de momios, nombres y sellado por partes."""
from __future__ import annotations

import functools
from datetime import datetime, timezone

import pytest

from wc_predictor.ingest.uefa_odds import parse_event
from wc_predictor.liga import seal
from wc_predictor.liga.europa import EUROPA_MODEL, cup_team_name, market_view
from wc_predictor.pipeline import europa_live

KNOWN = {"Inter", "Milan", "Man City", "Paris SG", "La Coruna", "Liverpool", "Ath Madrid",
         "Man United", "Bayern Munich", "Roma"}


def _ev(home="Inter Milan", away="Club Brugge", totals=True):
    def book(o1, ox, o2):
        mk = [{"key": "h2h", "outcomes": [{"name": home, "price": o1}, {"name": "Draw", "price": ox},
                                         {"name": away, "price": o2}]}]
        if totals:
            mk.append({"key": "totals", "outcomes": [{"name": "Over", "price": 1.6, "point": 2.5},
                                                     {"name": "Under", "price": 2.3, "point": 2.5}]})
        return {"markets": mk}
    return {"commence_time": "2026-10-13T19:00:00Z", "home_team": home, "away_team": away,
            "bookmakers": [book(1.25, 6.5, 11.0), book(1.27, 6.2, 10.5)]}


@pytest.mark.parametrize("raw,want", [
    ("Inter Milan", "Inter"), ("AC Milan", "Milan"), ("Manchester City", "Man City"),
    ("Paris Saint Germain", "Paris SG"), ("Atlético Madrid", "Ath Madrid"),
    ("Liverpool", "Liverpool"), ("Bayern Munich", "Bayern Munich"),
    ("LASK", "LASK"), ("Club Brugge", "Club Brugge"),   # foreign clubs keep their name
])
def test_cup_team_name(raw, want):
    assert cup_team_name(raw, KNOWN) == want


def test_parse_event_devigs_and_averages():
    r = parse_event("UCL", _ev())
    assert r["league"] == "UCL" and r["date"] == "2026-10-13"
    assert r["kickoff_utc"] == "2026-10-13T19:00:00+00:00"
    assert r["fair_p1"] + r["fair_px"] + r["fair_p2"] == pytest.approx(1.0, abs=1e-3)
    assert r["avg_o1"] == pytest.approx(1.26) and r["n_books"] == 2
    assert 0.55 < r["fair_over25"] < 0.62 and r["ah_line"] is None
    assert parse_event("UCL", {**_ev(), "bookmakers": []}) is None


def test_market_view_follows_the_market():
    v = market_view((0.77, 0.14, 0.09), 0.75, EUROPA_MODEL)
    assert v.probs[0] == pytest.approx(0.77, abs=0.01) and v.pick_1x2 == "1"
    assert v.p_over25 == pytest.approx(0.75)
    assert market_view((0.3, 0.3, 0.4), None, EUROPA_MODEL).pick_1x2 in "12X"


def test_cup_matches_only_top3_and_estadistico_sits_out():
    fx = [parse_event("UCL", _ev()), parse_event("UCL", _ev("LASK", "Club Brugge"))]
    out = europa_live.cup_matches(fx, {"I1": ["Inter", "Roma", "Napoli"]}, KNOWN,
                                  {"estadistico": 0.0, "calibrado": 0.9, "borrego": 1.0})
    assert [(m["home"], m["away"]) for m in out] == [("Inter", "Club Brugge")]
    assert "error" in out[0]["bots"]["estadistico"]
    assert out[0]["bots"]["calibrado"]["pick_1x2"] == "1" and out[0]["top"]


def test_seal_bots_adds_new_matches_as_a_second_part(tmp_path, monkeypatch):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(seal, "append", functools.partial(seal.append, path=led))
    read = seal.read_ledger
    monkeypatch.setattr(seal, "read_ledger", lambda *_a, **_k: read(led))
    entry = {"pick_1x2": "1", "pick_exact": "1-0", "p1x2": [0.5, 0.3, 0.2], "p_over25": 0.5,
             "p_btts": 0.5, "value_bets": []}

    def m(h, d):
        return {"home": h, "away": "Z", "league": "UCL", "date": d,
                "kickoff_utc": f"{d}T19:00+00:00", "bots": {"borrego": entry}}
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    europa_live.seal_bots({"bots": ["borrego"], "matches": [m("A", "2026-10-13")]}, "eu-2026-W42", now)
    recs = europa_live.seal_bots({"bots": ["borrego"], "matches": [m("A", "2026-10-13"),
                                                                   m("B", "2026-10-17")]},
                                 "eu-2026-W42", now)
    assert recs[0]["round"] == "eu-2026-W42/2" and [p["home"] for p in recs[0]["picks"]] == ["B"]
    assert europa_live.seal_bots({"bots": ["borrego"], "matches": [m("B", "2026-10-17")]},
                                 "eu-2026-W42", now) == []
