"""Tests de mercados (O/U, BTTS, hándicap asiático), ingest de Europa y top-3."""
from __future__ import annotations

import csv
import io

import pytest

from wc_predictor.ingest import europa_fd as fd
from wc_predictor.liga import markets as mk
from wc_predictor.liga.europa import top_teams


def _cells(table: dict[tuple[int, int], float]) -> list[dict]:
    return [{"h": h, "a": a, "prob": p} for (h, a), p in table.items()]


# Toy distribution: 1-0 40%, 1-1 30%, 0-2 20%, 3-1 10%
CELLS = _cells({(1, 0): 0.4, (1, 1): 0.3, (0, 2): 0.2, (3, 1): 0.1})


def test_simple_markets_from_cells():
    assert mk.p_1x2(CELLS) == pytest.approx((0.5, 0.3, 0.2))
    assert mk.p_over(CELLS, 2.5) == pytest.approx(0.1)
    assert mk.p_over(CELLS, 1.5) == pytest.approx(0.6)
    assert mk.p_btts(CELLS) == pytest.approx(0.4)


@pytest.mark.parametrize("gd,line,expected", [
    (1, -0.5, 2.0),    # win
    (0, -0.5, 0.0),    # loss
    (1, -1.0, 1.0),    # push on the whole line
    (1, -0.75, 1.5),   # half win (−0.5) + half push (−1.0)
    (0, -0.25, 0.5),   # half loss (−0.5) + half push (0)
    (0, 0.25, 1.5),    # half push (0) + half win (+0.5)
    (-1, 1.5, 2.0),
])
def test_ah_return(gd, line, expected):
    assert mk.ah_return(gd, line, 2.0) == pytest.approx(expected)


def test_ah_expected_returns_sides_are_mirrors():
    # Level line: home wins 50%, draw push 30%, away wins 20%, both priced 2.0
    e = mk.ah_expected_returns(CELLS, 0.0, 2.0, 2.0)
    assert e["home"] == pytest.approx(0.5 * 2 + 0.3 * 1)
    assert e["away"] == pytest.approx(0.2 * 2 + 0.3 * 1)


def test_market_bankroll_bets_only_with_value_and_counts_push():
    bk = mk.MarketBankroll("ah", stake=10)
    assert bk.settle({"home": 0.98, "away": 0.97}, {"home": 2.0, "away": 0.0}) is None
    assert bk.settle({"home": 1.10, "away": 0.90}, {"home": 1.0, "away": 1.0}) == 0.0  # push
    assert bk.settle({"home": 1.10, "away": 0.90}, {"home": 1.9, "away": 0.0}) == pytest.approx(9.0)
    assert (bk.n_bets, bk.wins, bk.staked) == (2, 1, 20.0)
    assert bk.roi == pytest.approx(0.45)


def test_logpool_binary_bounds():
    assert mk.logpool_binary([0.6, 0.6], [1, 1]) == pytest.approx(0.6)
    p = mk.logpool_binary([0.4, 0.8], [0.5, 0.5])
    assert 0.4 < p < 0.8


HEADER = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,PSCH,PSCD,PSCA,AvgCH,AvgCD,AvgCA,"
          "PC>2.5,PC<2.5,AvgC>2.5,AvgC<2.5,AHCh,AvgCAHH,AvgCAHA")


def test_normalize_rows_closing_and_fallbacks():
    text = HEADER + "\n" + "\n".join([
        "E0,16/08/2025,20:00,Liverpool,Bournemouth,4,2,H,1.30,6.0,9.5,1.28,5.8,9.0,"
        "1.45,2.9,1.42,2.8,-1.75,1.95,1.95",
        # no Pinnacle → avg fallback; 2-digit year
        "E0,17/08/25,14:00,Arsenal,Man United,1,0,H,,,,2.0,3.5,3.8,,,1.9,1.9,-0.5,1.9,2.0",
        # not played yet → skipped in closing mode
        "E0,30/08/2025,14:00,Chelsea,Fulham,,,,,,,2.0,3.5,3.8,,,1.9,1.9,-0.5,1.9,2.0",
    ]) + "\n"
    rows = fd.normalize_rows(list(csv.DictReader(io.StringIO(text))), "E0", "2526")
    assert len(rows) == 2
    a, b = rows
    assert a["date"] == "2025-08-16" and a["fair_source"] == "pinnacle"
    assert a["fair_p1"] + a["fair_px"] + a["fair_p2"] == pytest.approx(1.0, abs=1e-3)
    assert a["ah_line"] == -1.75 and a["avg_over25"] == 1.42
    assert b["date"] == "2025-08-17" and b["fair_source"] == "avg"
    assert b["fair_over25"] == pytest.approx(0.5)


def test_committed_europa_file():
    rows = fd.load()
    assert len(rows) > 10_000
    assert {r["league"] for r in rows} == set(fd.LEAGUES)
    missing = sum(1 for r in rows if r["fair_p1"] is None or r["avg_over25"] is None)
    assert missing <= 0.01 * len(rows)


def test_top_teams_by_elo_and_override():
    elos = {"A": 1700, "B": 1650, "C": 1600, "D": 1550, "Z": 1900}
    season = {"A", "B", "C", "D"}           # Z isn't in the league this season
    assert top_teams(elos, season, 3) == ["A", "B", "C"]
    assert top_teams(elos, season, 3, "E0", {"E0": ["D", "C", "B"]}) == ["D", "C", "B"]


def test_implied_lambdas_reproduce_market():
    from wc_predictor.liga.europa import _probs_np, implied_lambdas
    lh, la = implied_lambdas(0.60, 0.17, 0.62, -0.10)
    p1, _, p2, po = _probs_np(lh, la, -0.10)
    assert (p1, p2, po) == pytest.approx((0.60, 0.17, 0.62), abs=0.01)
    assert lh > la
