import json

import pytest

from wc_predictor.ingest import liga_results as lr
from wc_predictor.liga import arbitro


@pytest.mark.parametrize("fd,tsdb", [
    ("Man City", "Manchester City"), ("Ath Madrid", "Atlético Madrid"),
    ("Paris SG", "Paris Saint-Germain"), ("Leverkusen", "Bayer Leverkusen"),
    ("Inter", "Inter Milan"), ("Espanol", "Espanyol"), ("Tigres", "Tigres UANL"),
    ("Querétaro", "Querétaro"), ("Nott'm Forest", "Nottingham Forest"),
    ("M'gladbach", "Borussia Mönchengladbach"),
])
def test_names_match(fd, tsdb):
    assert lr.similarity(fd, tsdb) >= 0.55


def _ev(h, a, hs, as_, status="FT"):
    return {"strHomeTeam": h, "strAwayTeam": a, "intHomeScore": hs, "intAwayScore": as_,
            "strStatus": status, "strPostponed": "no", "idEvent": "1"}


def test_match_picks_right_pairing():
    events = [_ev("Manchester United", "Tottenham Hotspur", "0", "0", "2H"),
              _ev("Manchester City", "Liverpool", "1", "0"),
              _ev("Arsenal", "Leeds United", "2", "1")]
    e = lr.match_event({"home": "Man City", "away": "Liverpool"}, events)
    assert e["strAwayTeam"] == "Liverpool"
    assert lr.match_event({"home": "Man City", "away": "Arsenal"}, events) is None
    assert lr.finished_score(events[0]) is None            # still playing
    assert lr.finished_score(events[2]) == (2, 1)
    assert lr.finished_score(_ev("A", "B", None, None, "NS")) is None


def test_collect_and_pending(tmp_path):
    led = tmp_path / "ledger.jsonl"
    picks = [{"league": "E0", "home": "Arsenal", "away": "Leeds", "date": "2026-10-10"},
             {"league": "MX", "home": "Querétaro", "away": "Atlante", "date": "2026-10-10"},
             {"league": "E0", "home": "Liverpool", "away": "Man City", "date": "2026-10-11"}]
    led.write_text(json.dumps({"picks": picks}) + "\n" + json.dumps({"picks": picks[:1]}) + "\n")
    from datetime import date
    todo = lr.pending(led, set(), date(2026, 10, 10))
    assert [m["home"] for m in todo] == ["Arsenal", "Querétaro"]        # dedup + not future
    assert lr.pending(led, {("E0", "Arsenal", "Leeds", "2026-10-09")}, date(2026, 10, 10))[0]["home"] \
        == "Querétaro"                                                     # FD has it (±1 day)

    calls = []

    def fake(lg, d):
        calls.append((lg, d))
        if (lg, d) == ("E0", "2026-10-10"):
            return [_ev("Arsenal", "Leeds United", "2", "1")]
        if (lg, d) == ("MX", "2026-10-11"):                              # night match, UTC next day
            return [_ev("Querétaro", "Atlante", "1", "1")]
        return []
    rows = lr.collect(todo, fake)
    assert {(r["home"], r["home_score"], r["away_score"]) for r in rows} == {("Arsenal", 2, 1),
                                                                           ("Querétaro", 1, 1)}
    assert len(calls) == len(set(calls))                                  # each day fetched once
    p = tmp_path / "live.csv"
    assert lr.merge_write(p, rows) == 2 and lr.merge_write(p, rows[:1]) == 2
    assert lr.load_live(p)[0]["home_score"] in (1, 2)


def test_football_data_wins_over_live():
    fd = [{"league": "E0", "home": "Arsenal", "away": "Leeds", "date": "2026-10-11"}]
    live = [{"league": "E0", "home": "Arsenal", "away": "Leeds", "date": "2026-10-10"},
            {"league": "E0", "home": "Chelsea", "away": "Bournemouth", "date": "2026-10-10"}]
    assert [r["home"] for r in arbitro.live_only(fd, live)] == ["Chelsea"]
