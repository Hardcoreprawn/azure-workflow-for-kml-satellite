"""Tests for _calculate_trends statistical accuracy.

Validates that the trend calculator:
- Does NOT confuse seasonal NDVI variation with anomalies
- Correctly identifies year-over-year same-season changes
- Handles real-world weather patterns (seasonal cycles)
- Produces accurate per-season summaries
"""

from __future__ import annotations

from typing import Any

import pytest

from blueprints.analysis import (
    _calculate_trends,  # pyright: ignore[reportPrivateUsage]
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ndvi_entry(year: int, season: str, mean: float, *, start: str = "") -> dict[str, Any]:
    """Build an NDVI timeseries entry matching the frontend format."""
    return {
        "date": start or f"{year}-06-01",
        "season": season,
        "year": year,
        "label": f"{season.capitalize()} {year}",
        "is_naip": False,
        "mean": mean,
        "min": round(mean - 0.1, 3),
        "max": round(mean + 0.15, 3),
    }


def _make_weather_entry(month: str, temp: float, precip: float) -> dict[str, Any]:
    return {"month": month, "month_index": 0, "temperature": temp, "precipitation": precip}


# ---------------------------------------------------------------------------
# NDVI trend tests
# ---------------------------------------------------------------------------


class TestNdviTrends:
    """Verify NDVI trend calculations are seasonally-aware."""

    def test_stable_vegetation_not_flagged(self):
        """Same summer NDVI across years → trajectory = Stable, no events."""
        series = [
            _make_ndvi_entry(2020, "summer", 0.55),
            _make_ndvi_entry(2021, "summer", 0.54),
            _make_ndvi_entry(2022, "summer", 0.56),
            _make_ndvi_entry(2023, "summer", 0.55),
        ]
        result = _calculate_trends(series, [])
        assert result["ndvi_trajectory"] == "Stable"
        assert len(result.get("significant_events", [])) == 0

    def test_seasonal_variation_not_anomaly(self):
        """Winter-to-summer NDVI swings should NOT produce 'significant events'."""
        series: list[dict[str, Any]] = []
        for yr in range(2020, 2024):
            series.append(_make_ndvi_entry(yr, "winter", 0.25))
            series.append(_make_ndvi_entry(yr, "spring", 0.42))
            series.append(_make_ndvi_entry(yr, "summer", 0.62))
            series.append(_make_ndvi_entry(yr, "autumn", 0.38))

        result = _calculate_trends(series, [])

        # Year-over-year same-season comparison → stable
        assert result["ndvi_trajectory"] == "Stable"
        # Events should reference year-over-year changes, not seasonal jumps
        for event in result.get("significant_events", []):
            # Each event should mention a year comparison, not a generic "spike"
            assert "vs" in event, f"Event should compare years: {event}"

    def test_real_decline_detected(self):
        """Summer NDVI declining year-over-year should be flagged."""
        series = [
            _make_ndvi_entry(2020, "summer", 0.65),
            _make_ndvi_entry(2021, "summer", 0.55),
            _make_ndvi_entry(2022, "summer", 0.42),
            _make_ndvi_entry(2023, "summer", 0.30),
        ]
        result = _calculate_trends(series, [])
        assert result["ndvi_trajectory"] == "Declining"
        assert result["ndvi_yoy_avg_change"] < -0.05
        assert len(result.get("significant_events", [])) >= 1

    def test_recovery_detected(self):
        """Summer NDVI recovering year-over-year should be marked Improving."""
        series = [
            _make_ndvi_entry(2020, "summer", 0.30),
            _make_ndvi_entry(2021, "summer", 0.40),
            _make_ndvi_entry(2022, "summer", 0.52),
            _make_ndvi_entry(2023, "summer", 0.60),
        ]
        result = _calculate_trends(series, [])
        assert result["ndvi_trajectory"] == "Improving"
        assert result["ndvi_yoy_avg_change"] > 0.02

    def test_per_season_summary(self):
        """Season breakdown should contain avg/min/max per season."""
        series = [
            _make_ndvi_entry(2020, "summer", 0.60),
            _make_ndvi_entry(2021, "summer", 0.65),
            _make_ndvi_entry(2020, "winter", 0.20),
            _make_ndvi_entry(2021, "winter", 0.22),
        ]
        result = _calculate_trends(series, [])
        assert "ndvi_by_season" in result
        assert "summer" in result["ndvi_by_season"]
        assert "winter" in result["ndvi_by_season"]
        assert result["ndvi_by_season"]["summer"]["avg"] == pytest.approx(0.625, abs=0.01)  # pyright: ignore[reportUnknownMemberType]
        assert result["ndvi_by_season"]["winter"]["avg"] == pytest.approx(0.21, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_null_entries_ignored(self):
        """Frames with null NDVI should not crash or skew averages."""
        series: list[dict[str, Any]] = [
            _make_ndvi_entry(2020, "summer", 0.55),
            {
                "date": "2020-12-01",
                "season": "winter",
                "year": 2020,
                "mean": None,
                "min": None,
                "max": None,
            },
            _make_ndvi_entry(2021, "summer", 0.57),
        ]
        result = _calculate_trends(series, [])
        assert result["ndvi_avg"] == pytest.approx(0.56, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_volatility_classification(self):
        """High variation in NDVI across same-season values → High volatility."""
        series = [
            _make_ndvi_entry(2018, "summer", 0.70),
            _make_ndvi_entry(2019, "summer", 0.30),
            _make_ndvi_entry(2020, "summer", 0.65),
            _make_ndvi_entry(2021, "summer", 0.25),
            _make_ndvi_entry(2022, "summer", 0.60),
        ]
        result = _calculate_trends(series, [])
        assert result["ndvi_volatility"] == "High"


# ---------------------------------------------------------------------------
# Weather trend tests
# ---------------------------------------------------------------------------


class TestWeatherTrends:
    """Verify weather analysis uses actual month labels."""

    def test_seasonal_temp_not_anomaly(self):
        """12-month span with large swing → Seasonal pattern, not anomaly."""
        weather = [
            _make_weather_entry("2023-01", 2.0, 60),
            _make_weather_entry("2023-04", 10.0, 45),
            _make_weather_entry("2023-07", 20.0, 30),
            _make_weather_entry("2023-10", 8.0, 70),
            _make_weather_entry("2023-12", 18.0, 55),  # +16°C first→last over 11 months
        ]
        result = _calculate_trends([], weather)
        assert result["temp_change_source"] == "Seasonal pattern (expected)"

    def test_rapid_temp_change_flagged(self):
        """2-month span with 5°C jump → Potential anomaly."""
        weather = [
            _make_weather_entry("2023-06", 18.0, 30),
            _make_weather_entry("2023-07", 23.5, 25),
        ]
        result = _calculate_trends([], weather)
        assert "anomaly" in result["temp_change_source"].lower()

    def test_dry_months_detected(self):
        """Months with <10mm precipitation should be flagged."""
        weather = [
            _make_weather_entry("2023-01", 5.0, 80),
            _make_weather_entry("2023-07", 22.0, 5),
            _make_weather_entry("2023-08", 21.0, 3),
        ]
        result = _calculate_trends([], weather)
        assert "2023-07" in result.get("dry_months", [])
        assert "2023-08" in result.get("dry_months", [])

    def test_weather_period_uses_labels(self):
        """Weather period should reference actual YYYY-MM labels."""
        weather = [
            _make_weather_entry("2020-03", 8.0, 50),
            _make_weather_entry("2023-09", 16.0, 40),
        ]
        result = _calculate_trends([], weather)
        assert result["weather_period"] == "2020-03 to 2023-09"

    def test_precip_totals(self):
        """Precipitation total should be accurate."""
        weather = [
            _make_weather_entry("2023-01", 5.0, 80.5),
            _make_weather_entry("2023-02", 6.0, 72.3),
            _make_weather_entry("2023-03", 9.0, 55.2),
        ]
        result = _calculate_trends([], weather)
        assert result["precip_total"] == pytest.approx(208.0, abs=0.1)  # pyright: ignore[reportUnknownMemberType]
        assert result["precip_avg"] == pytest.approx(69.3, abs=0.1)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Combined (NDVI + Weather) tests
# ---------------------------------------------------------------------------


class TestCombinedTrends:
    """Test that combined NDVI + weather data produces coherent analysis."""

    def test_full_multi_year_dataset(self):
        """Realistic 4-year, 4-season dataset should produce valid trends."""
        ndvi: list[dict[str, Any]] = []
        weather: list[dict[str, Any]] = []
        for yr in range(2020, 2024):
            ndvi.append(_make_ndvi_entry(yr, "winter", 0.22 + (yr - 2020) * 0.01))
            ndvi.append(_make_ndvi_entry(yr, "spring", 0.40 + (yr - 2020) * 0.01))
            ndvi.append(_make_ndvi_entry(yr, "summer", 0.60 + (yr - 2020) * 0.01))
            ndvi.append(_make_ndvi_entry(yr, "autumn", 0.35 + (yr - 2020) * 0.01))
            for m, temp, precip in [
                (1, 3.0, 70),
                (4, 11.0, 50),
                (7, 21.0, 35),
                (10, 9.0, 65),
            ]:
                weather.append(_make_weather_entry(f"{yr}-{m:02d}", temp, precip))

        result = _calculate_trends(ndvi, weather)

        # 0.01/yr × 3 years = 0.03 yoy avg change (above 0.02 threshold)
        assert result["ndvi_trajectory"] == "Improving"
        assert "ndvi_by_season" in result
        assert len(result["ndvi_by_season"]) == 4
        assert result["temp_change_source"] == "Seasonal pattern (expected)"
        assert result["precip_total"] > 0

    def test_empty_series(self):
        """Empty inputs should return empty dict, not crash."""
        result = _calculate_trends([], [])
        assert result == {}

    def test_single_ndvi_point(self):
        """Single NDVI point → no trajectory, only season summary."""
        series = [_make_ndvi_entry(2023, "summer", 0.55)]
        result = _calculate_trends(series, [])
        assert "ndvi_trajectory" not in result
        assert result.get("significant_events", []) == []
