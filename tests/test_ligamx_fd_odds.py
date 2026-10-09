"""Tests del ingest de momios históricos (Football-Data MEX.csv)."""
from __future__ import annotations

import pytest

from wc_predictor.ingest import ligamx_fd_odds as fd

HEADER = ("Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,"
          "MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA,BFECH,BFECD,BFECA,B365CH,B365CD,B365CA")


def _csv(*rows: str) -> str:
    return "﻿" + HEADER + "\n" + "\n".join(rows) + "\n"


def test_devig_sums_to_one_and_keeps_order():
    p = fd.devig(2.0, 3.5, 4.0)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[2]


def test_normalize_maps_names_and_prefers_pinnacle():
    text = _csv(
        "Mexico,Liga MX,2025/2026,26/07/2025,02:00,Club America,Guadalajara Chivas,2,1,H,"
        "1.80,3.60,4.80,1.90,3.80,5.00,1.75,3.50,4.50,,,,,,",
        # Pinnacle blank → falls back to the market average
        "Mexico,Liga MX,2026/2027,27/09/2026,19:00,UNAM Pumas,Atl. San Luis,2,3,A,"
        ",,,2.05,3.4,3.5,2.1,3.6,3.5,,,,,,",
    )
    rows, unmapped = fd.normalize(text)
    assert not unmapped and len(rows) == 2
    a, b = rows
    assert (a["home"], a["away"], a["date"]) == ("América", "Guadalajara", "2025-07-26")
    assert a["fair_source"] == "pinnacle" and a["avg_o1"] == 1.75 and a["max_o1"] == 1.90
    assert b["fair_source"] == "avg" and (b["home"], b["away"]) == ("Pumas", "San Luis")
    assert a["fair_p1"] + a["fair_px"] + a["fair_p2"] == pytest.approx(1.0, abs=1e-3)


def test_normalize_skips_old_seasons_and_reports_unmapped():
    text = _csv(
        "Mexico,Liga MX,2018/2019,21/07/2018,01:30,Veracruz,Tigres UANL,0,4,A,"
        "2.93,3.34,2.6,2.95,3.5,2.64,2.74,3.1,2.51,,,,,,",
        "Mexico,Liga MX,2025/2026,21/07/2025,01:30,Equipo Nuevo,Tigres UANL,0,4,A,"
        "2.93,3.34,2.6,2.95,3.5,2.64,2.74,3.1,2.51,,,,,,",
    )
    rows, unmapped = fd.normalize(text)
    assert rows == [] and unmapped == {"Equipo Nuevo"}


def test_lookup_tolerates_uk_time_date_shift():
    idx = fd.index([{"date": "2026-09-28", "home": "León", "away": "Juárez"},
                    {"date": "2026-03-01", "home": "León", "away": "Juárez"}])
    assert fd.lookup(idx, "León", "Juárez", "2026-09-27")["date"] == "2026-09-28"
    assert fd.lookup(idx, "León", "Juárez", "2026-03-01")["date"] == "2026-03-01"
    assert fd.lookup(idx, "León", "Juárez", "2026-09-20") is None
    assert fd.lookup(idx, "Juárez", "León", "2026-09-28") is None  # home/away matter


def test_committed_file_covers_history():
    """The versioned historical_odds.csv must join (almost) every history match."""
    from wc_predictor.pipeline.ligamx import load_history_rows
    idx = fd.index(fd.load())
    hist = load_history_rows()
    missing = [r for r in hist if fd.lookup(idx, r["home"], r["away"], r["date"]) is None]
    assert len(missing) <= 0.01 * len(hist)
