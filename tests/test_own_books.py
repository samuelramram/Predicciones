"""Tests for betting only at books I can actually use, and the CLV gate.

The module used to line-shop across ~45 books (Pinnacle, lowvig, matchbook…) and
report an edge at prices the user has no account for. Worse, the only gate was
`model − fair ≥ 3%` — a model-vs-market disagreement, which the plan itself says
is NOT evidence (the model is not sharper than the market). These pin the fix:
price from my books, and judge it by CLV against the sharp fair line.
"""
from __future__ import annotations

import json

from wc_predictor.betting.value import find_value_bets
from wc_predictor.ingest.ligamx_odds import load_books_config, manual_prices_for, parse_markets

# One match, 3-cell toy matrix; the model likes the home side far more than the
# market does — exactly the "big edge" shape that should NOT survive on its own.
CELLS = [{"h": 1, "a": 0, "prob": 0.55, "outcome": "1"},
         {"h": 1, "a": 1, "prob": 0.25, "outcome": "X"},
         {"h": 0, "a": 1, "prob": 0.20, "outcome": "2"}]
MODEL_1X2 = (0.55, 0.25, 0.20)

MARKET = {
    "h2h": {
        # The model beats fair on "1" (+10pp) and "2" (+5pp); "X" it likes LESS
        # than the market, so "X" never qualifies under any setting.
        "fair": {"1": 0.45, "X": 0.40, "2": 0.15},
        # Sharp book pays 2.30 — better than the fair price of 1/0.45 = 2.22.
        "best": {"1": {"price": 2.30, "book": "pinnacle"},
                 "X": {"price": 2.40, "book": "pinnacle"},
                 "2": {"price": 7.00, "book": "pinnacle"}},
        # My book pays only 2.10 on the home side — worse than fair, so betting it
        # starts behind — and doesn't quote the away side at all.
        "best_available": {"1": {"price": 2.10, "book": "caliente"},
                           "X": {"price": 0.0, "book": None},
                           "2": {"price": 0.0, "book": None}},
    },
    "totals": {},
}


def _bets(**kw):
    return find_value_bets("A vs B", MODEL_1X2, CELLS, MARKET, edge_min=0.03, **kw)


def test_default_line_shops_every_book():
    bets = {b.selection: b for b in _bets()}
    assert bets["1"].price == 2.30
    assert bets["1"].book == "pinnacle"


def test_own_books_only_uses_my_price():
    bets = {b.selection: b for b in _bets(own_books_only=True)}
    assert bets["1"].price == 2.10
    assert bets["1"].book == "caliente"
    assert bets["1"].is_available


def test_own_books_only_drops_bets_my_books_dont_quote():
    """No price at my books must DROP the bet, not silently fall back to a
    sharp book's price I cannot take."""
    assert {b.selection for b in _bets(own_books_only=True)} == {"1"}
    # The away side IS a candidate when line-shopping — it only disappears
    # because no book I can use quotes it.
    assert "2" in {b.selection for b in _bets()}


def test_clv_sign_separates_the_two_prices():
    """Same bet, same model edge — only the price differs. CLV is what tells them
    apart: the sharp price beats the fair line, mine doesn't."""
    sharp = {b.selection: b for b in _bets()}["1"]
    mine = {b.selection: b for b in _bets(own_books_only=True)}["1"]
    assert sharp.clv_entry > 0 and sharp.beats_fair
    assert mine.clv_entry < 0 and not mine.beats_fair
    # Both still look +EV to the model — which is exactly the trap.
    assert sharp.ev > 0 and mine.ev > 0


def test_require_clv_drops_the_bet_that_starts_behind():
    assert _bets(own_books_only=True, require_clv=True) == []
    assert len(_bets(require_clv=True)) >= 1


def test_clv_matches_price_over_fair_price():
    b = {x.selection: x for x in _bets()}["1"]
    assert abs(b.clv_entry - (2.30 * 0.45 - 1.0)) < 1e-9


# ------------------------------------------------------------- books config ---

def test_books_config_absent_is_inert(tmp_path):
    cfg = load_books_config(tmp_path / "nope.json")
    assert cfg == {"available": [], "manual": {}}


def test_manual_prices_are_read_per_match(tmp_path):
    p = tmp_path / "books.json"
    p.write_text(json.dumps({
        "available": ["Caliente"],
        "manual": {"caliente": {"matches": {"León|Pachuca": {"h2h": {"1": 2.95, "X": 3.45, "2": 2.34}}}}},
    }), encoding="utf-8")
    cfg = load_books_config(p)
    assert cfg["available"] == ["caliente"]           # normalised to lowercase
    assert manual_prices_for(cfg, "León|Pachuca")["caliente"]["2"] == 2.34
    assert manual_prices_for(cfg, "Otro|Partido") == {}


def test_manual_book_competes_for_available_but_not_for_fair():
    """A hand-captured book must reach best_available without touching the fair
    line — the sharp consensus is the yardstick and must stay independent."""
    payload = [{
        "home_team": "León", "away_team": "Pachuca", "commence_time": "2026-08-01T01:00:00Z",
        "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
            {"name": "León", "price": 2.80}, {"name": "Pachuca", "price": 2.50},
            {"name": "Draw", "price": 3.40}]}]}],
    }]
    cfg = {"available": ["caliente"],
           "manual": {"caliente": {"matches": {"León|Pachuca": {"h2h": {"1": 9.99}}}}}}
    plain = parse_markets(payload)["León|Pachuca"]
    with_cal = parse_markets(payload, cfg)["León|Pachuca"]

    assert with_cal["h2h"]["best_available"]["1"] == {"price": 9.99, "book": "caliente"}
    assert with_cal["h2h"]["best"]["1"]["book"] == "pinnacle"     # feed best untouched
    assert with_cal["h2h"]["fair"] == plain["h2h"]["fair"]        # fair line untouched


def test_played_stake_rounds_to_house_minimum():
    """El stake que se apuesta se redondea a múltiplos del mínimo de la casa, con
    un piso de 1 unidad — los stakes de ¼-Kelly ($3–$10) caen bajo el mínimo de
    $20 y hay que subirlos para que el boleto sea jugable."""
    from wc_predictor.pipeline.ligamx_bets import played_stake_mxn

    # ¼-Kelly de ~1.6% sobre $500 = ~$8 → piso al mínimo de $20.
    assert played_stake_mxn(0.0156, 500, 20) == 20.0
    # Un stake ínfimo también sube al mínimo, nunca a $0.
    assert played_stake_mxn(0.0008, 500, 20) == 20.0
    # ~$31 redondea al múltiplo más cercano de $20 = $40.
    assert played_stake_mxn(0.0625, 500, 20) == 40.0
    # min_stake=0 devuelve el Kelly crudo (comportamiento anterior).
    assert played_stake_mxn(0.0156, 500, 0) == round(0.0156 * 500, 2)
