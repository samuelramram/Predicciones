"""Tests de la liga de bots: calificador, bankroll ficticio, sellado y bots."""
from __future__ import annotations

import pytest

from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.liga import seal
from wc_predictor.liga.bots import Ticket, borrego_ticket, ticket_from_prediction, typical_scores
from wc_predictor.liga.scoring import (UNIFORM_BRIER, Bankroll, BotRecord, brier, log_loss,
                                       outcome_of, paired_diff, table)

RULES = LIGAMX_APERTURA_PROFILE.rules


# ---------------------------------------------------------------- scoring

def test_outcome_of():
    assert outcome_of(2, 1) == "1" and outcome_of(1, 1) == "X" and outcome_of(0, 3) == "2"


def test_brier_scale_is_sum_over_classes():
    third = (1 / 3, 1 / 3, 1 / 3)
    assert brier(third, "1") == pytest.approx(UNIFORM_BRIER)   # 0.667, not 0.222
    assert brier((1.0, 0.0, 0.0), "1") == 0.0
    assert brier((0.0, 0.0, 1.0), "1") == pytest.approx(2.0)


def test_log_loss_clamps_zero_probability():
    assert log_loss((1.0, 0.0, 0.0), "1") == pytest.approx(0.0)
    assert log_loss((1.0, 0.0, 0.0), "X") > 20  # finite, huge — no math domain error


def test_bot_record_uses_pool_rules():
    r = BotRecord("x")
    assert r.add("1", "2-1", (0.5, 0.3, 0.2), 2, 1, RULES) == RULES.points_exact
    assert r.add("1", "1-0", (0.5, 0.3, 0.2), 3, 1, RULES) == RULES.points_1x2
    assert r.add("2", "0-1", (0.5, 0.3, 0.2), 1, 1, RULES) == 0
    s = r.summary()
    assert (s["n"], s["points"], s["exactos"]) == (3, RULES.points_exact + RULES.points_1x2, 1)


def test_table_breaks_ties_by_exactos():
    a, b = BotRecord("a"), BotRecord("b")
    a.add("1", "2-1", (1, 0, 0), 2, 1, RULES)   # exact: 2 pts, 1 exacto
    b.add("1", "1-0", (1, 0, 0), 2, 1, RULES)   # 1 pt
    b.add("1", "1-0", (1, 0, 0), 3, 1, RULES)   # 1 pt → 2 pts, 0 exactos
    assert [s["bot"] for s in table([b, a])] == ["a", "b"]


# ---------------------------------------------------------------- bankroll

def test_bankroll_only_bets_with_value():
    br = Bankroll(start=100, stake=10)
    assert br.choose((0.5, 0.3, 0.2), (1.8, 3.0, 4.0)) is None  # every p·q ≤ 1
    pick = br.choose((0.6, 0.25, 0.15), (2.0, 3.5, 6.0))         # 1.2 / 0.875 / 0.9
    assert pick[0] == "1" and pick[1] == pytest.approx(0.2)


def test_bankroll_settles_win_and_loss():
    br = Bankroll(start=100, stake=10)
    assert br.settle((0.6, 0.25, 0.15), (2.0, 3.5, 6.0), "1") == pytest.approx(10.0)
    assert br.settle((0.6, 0.25, 0.15), (2.0, 3.5, 6.0), "X") == pytest.approx(-10.0)
    assert br.balance == pytest.approx(100.0)
    assert (br.n_bets, br.wins, br.staked) == (2, 1, 20.0)
    assert br.roi == pytest.approx(0.0)


def test_bankroll_stops_when_broke():
    br = Bankroll(start=5, stake=10)
    assert br.settle((0.9, 0.05, 0.05), (2.0, 10.0, 10.0), "1") == 0.0
    assert br.n_bets == 0


def test_paired_diff():
    d = paired_diff([2, 1, 0, 1], [1, 1, 0, 0])
    assert d["n"] == 4 and d["total_diff"] == 2 and d["mean_diff"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        paired_diff([1, 2], [1])


# ---------------------------------------------------------------- bots

def test_typical_scores_per_outcome():
    rows = [{"home_score": h, "away_score": a} for h, a in
            [(1, 0), (1, 0), (2, 1), (1, 1), (0, 0), (0, 0), (0, 1)]]
    assert typical_scores(rows) == {"1": "1-0", "X": "0-0", "2": "0-1"}
    assert typical_scores([]) == {"1": "1-0", "X": "1-1", "2": "0-1"}  # fallback


def test_borrego_follows_market_favorite():
    t = borrego_ticket((0.2, 0.3, 0.5), {"1": "1-0", "X": "1-1", "2": "0-1"})
    assert (t.pick_1x2, t.pick_exact) == ("2", "0-1")
    assert sum(t.probs) == pytest.approx(1.0)


def test_ticket_from_prediction_renormalizes():
    t = ticket_from_prediction({"pick_1x2": "1", "pick_exact": "2-1",
                                "p_home_win": 0.501, "p_draw": 0.3, "p_away_win": 0.2})
    assert isinstance(t, Ticket) and sum(t.probs) == pytest.approx(1.0)


# ---------------------------------------------------------------- seal

PICKS = [{"home": "América", "away": "Chivas", "pick_1x2": "1", "pick_exact": "2-1"},
         {"home": "Pumas", "away": "Cruz Azul", "pick_1x2": "2", "pick_exact": "0-1"}]


def test_seal_is_deterministic_and_order_independent():
    a = seal.seal("j10", "samuel", PICKS, sealed_at="2026-10-10T00:00:00+00:00")
    b = seal.seal("j10", "samuel", list(reversed(PICKS)), sealed_at="2026-10-10T00:00:00+00:00")
    assert a["hash"] == b["hash"] and seal.verify(a)


def test_editing_a_pick_breaks_the_hash():
    rec = seal.seal("j10", "samuel", PICKS, sealed_at="2026-10-10T00:00:00+00:00")
    rec["picks"][0]["pick_exact"] = "3-0"
    assert not seal.verify(rec)


def test_ledger_chain(tmp_path):
    led = tmp_path / "ledger.jsonl"
    seal.append("j10", "samuel", PICKS, path=led, sealed_at="2026-10-10T00:00:00+00:00")
    seal.append("j10", "estadistico", PICKS, path=led, sealed_at="2026-10-10T00:01:00+00:00")
    recs = seal.read_ledger(led)
    assert seal.verify_chain(recs)[0]
    with pytest.raises(ValueError, match="ya selló"):
        seal.append("j10", "samuel", PICKS, path=led)
    # dropping a record breaks the chain
    assert not seal.verify_chain(recs[1:])[0]
    # tampering a stored record is caught and blocks new appends
    lines = led.read_text(encoding="utf-8").splitlines()
    led.write_text(lines[0].replace('"2-1"', '"3-0"') + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupto"):
        seal.append("j11", "samuel", PICKS, path=led)


def test_sealed_before_kickoff():
    rec = seal.seal("j10", "samuel", PICKS, sealed_at="2026-10-10T17:00:00+00:00")
    assert seal.sealed_before(rec, "2026-10-10T19:00:00Z")
    assert not seal.sealed_before(rec, "2026-10-10T16:59:00+00:00")
