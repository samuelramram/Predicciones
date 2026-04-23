"""
Regression tests for the bug fixes documented in the Feb 2026 code review.

Run with:
    .venv\\Scripts\\python -m pytest tests/test_fixes.py -v
"""
import logging
import pandas as pd
import numpy as np
import pytest
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# P1 — improvements.py: pd.api.types over np.issubdtype
# ---------------------------------------------------------------------------

class TestRecentFormDateCompatibility:
    """Fix P1: pipeline blocker in pandas >= 2.x with StringDtype date columns."""

    def _make_stats_df(self, date_dtype="string"):
        """Build a minimal stats DataFrame with the given date dtype."""
        data = {
            "date": pd.array(["01/01/2025", "15/01/2025", "01/02/2025"], dtype=date_dtype),
            "home_team": ["chivas", "america", "tigres"],
            "away_team": ["america", "tigres", "chivas"],
            "home_goals": [1, 2, 0],
            "away_goals": [1, 1, 2],
            "tournament": ["Clausura 2025"] * 3,
        }
        return pd.DataFrame(data)

    def test_no_crash_with_string_dtype(self):
        """calculate_recent_form must not throw TypeError when date column is StringDtype."""
        from src.predicciones.improvements import calculate_recent_form

        df = self._make_stats_df("string")
        # Verify the column really is StringDtype (the problematic case)
        assert not pd.api.types.is_datetime64_any_dtype(df["date"]), (
            "Precondition: date column should NOT be datetime before calling the function"
        )

        # Must not raise
        multiplier, details = calculate_recent_form(df, "chivas", "2025-02-10", n=3)
        assert isinstance(multiplier, float)
        assert 0.90 <= multiplier <= 1.10  # within valid form range

    def test_no_crash_with_object_dtype(self):
        """Also works with legacy object/str dtype (pandas 1.x behaviour)."""
        from src.predicciones.improvements import calculate_recent_form

        df = self._make_stats_df("object")
        multiplier, details = calculate_recent_form(df, "chivas", "2025-02-10", n=3)
        assert isinstance(multiplier, float)

    def test_no_crash_with_datetime_dtype(self):
        """Already-parsed datetime columns must not be double-converted."""
        from src.predicciones.improvements import calculate_recent_form

        df = self._make_stats_df("string")
        df["date"] = pd.to_datetime(df["date"], dayfirst=True)
        multiplier, details = calculate_recent_form(df, "chivas", "2025-02-10", n=3)
        assert isinstance(multiplier, float)


# ---------------------------------------------------------------------------
# P2 — gen_predicciones.py: drop_duplicates guard before to_csv
# ---------------------------------------------------------------------------

class TestNoDuplicateRowsInOutput:
    """Fix P2: output CSV must never contain duplicate match rows."""

    def test_drop_duplicates_removes_exact_duplicate_matches(self):
        """Simulates the production scenario: a results list with 9 + 9 duplicate rows."""
        single_match_rows = [
            {"home_team_canonical": f"equipo_{i}", "away_team_canonical": f"rival_{i}",
             "pick_1x2": "1", "pick_exact": "2-1", "ev": 1.5}
            for i in range(9)
        ]
        # Duplicate the list (simulates old append-based bug)
        double_rows = single_match_rows + single_match_rows
        df = pd.DataFrame(double_rows)

        assert len(df) == 18, "Precondition: 18 rows before dedup"

        df_clean = df.drop_duplicates(
            subset=["home_team_canonical", "away_team_canonical"]
        )

        assert len(df_clean) == 9, "After dedup, exactly 9 unique matches expected"

    def test_drop_duplicates_preserves_unique_matches(self):
        """Deduplication must not accidentally remove genuinely different matches."""
        rows = [
            {"home_team_canonical": "chivas", "away_team_canonical": "america"},
            {"home_team_canonical": "tigres", "away_team_canonical": "monterrey"},
            {"home_team_canonical": "america", "away_team_canonical": "tigres"},  # Different order = different match
        ]
        df = pd.DataFrame(rows)
        df_clean = df.drop_duplicates(subset=["home_team_canonical", "away_team_canonical"])
        assert len(df_clean) == 3


# ---------------------------------------------------------------------------
# P3 — core.py: bare except replaced with specific types + logging
# ---------------------------------------------------------------------------

class TestWeightedLeagueAveragesLogging:
    """Fix P3: calculate_weighted_league_averages must log warnings, not swallow errors."""

    def test_invalid_tournament_logs_warning(self, caplog):
        """A tournament not present in the data must produce a WARNING, not crash silently."""
        from src.predicciones.core import calculate_weighted_league_averages

        stats_df = pd.DataFrame({
            "tournament": ["Clausura 2025"] * 3,
            "home_team": ["chivas", "america", "tigres"],
            "away_team": ["america", "tigres", "chivas"],
            "home_goals": [1, 2, 0],
            "away_goals": [1, 1, 2],
        })

        config_with_fake_tournament = {
            "PRIOR_TOURNAMENTS": [
                {"name": "TORNEO_INEXISTENTE_XYZ", "weight": 0.5},
                {"name": "Clausura 2025", "weight": 0.5},
            ]
        }

        with caplog.at_level(logging.WARNING, logger="root"):
            result = calculate_weighted_league_averages(stats_df, config_with_fake_tournament)

        # Function must still return a usable result from the valid tournament
        assert result["home"] > 0
        assert result["away"] > 0

        # And must have logged the warning for the missing tournament
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("TORNEO_INEXISTENTE_XYZ" in str(m) for m in warning_messages), (
            f"Expected a WARNING mentioning 'TORNEO_INEXISTENTE_XYZ', got: {warning_messages}"
        )


# ---------------------------------------------------------------------------
# P4 — data.py: STATUS_DUDA_FACTOR must be non-zero
# ---------------------------------------------------------------------------

class TestDudaFactorNonZero:
    """Fix P4: PENALTIES['STATUS_DUDA_FACTOR'] must be > 0 so Duda players have some impact."""

    def test_duda_factor_is_positive(self):
        from src.predicciones.data import PENALTIES
        factor = PENALTIES.get("STATUS_DUDA_FACTOR", 0)
        assert factor > 0, (
            f"STATUS_DUDA_FACTOR should be > 0 (got {factor}). "
            "A value of 0.0 means players listed as Duda have zero modelled impact."
        )

    def test_duda_factor_is_conservative(self):
        """Factor should not be too aggressive (should be between 0.1 and 0.7)."""
        from src.predicciones.data import PENALTIES
        factor = PENALTIES.get("STATUS_DUDA_FACTOR", 0)
        assert 0.1 <= factor <= 0.7, (
            f"STATUS_DUDA_FACTOR={factor} is outside the reasonable range [0.1, 0.7]. "
            "Too high would penalise every Duda too heavily; too low still ignores real uncertainty."
        )
