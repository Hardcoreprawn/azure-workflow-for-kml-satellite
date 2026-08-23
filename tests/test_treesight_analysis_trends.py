"""Unit tests for treesight.analysis.trends (pure logic, no HTTP dependency)."""

from __future__ import annotations

import pytest

from treesight.analysis.trends import (
    calculate_trends,
    default_analysis,
    sanitise_for_prompt,
)


class TestSanitiseForPrompt:
    def test_strips_special_characters(self):
        # Angle brackets and slashes are stripped; parentheses are allowed
        assert sanitise_for_prompt("<script>") == "script"
        # Leading stripped chars leave "DROP TABLE--" after strip()
        assert sanitise_for_prompt("'; DROP TABLE--") == "DROP TABLE--"

    def test_allows_safe_characters(self):
        assert sanitise_for_prompt("Mountsorrel, UK") == "Mountsorrel, UK"

    def test_truncates_to_200_chars(self):
        long = "a" * 300
        assert len(sanitise_for_prompt(long)) == 200

    def test_non_string_returns_empty(self):
        assert sanitise_for_prompt(42) == ""  # type: ignore[arg-type]
        assert sanitise_for_prompt(None) == ""  # type: ignore[arg-type]

    def test_strips_control_characters(self):
        assert sanitise_for_prompt("test\x00\x01") == "test"

    def test_allows_dates(self):
        assert sanitise_for_prompt("2023-01-15") == "2023-01-15"


class TestDefaultAnalysis:
    def test_returns_expected_shape(self):
        result = default_analysis("AI unavailable")
        assert "observations" in result
        assert "summary" in result
        assert "score" in result

    def test_truncates_long_text(self):
        text = "x" * 300
        result = default_analysis(text)
        assert len(result["summary"]) == 200
        assert len(result["observations"][0]["description"]) == 150

    def test_score_is_neutral(self):
        assert default_analysis("msg")["score"] == 0.5


class TestCalculateTrendsNdvi:
    def _entry(self, year: int, season: str, mean: float) -> dict:
        return {"date": f"{year}-06-01", "season": season, "year": year, "mean": mean}

    def test_stable_trajectory(self):
        series = [self._entry(y, "summer", 0.55) for y in range(2020, 2024)]
        result = calculate_trends(series, [])
        assert result["ndvi_trajectory"] == "Stable"
        assert result["ndvi_yoy_avg_change"] == pytest.approx(0.0, abs=1e-4)

    def test_declining_trajectory(self):
        series = [
            self._entry(2020, "summer", 0.65),
            self._entry(2021, "summer", 0.50),
            self._entry(2022, "summer", 0.35),
        ]
        result = calculate_trends(series, [])
        assert result["ndvi_trajectory"] == "Declining"

    def test_improving_trajectory(self):
        series = [
            self._entry(2020, "summer", 0.30),
            self._entry(2021, "summer", 0.45),
            self._entry(2022, "summer", 0.60),
        ]
        result = calculate_trends(series, [])
        assert result["ndvi_trajectory"] == "Improving"

    def test_seasonal_variation_not_flagged_as_event(self):
        """Winter-to-summer swings should NOT produce significant events."""
        series = []
        for yr in range(2020, 2024):
            series.append(self._entry(yr, "winter", 0.25))
            series.append(self._entry(yr, "summer", 0.60))
        result = calculate_trends(series, [])
        # Events should compare years, not seasonal jumps
        for event in result.get("significant_events", []):
            assert "vs" in event, f"Should be YoY comparison: {event}"

    def test_significant_event_flagged(self):
        series = [
            self._entry(2021, "summer", 0.65),
            self._entry(2022, "summer", 0.40),  # drop > 0.1
        ]
        result = calculate_trends(series, [])
        assert len(result["significant_events"]) >= 1

    def test_per_season_summary(self):
        series = [
            self._entry(2020, "summer", 0.50),
            self._entry(2021, "summer", 0.55),
        ]
        result = calculate_trends(series, [])
        assert "ndvi_by_season" in result
        assert "summer" in result["ndvi_by_season"]

    def test_empty_series_returns_empty_dict(self):
        result = calculate_trends([], [])
        assert result == {}

    def test_single_entry_no_trajectory(self):
        """Need at least 2 entries for trajectory."""
        result = calculate_trends([{"mean": 0.5, "season": "summer", "year": 2022}], [])
        assert "ndvi_trajectory" not in result


class TestCalculateTrendsWeather:
    def _w(self, month: str, temp: float, precip: float) -> dict:
        return {"month": month, "temperature": temp, "precipitation": precip}

    def test_temp_avg_computed(self):
        series = [self._w("2023-01", 5.0, 80), self._w("2023-07", 20.0, 50)]
        result = calculate_trends([], series)
        assert result["temp_avg"] == pytest.approx(12.5, abs=0.1)

    def test_seasonal_temp_change_labelled(self):
        # 12 months of data: first temp 3°C, last temp 20°C → delta=17°C over 11 month span
        months = [f"2022-{m:02d}" for m in range(1, 13)]
        temps = [3, 4, 8, 12, 16, 20, 22, 21, 17, 12, 7, 20]
        series = [{"month": m, "temperature": t, "precipitation": 60} for m, t in zip(months, temps, strict=True)]
        result = calculate_trends([], series)
        assert result["temp_change_source"] == "Seasonal pattern (expected)"

    def test_dry_months_identified(self):
        series = [self._w("2023-01", 25.0, 3), self._w("2023-02", 26.0, 60)]
        result = calculate_trends([], series)
        assert "2023-01" in result["dry_months"]

    def test_wet_months_identified(self):
        series = [self._w("2023-01", 25.0, 200), self._w("2023-02", 26.0, 60)]
        result = calculate_trends([], series)
        assert "2023-01" in result["wet_months"]
