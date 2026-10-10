import random

import pytest

from wc_predictor.liga import aprendiz


def _sim(n, truth_w, seed=1):
    """Matches where the TRUE probability is pool(model, market, truth_w)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        a = [rng.random() + 0.2 for _ in range(3)]
        b = [rng.random() + 0.2 for _ in range(3)]
        m = tuple(x / sum(a) for x in a)
        q = tuple(x / sum(b) for x in b)
        p = aprendiz.pool(m, q, truth_w)
        r, acc, o = rng.random(), 0.0, 2
        for i, pi in enumerate(p):
            acc += pi
            if r < acc:
                o = i
                break
        out.append((m, q, o))
    return out


def test_pool_edges():
    m, q = (0.5, 0.3, 0.2), (0.2, 0.3, 0.5)
    assert aprendiz.pool(m, q, 0.0) == pytest.approx(m)
    assert aprendiz.pool(m, q, 1.0) == pytest.approx(q)


def test_no_data_stays_at_prior():
    info = aprendiz.fit_weight([], 0.9)
    assert info["w"] == 0.9 and info["n"] == 0
    assert "arranca igual que el calibrado" in aprendiz.explain({**info, "prior": 0.9})


def test_shrinks_with_little_evidence_and_learns_with_a_lot():
    few = aprendiz.fit_weight(_sim(20, 0.4), prior=0.9)
    assert few["w"] > 0.8                       # 20 partidos: casi no se mueve
    many = aprendiz.fit_weight(_sim(1500, 0.4, seed=3), prior=0.9)
    assert many["w_star"] == pytest.approx(0.4, abs=0.1)
    assert 0.4 < many["w"] < 0.6                 # la evidencia manda, aún encogido


def test_pairs_from_ledger_uses_settled_only():
    from wc_predictor.liga import arbitro
    pick = {"league": "E0", "home": "A", "away": "B", "date": "2026-10-10",
            "pick_1x2": "1", "pick_exact": "1-0"}
    recs = [{"round": "eu-2026-W41", "bot": "estadistico", "picks": [{**pick, "p1x2": [0.6, 0.2, 0.2]},
                                                                    {**pick, "home": "C", "p1x2": [0.5, 0.3, 0.2]}]},
            {"round": "eu-2026-W41", "bot": "borrego", "picks": [{**pick, "p1x2": [0.5, 0.25, 0.25]},
                                                                {**pick, "home": "C", "p1x2": [0.4, 0.3, 0.3]}]},
            {"round": "mx-2026-J11", "bot": "estadistico", "picks": [{**pick, "league": "MX", "p1x2": [1, 0, 0]}]}]
    idx = arbitro.results_index([{"league": "E0", "home": "A", "away": "B", "date": "2026-10-10",
                                  "home_score": 0, "away_score": 2}])
    pairs = aprendiz.pairs_from_ledger(recs, idx, "eu-")
    assert pairs == [((0.6, 0.2, 0.2), (0.5, 0.25, 0.25), 2)]
    assert aprendiz.pairs_from_ledger(recs, idx, "eu-", before="2026-10-10") == []


def test_seal_bots_skips_started_matches(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from wc_predictor.liga import seal
    from wc_predictor.pipeline import europa_live
    import functools
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(seal, "append", functools.partial(seal.append, path=led))
    read = seal.read_ledger
    monkeypatch.setattr(seal, "read_ledger", lambda *_a, **_k: read(led))
    entry = {"pick_1x2": "1", "pick_exact": "1-0", "p1x2": [0.5, 0.3, 0.2], "p_over25": 0.5,
             "p_btts": 0.5, "value_bets": []}
    rnd = {"bots": ["aprendiz"], "matches": [
        {"home": "A", "away": "B", "league": "E0", "date": "2026-10-10",
         "kickoff_utc": "2026-10-10T11:30+00:00", "bots": {"aprendiz": entry}},
        {"home": "C", "away": "D", "league": "E0", "date": "2026-10-11",
         "kickoff_utc": "2026-10-11T15:30+00:00", "bots": {"aprendiz": entry}}]}
    recs = europa_live.seal_bots(rnd, "eu-2026-W41", now=datetime(2026, 10, 10, 18, tzinfo=timezone.utc))
    assert [p["home"] for p in recs[0]["picks"]] == ["C"]
