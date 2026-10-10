from datetime import date

import pytest

from wc_predictor.liga import tablero


def _pick(home, away, d, bets=(), exact="1-0", lg="E0"):
    return {"league": lg, "home": home, "away": away, "date": d, "pick_1x2": "1",
            "pick_exact": exact, "p1x2": [0.5, 0.3, 0.2], "p_over25": 0.5, "p_btts": 0.5,
            "value_bets": list(bets)}


def _res(home, away, d, hs, as_, **kw):
    return {"league": kw.pop("league", "E0"), "home": home, "away": away, "date": d,
            "home_score": hs, "away_score": as_, "fair_p1": 0.5, "fair_px": 0.3, "fair_p2": 0.2,
            "fair_over25": 0.55, **kw}


BET1 = {"market": "1x2", "side": "1", "price": 2.2, "edge": 0.1}
BET_OU = {"market": "ou25", "side": "under2.5", "price": 2.0, "edge": 0.05}


def test_closing_prob_and_clv():
    r = _res("A", "B", "2026-10-10", 2, 0, ah_line=-0.5, avg_ahh=1.9, avg_aha=1.9)
    assert tablero.closing_prob(BET1, r) == 0.5
    assert tablero.closing_prob(BET_OU, r) == pytest.approx(0.45)
    assert tablero.closing_prob({"market": "ah", "side": "home -0.5", "price": 2}, r) == pytest.approx(0.5)
    # line moved → no comparable close
    assert tablero.closing_prob({"market": "ah", "side": "home -1", "price": 2}, r) is None
    row = tablero.bet_row(BET1, {**_pick("A", "B", "2026-10-10"), "round": "eu-x"}, r)
    assert row["clv"] == pytest.approx(2.2 * 0.5 - 1)
    assert row["profit"] == pytest.approx(10 * 1.2)


def test_build_wallets_and_points():
    records = [
        {"round": "eu-2026-W41", "bot": "estadistico",
         "picks": [_pick("A", "B", "2026-10-10", [BET1, BET_OU]), _pick("C", "D", "2026-10-11", [BET1])]},
        {"round": "eu-2026-W41", "bot": "calibrado",
         "picks": [_pick("A", "B", "2026-10-10"), _pick("C", "D", "2026-10-11")]},
        {"round": "eu-2026-W41/2", "bot": "samuel",
         "picks": [_pick("A", "B", "2026-10-10", exact="2-0")]},
    ]
    results = [_res("A", "B", "2026-10-10", 2, 0)]          # C–D still pending
    d = tablero.build(records, results, date(2026, 10, 12))
    est = next(w for w in d["wallets"] if w["who"] == "estadistico")
    # A–B: home win at 2.2 (+12), under 2.5 wins at 2.0 (+10); C–D pending
    assert est["balance"] == pytest.approx(1022)
    assert est["n"] == 2 and est["pending_bets"] == 1
    assert est["expected"] == pytest.approx(1.5)
    assert d["rounds"][0]["done"] == 1 and d["rounds"][0]["total"] == 2
    sam = next(p for p in d["people"] if p["who"] == "samuel")
    assert sam["points"] == 2 and sam["exactos"] == 1
    assert all("samuel" != w["who"] for w in d["wallets"])
    html = tablero.render_html(d)
    assert "1,022" in html and "<svg" in html
    assert "estadistico: 1,022" in tablero.render_md(d)


def test_verdict_reads_the_close():
    bad = [{"market": "1x2", "profit": -10, "clv": -0.08, "edge": 0.1, "price": 2.0, "p_close": 0.46,
            "league": "E0", "round": "r", "match": "A–B", "result": "0-1", "side": "1"}] * 40
    v = tablero.explain(bad)["verdict"]
    assert any("Compra caro" in t for t in v)
    good = [{**b, "clv": 0.05, "p_close": 0.525} for b in bad]
    assert any("Le gana a la línea" in t for t in tablero.explain(good)["verdict"])
    assert tablero.explain([])["verdict"][0].startswith("No apostó")


def test_should_send():
    d = {"rounds": [{"id": "eu-1", "done": 5, "total": 5}, {"id": "mx-1", "done": 2, "total": 9}],
         "latest": "mx-1"}
    sat, mon = date(2026, 10, 10), date(2026, 10, 12)
    assert tablero.should_send(d, {}, sat) == (True, ["eu-1"])
    assert tablero.should_send(d, {"rounds": ["eu-1"]}, sat) == (False, [])
    assert tablero.should_send(d, {"rounds": ["eu-1"]}, mon) == (True, [])
    assert tablero.should_send(d, {"rounds": ["eu-1"], "last": mon.isoformat()}, mon) == (False, [])
