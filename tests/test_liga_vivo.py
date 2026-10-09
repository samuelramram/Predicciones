"""Tests del Notario (boleto humano) y del Árbitro (calificación en vivo)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wc_predictor.ingest.europa_fd import kickoff_utc
from wc_predictor.liga import arbitro, notario, seal

RND = {"round_id": "eu-2026-W41", "matches": [
    {"n": 1, "league": "D1", "date": "2026-10-09", "kickoff_utc": "2026-10-09T18:30+00:00",
     "home": "Dortmund", "away": "Werder Bremen"},
    {"league": "D1", "date": "2026-10-10", "kickoff_utc": "2026-10-10T13:30+00:00",
     "home": "Hoffenheim", "away": "Hamburg"},                      # not on Samuel's ticket
    {"n": 2, "league": "E0", "date": "2026-10-11", "kickoff_utc": "2026-10-11T15:30+00:00",
     "home": "Liverpool", "away": "Man City"},
]}
BEFORE = datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)
BETWEEN = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def test_kickoff_utc_handles_bst_and_gmt():
    assert kickoff_utc("09/10/2026", "19:30") == "2026-10-09T18:30+00:00"   # BST
    assert kickoff_utc("05/12/2026", "15:00") == "2026-12-05T15:00+00:00"   # GMT
    assert kickoff_utc("05/12/2026", "") == ""


def test_parse_picks():
    assert notario.parse_picks("2-1, 0-2,-,\n1:3") == [(2, 1), (0, 2), None, (1, 3)]
    with pytest.raises(ValueError):
        notario.parse_picks("gana el Liverpool")


def test_ticket_maps_numbers_skips_and_blocks_started_matches():
    t, msgs = notario.build_ticket(RND, [(2, 1), (1, 2)], [], "samuel", BETWEEN)
    assert [p["home"] for p in t] == ["Liverpool"]          # Dortmund already kicked off
    assert t[0]["pick_1x2"] == "2" and t[0]["pick_exact"] == "1-2"
    assert any("ya empezó" in m for m in msgs)
    t, _ = notario.build_ticket(RND, [None, (0, 0)], [], "samuel", BEFORE)
    assert [(p["home"], p["pick_1x2"]) for p in t] == [("Liverpool", "X")]
    with pytest.raises(ValueError):
        notario.build_ticket(RND, [(1, 0)] * 3, [], "samuel", BEFORE)


def test_ticket_in_parts_never_changes_a_sealed_match(tmp_path):
    led = tmp_path / "l.jsonl"
    first, _ = notario.build_ticket(RND, [(2, 1)], [], "samuel", BEFORE)
    seal.append(notario.next_part([], "eu-2026-W41", "samuel"), "samuel", first, path=led)
    recs = seal.read_ledger(led)
    again, msgs = notario.build_ticket(RND, [(0, 0), (1, 1)], recs, "samuel", BEFORE)
    assert [p["home"] for p in again] == ["Liverpool"]
    assert any("ya lo tenías" in m for m in msgs)
    assert notario.next_part(recs, "eu-2026-W41", "samuel") == "eu-2026-W41/2"


@pytest.mark.parametrize("bet,score,profit", [
    ({"market": "1x2", "side": "1", "price": 2.0}, (2, 1), 10.0),
    ({"market": "1x2", "side": "X", "price": 3.5}, (2, 1), -10.0),
    ({"market": "ou25", "side": "over2.5", "price": 1.9}, (2, 1), 9.0),
    ({"market": "ou25", "side": "under2.5", "price": 2.0}, (2, 1), -10.0),
    ({"market": "ah", "side": "home -1.5", "price": 2.0}, (2, 1), -10.0),
    ({"market": "ah", "side": "away +1.5", "price": 2.0}, (2, 1), 10.0),
    ({"market": "ah", "side": "home -1", "price": 2.0}, (2, 1), 0.0),      # push
])
def test_settle_bet(bet, score, profit):
    assert arbitro.settle_bet(bet, *score) == pytest.approx(profit)


def test_table_mano_a_mano_only_on_samuels_matches():
    k1 = ("D1", "Dortmund", "Werder Bremen", "2026-10-09")
    k2 = ("D1", "Hoffenheim", "Hamburg", "2026-10-10")
    bot_pick = {"p1x2": [0.6, 0.25, 0.15], "p_over25": 0.6, "p_btts": 0.5, "value_bets": []}
    picks = {
        "samuel": {k1: {"league": "D1", "home": "Dortmund", "away": "Werder Bremen",
                        "date": "2026-10-09", "pick_1x2": "1", "pick_exact": "2-1"}},
        "calibrado": {
            k1: {"league": "D1", "home": "Dortmund", "away": "Werder Bremen", "date": "2026-10-09",
                 "pick_1x2": "1", "pick_exact": "2-0", **bot_pick},
            k2: {"league": "D1", "home": "Hoffenheim", "away": "Hamburg", "date": "2026-10-10",
                 "pick_1x2": "1", "pick_exact": "1-0", **bot_pick}},
    }
    idx = arbitro.results_index([
        {"league": "D1", "home": "Dortmund", "away": "Werder Bremen", "date": "2026-10-10",
         "home_score": 2, "away_score": 1},       # UK-date shift of one day still matches
    ])
    t = arbitro.build_table(arbitro.score(picks, idx))
    assert t["mano_a_mano"]["samuel"] == {"n": 1, "points": 2, "exactos": 1}
    assert t["mano_a_mano"]["calibrado"]["points"] == 1
    assert t["bots"]["calibrado"]["n"] == 1 and t["bots"]["calibrado"]["pendientes"] == 1
    assert "Mano a mano" in arbitro.render_md(t)


TICKET = {"round_id": "eu-2026-W41", "matches": [
    {"n": 1, "league": "E0", "home": "Arsenal", "away": "Leeds"},
    {"n": 2, "league": "D1", "home": "Augsburg", "away": "Bayern Munich"},
    {"n": 3, "league": "SP1", "home": "Alaves", "away": "Ath Madrid"},
    {"n": 4, "league": "SP1", "home": "Real Madrid", "away": "Villarreal"},
    {"n": 5, "league": "E0", "home": "Liverpool", "away": "Man City"},
]}


def test_named_picks_like_telegram():
    got = notario.read_picks("Arsenal 2-0 Leeds, Bayern 2-0, Atlético 3-1, Madrid 2-0, City 2-1", TICKET)
    assert got == [(2, 0), (0, 2), (1, 3), (2, 0), (1, 2)]
    # numbered lines, accents, and leaving some out
    assert notario.read_picks("5. Man City 1-1\n2) Bayern 3-1", TICKET) == [None, (1, 3), None, None, (1, 1)]
    assert notario.read_picks("Leeds 1-2 Arsenal", TICKET) == [(2, 1)]
    with pytest.raises(ValueError):
        notario.read_picks("Getafe 1-0", TICKET)           # not on the ticket
    with pytest.raises(ValueError):
        notario.read_picks("Madrid 1-0", {"round_id": "x", "matches": [
            {"n": 1, "league": "SP1", "home": "Real Madrid", "away": "Getafe"},
            {"n": 2, "league": "SP1", "home": "Alaves", "away": "Real Madrid"}]})  # ambiguous
    assert notario.read_picks("2-1, -, 0-0", TICKET) == [(2, 1), None, (0, 0)]   # positional still works


NLF = ("Country,League,Date,Time,Home,Away,PSH,PSD,PSA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA\n"
       "Mexico,Liga MX,10/10/2026,02:00,Puebla,Club Leon,,,,2.9,3.4,2.45,2.78,3.28,2.35\n"
       "Mexico,Liga MX,11/10/2026,04:10,Club America,Monterrey,1.9,3.7,4.3,1.9,3.7,4.2,1.85,3.58,3.74\n"
       "Argentina,Liga Profesional,09/10/2026,18:30,Aldosivi,Sarmiento Junin,,,,2.65,3.1,3.1,2.55,2.97,2.88\n")


def test_ligamx_upcoming_maps_names_and_mexico_time():
    from wc_predictor.pipeline.ligamx_live import upcoming
    fx, unmapped = upcoming(NLF)
    assert not unmapped and [f["home"] for f in fx] == ["Puebla", "América"]
    pue = fx[0]
    assert pue["away"] == "León" and pue["kickoff_utc"] == "2026-10-10T01:00+00:00"
    assert pue["date"] == "2026-10-09"                       # Friday night in Mexico
    assert sum(pue["fair"]) == pytest.approx(1.0) and pue["avg"] == [2.78, 3.28, 2.35]
    assert fx[1]["fair"][0] > 0.5                              # Pinnacle used when present


def test_named_picks_liga_mx_nicknames():
    t = {"round_id": "mx-2026-J11", "matches": [
        {"n": 1, "league": "MX", "home": "Atlas", "away": "Guadalajara"},
        {"n": 2, "league": "MX", "home": "América", "away": "Monterrey"},
        {"n": 3, "league": "MX", "home": "Pumas", "away": "Cruz Azul"}]}
    assert notario.read_picks("Chivas 2-1, America 1-0, la maquina 2-0", t) == [(1, 2), (1, 0), (0, 2)]


def test_arbitro_skips_goal_brier_when_bot_has_no_goal_model():
    k = ("MX", "Puebla", "León", "2026-10-09")
    picks = {"borrego": {k: {"league": "MX", "home": "Puebla", "away": "León", "date": "2026-10-09",
                             "pick_1x2": "2", "pick_exact": "1-2", "p1x2": [0.33, 0.28, 0.39],
                             "p_over25": None, "p_btts": None, "value_bets": []}}}
    idx = arbitro.results_index([{"league": "MX", "home": "Puebla", "away": "León",
                                  "date": "2026-10-10", "home_score": 1, "away_score": 2}])
    t = arbitro.build_table(arbitro.score(picks, idx))
    b = t["bots"]["borrego"]
    assert b["points"] == 2 and b["brier_ou25"] == 0.0 and b["n"] == 1
