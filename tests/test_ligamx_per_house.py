"""Tests for the per-house boleto: per-book price retention, budget allocation,
and honest ledger logging. Pure functions + a temp odds/ledger file, no network."""
from __future__ import annotations

import json

from wc_predictor.ingest.ligamx_odds import parse_markets
from wc_predictor.pipeline import ligamx_bets as B
from wc_predictor.pipeline import ligamx_clv as C


def test_parse_markets_keeps_only_my_books_in_by_book():
    """`by_book` must carry my houses (feed + manual) and NEVER a sharp book —
    the price you can actually get, not the line-shopped reference."""
    payload = [{
        "home_team": "America", "away_team": "Santos",
        "commence_time": "2026-07-27T00:00:00Z",
        "bookmakers": [
            {"key": "betway", "markets": [{"key": "h2h", "outcomes": [
                {"name": "America", "price": 1.50},
                {"name": "Draw", "price": 4.0},
                {"name": "Santos", "price": 6.0}]}]},
            {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "America", "price": 1.55},
                {"name": "Draw", "price": 4.2},
                {"name": "Santos", "price": 5.5}]}]},
        ]}]
    cfg = {"available": ["betway", "caliente"],
           "manual": {"caliente": {"as_of": "x", "matches": {
               "América|Santos": {"h2h": {"1": 1.48, "X": 4.1, "2": 6.5}}}}}}
    mk = parse_markets(payload, cfg)
    by_book = mk["América|Santos"]["h2h"]["by_book"]
    assert set(by_book) == {"betway", "caliente"}          # my houses only
    assert "pinnacle" not in by_book                        # sharp book excluded
    assert by_book["betway"]["1"] == 1.50
    assert by_book["caliente"]["2"] == 6.5                  # manual folded in


def _synthetic_market_for_round(round_spec="j3"):
    fx = json.loads(B.FIXTURES_JSON.read_text(encoding="utf-8"))
    n = int(round_spec[1:])
    matches = {}
    for m in fx["matches"]:
        if m.get("jornada") != n:
            continue
        matches[f"{m['home']}|{m['away']}"] = {
            "h2h": {"fair": {"1": 0.45, "X": 0.27, "2": 0.28},
                    "by_book": {"betway": {"1": 2.1, "X": 3.4, "2": 3.2},
                                "caliente": {"1": 2.05, "X": 3.5, "2": 3.3}}},
            "totals": {}}
    return matches, sum(1 for m in fx["matches"] if m.get("jornada") == n)


def test_per_house_deploys_full_budget_at_min_stake(tmp_path, monkeypatch):
    matches, n_matches = _synthetic_market_for_round("j3")
    odds = tmp_path / "odds_markets.json"
    odds.write_text(json.dumps({"matches": matches}), encoding="utf-8")
    monkeypatch.setattr(B, "ODDS_MARKETS_JSON", odds)

    pay = B.per_house_ticket("j3", {"betway": 200.0, "caliente": 100.0}, min_stake=20.0)

    bw = pay["houses"]["betway"]
    # 200/20 = 10 units across 9 matches -> every match covered, one gets 2 units.
    assert len(bw["bets"]) == n_matches
    assert bw["total_stake_mxn"] == 200.0
    assert all(b["stake_mxn"] >= 20.0 for b in bw["bets"])
    assert all(b["house"] == "betway" for b in bw["bets"])
    assert all(b["price"] in (2.1, 3.4, 3.2) for b in bw["bets"])  # betway prices only

    cl = pay["houses"]["caliente"]
    # 100/20 = 5 units < 9 matches -> only the 5 strongest picks, one unit each.
    assert len(cl["bets"]) == 5
    assert cl["total_stake_mxn"] == 100.0
    assert all(b["stake_mxn"] == 20.0 for b in cl["bets"])


def test_log_boleto_records_real_house_and_is_book_aware(tmp_path, monkeypatch):
    matches, _ = _synthetic_market_for_round("j3")
    odds = tmp_path / "odds_markets.json"
    odds.write_text(json.dumps({"matches": matches}), encoding="utf-8")
    monkeypatch.setattr(B, "ODDS_MARKETS_JSON", odds)
    ledger = tmp_path / "clv_ledger.json"
    ledger.write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(C, "LEDGER_JSON", ledger)

    pay = B.per_house_ticket("j3", {"betway": 60.0, "caliente": 60.0}, min_stake=20.0)
    added = C.log_boleto(pay)
    entries = json.loads(ledger.read_text(encoding="utf-8"))["entries"]

    assert added == len(entries)
    assert {e["entry_book"] for e in entries} <= {"betway", "caliente"}
    # the same selection at both houses is TWO real bets (book-aware dedup)
    both = [e for e in entries if e["match"] == entries[0]["match"]
            and e["selection"] == entries[0]["selection"]]
    assert len({e["entry_book"] for e in both}) == len(both)
    # re-logging the identical boleto adds nothing (idempotent)
    assert C.log_boleto(pay) == 0
