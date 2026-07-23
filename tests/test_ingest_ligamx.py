"""Tests for the Liga MX ingest — pure logic only (no network)."""
from __future__ import annotations

from wc_predictor.ingest.ligamx import (
    HISTORY_COLUMNS,
    event_to_fixture,
    event_to_history_row,
    normalize_name,
    _match_id,
    _tournament_label,
)


def test_normalize_name_maps_thesportsdb_spellings():
    assert normalize_name("CF America") == "América"
    assert normalize_name("CD Guadalajara") == "Guadalajara"
    assert normalize_name("Atletico de San Luis") == "San Luis"
    assert normalize_name("Queretaro FC") == "Querétaro"
    assert normalize_name("FC Juarez") == "Juárez"
    assert normalize_name("Santos Laguna") == "Santos"
    assert normalize_name("Mazatlán") == "Mazatlán"
    assert normalize_name("Atlante") == "Atlante"


def test_normalize_name_prefix_fallback_and_passthrough():
    # Unknown side with a known prefix is stripped, not dropped.
    assert normalize_name("FC Some New Team") == "Some New Team"
    # Fully unknown passes through unchanged (still a valid opponent key).
    assert normalize_name("Veracruz") == "Veracruz"
    assert normalize_name("") == ""


def test_normalize_name_accent_insensitive_variants():
    """Regression: the odds feed spells 'Atlético San Luis' (accent, no 'de')
    where fixtures use 'San Luis'. Before the accent-folding fallback this exact
    variant fell through and the match silently lost its market odds in the blend."""
    assert normalize_name("Atlético San Luis") == "San Luis"      # feed spelling
    assert normalize_name("Atletico San Luis") == "San Luis"      # no accent
    assert normalize_name("Atlético de San Luis") == "San Luis"   # with 'de'
    # Accent-folding also covers other accented feed variants.
    assert normalize_name("Club León") == "León"
    assert normalize_name("Queretaro") == "Querétaro"


def test_tournament_label_splits_apertura_clausura():
    assert _tournament_label("2025-08-10") == "Liga MX Apertura 2025"
    assert _tournament_label("2025-12-01") == "Liga MX Apertura 2025"
    assert _tournament_label("2026-02-15") == "Liga MX Clausura 2026"
    assert _tournament_label("2026-06-30") == "Liga MX Clausura 2026"
    assert _tournament_label("bad-date") == "Liga MX"


def test_match_id_is_deterministic():
    a = _match_id("2026-07-16", "Necaxa", "Atlante")
    b = _match_id("2026-07-16", "Necaxa", "Atlante")
    c = _match_id("2026-07-16", "Atlante", "Necaxa")
    assert a == b and a != c and a.startswith("m_")


def _ev(**kw):
    base = {
        "dateEvent": "2026-07-16", "strHomeTeam": "Necaxa", "strAwayTeam": "Atlante",
        "intHomeScore": "2", "intAwayScore": "1", "intRound": "1",
        "strVenue": "Estadio Victoria", "idEvent": "999", "strTimestamp": "2026-07-17T01:00:00",
    }
    base.update(kw)
    return base


def test_event_to_history_row_completed():
    row = event_to_history_row(_ev())
    assert set(row) == set(HISTORY_COLUMNS)
    assert row["home"] == "Necaxa" and row["away"] == "Atlante"
    assert row["home_score"] == 2 and row["away_score"] == 1
    assert row["neutral"] is False
    assert row["country"] == "Mexico"
    assert row["tournament"] == "Liga MX Apertura 2026"


def test_event_to_history_row_skips_unplayed():
    assert event_to_history_row(_ev(intHomeScore="", intAwayScore="")) is None


def test_event_to_fixture_played_and_upcoming():
    played = event_to_fixture(_ev())
    assert played["jornada"] == 1
    assert played["round_label"] == "Jornada 1"
    assert played["home_score"] == 2 and played["away_score"] == 1
    assert played["home"] == "Necaxa" and played["away"] == "Atlante"
    assert played["tsdb_event_id"] == "999"

    upcoming = event_to_fixture(_ev(intHomeScore="", intAwayScore="", intRound="5"))
    assert upcoming["jornada"] == 5
    assert upcoming["home_score"] is None and upcoming["away_score"] is None
