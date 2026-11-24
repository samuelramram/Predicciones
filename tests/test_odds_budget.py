"""The Odds API credits are shared with other projects (500/month). These pin the
rules that keep the ingests from eating the month: pay only for competitions with
matches coming up, keep a reserve, and price calls as markets × regions."""
from __future__ import annotations

from datetime import datetime, timezone

from wc_predictor.ingest import odds_budget
from wc_predictor.ingest.ligamx_odds import request_cost

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def test_request_cost_is_markets_times_regions():
    assert request_cost("eu", "h2h") == 1
    assert request_cost("eu", "h2h,totals") == 2
    assert request_cost("us,eu,uk", "h2h,totals") == 6     # the old default


def test_events_within_window_only():
    ev = [{"commence_time": "2026-11-24T20:00:00Z"},      # tonight
          {"commence_time": "2026-11-24T10:30:00Z"},      # in play
          {"commence_time": "2026-12-02T20:00:00Z"},      # next week
          {"commence_time": "garbage"}]
    got = odds_budget.events_within(ev, 72, now=NOW)
    assert [e["commence_time"] for e in got] == ["2026-11-24T20:00:00Z",
                                                  "2026-11-24T10:30:00Z"]


def test_reserve_blocks_spending(monkeypatch):
    monkeypatch.setattr(odds_budget, "credits_left", lambda key: 70)
    monkeypatch.delenv("ODDS_API_RESERVE", raising=False)
    assert not odds_budget.can_spend("k", 1)                       # 69 < 100
    assert odds_budget.can_spend("k", 1, reserve_floor=25)         # 69 ≥ 25
    assert odds_budget.can_spend("k", 1, force=True)
    monkeypatch.setenv("ODDS_API_RESERVE", "60")
    assert odds_budget.can_spend("k", 6)                           # 64 ≥ 60


def test_unknown_balance_does_not_spend(monkeypatch):
    monkeypatch.setattr(odds_budget, "credits_left", lambda key: None)
    assert not odds_budget.can_spend("k", 1)
    assert odds_budget.can_spend("k", 1, force=True)
