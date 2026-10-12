"""Pure helpers of the pool audit (expected vs realized points)."""
from __future__ import annotations

import pytest

from wc_predictor.pipeline.ligamx_pool_audit import (expected_points, market_reweight,
                                                      outcome, realized_points)


def test_outcome_and_realized_points():
    assert outcome("2-1") == 1 and outcome("1-1") == 0 and outcome("0-3") == -1
    assert realized_points("2-1", "2-1") == 2
    assert realized_points("1-0", "3-1") == 1
    assert realized_points("1-1", "2-1") == 0


def test_market_reweight_matches_market_1x2_and_keeps_shape():
    cells = [("1-0", 0.30), ("2-0", 0.10), ("1-1", 0.30), ("0-1", 0.30)]
    d = market_reweight(cells, (0.5, 0.2, 0.3))
    assert sum(d.values()) == pytest.approx(1.0)
    assert d["1-0"] + d["2-0"] == pytest.approx(0.5)
    assert d["1-1"] == pytest.approx(0.2) and d["0-1"] == pytest.approx(0.3)
    assert d["1-0"] / d["2-0"] == pytest.approx(3.0)  # model shape within the outcome


def test_expected_points_is_p_result_plus_p_exact():
    d = {"1-0": 0.4, "2-0": 0.1, "1-1": 0.2, "0-1": 0.3}
    assert expected_points("1-0", d) == pytest.approx(0.5 + 0.4)
    assert expected_points("1-1", d) == pytest.approx(0.2 + 0.2)
    assert expected_points("3-0", d) == pytest.approx(0.5)
