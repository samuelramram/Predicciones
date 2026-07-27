"""Tests for the CLV (closing-line-value) core."""
from __future__ import annotations

from wc_predictor.betting.clv import (LedgerEntry, beat_close, clv_odds, ev_vs_fair,
                                      settle_profit, summarize)


def _entry(**kw):
    base = dict(round="j3", match="A vs B", market="1X2", selection="1",
                model_prob=0.7, entry_fair_prob=0.6, entry_price=1.8, entry_book="x",
                stake_mxn=10.0, logged_at="2026-07-27T00:00:00Z")
    base.update(kw)
    return LedgerEntry(**base)


def test_clv_odds_positive_when_entry_longer_than_close():
    # Bet at 2.10, closed at 2.00 → you beat the close.
    assert clv_odds(2.10, 2.00) > 0
    assert clv_odds(1.90, 2.00) < 0
    assert clv_odds(2.00, 2.00) == 0.0
    assert clv_odds(2.0, None) is None


def test_beat_close():
    assert beat_close(2.1, 2.0) is True
    assert beat_close(1.9, 2.0) is False
    assert beat_close(2.0, None) is None


def test_ev_vs_fair():
    # Price 2.0 at a 55% sharp fair → +10% EV per unit.
    assert abs(ev_vs_fair(2.0, 0.55) - 0.10) < 1e-9
    assert ev_vs_fair(2.0, None) is None


def test_settle_profit():
    assert settle_profit(1.8, 10.0, "win") == 8.0
    assert settle_profit(1.8, 10.0, "loss") == -10.0
    assert settle_profit(1.8, 10.0, "void") == 0.0
    assert settle_profit(1.8, 10.0, None) is None


def test_summary_same_snapshot_is_zero_clv():
    # Entry price == close price → CLV exactly 0 (no line movement captured).
    e = _entry(close_price=1.8, close_fair_prob=0.56, closed_at="2026-07-27T00:00:00Z")
    s = summarize([e])
    assert s["n"] == 1 and s["n_closed"] == 1
    assert s["avg_clv_pct"] == 0.0
    assert s["pct_beat_close"] == 0.0  # strict >, equal is not "beat"


def test_summary_clv_and_pnl():
    a = _entry(entry_price=2.1, close_price=2.0, close_fair_prob=0.49,
               closed_at="z", result="win", profit_mxn=11.0)
    b = _entry(match="C vs D", entry_price=1.8, close_price=2.0, close_fair_prob=0.55,
               closed_at="z", result="loss", profit_mxn=-10.0)
    s = summarize([a, b])
    assert s["n_closed"] == 2
    # a beat the close (2.1>2.0), b did not → 50%.
    assert s["pct_beat_close"] == 50.0
    assert s["n_settled"] == 2 and s["wins"] == 1 and s["losses"] == 1
    assert s["profit_mxn"] == 1.0 and s["staked_mxn"] == 20.0
    assert s["roi_pct"] == 5.0


def test_summary_by_market():
    a = _entry(market="1X2", close_price=2.0, close_fair_prob=0.5, closed_at="z")
    b = _entry(market="O/U 2.5", selection="Under", close_price=2.0,
               close_fair_prob=0.5, closed_at="z")
    s = summarize([a, b])
    assert set(s["by_market"]) == {"1X2", "O/U 2.5"}
    assert s["by_market"]["1X2"]["n"] == 1
