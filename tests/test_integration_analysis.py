"""End-to-end integration tests: enrichment manifest → frontend transform → analysis.

Validates the full data chain without hitting external APIs:
1. build_frame_plan produces season-tagged frames
2. Frontend-equivalent transform builds ndvi/weather timeseries
3. _calculate_trends produces statistically correct results
4. Prompt context string is well-formed with real dates and seasons
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from blueprints.analysis import (
    _calculate_trends,  # pyright: ignore[reportPrivateUsage]
)
from treesight.pipeline.enrichment import (
    aggregate_weather_monthly,
    build_frame_plan,
)

# ---------------------------------------------------------------------------
# Simulate the frontend JavaScript data transform in Python
# ---------------------------------------------------------------------------


def _frontend_transform_ndvi(
    frame_plan: list[dict[str, Any]],
    ndvi_stats: list[dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Mirrors website/index.html ndviTimeseries builder."""
    timeseries: list[dict[str, Any]] = []
    length = min(len(frame_plan), len(ndvi_stats))
    for i in range(length):
        f = frame_plan[i]
        entry: dict[str, Any] = {
            "date": f["start"],
            "season": f.get("season"),
            "year": f.get("year"),
            "label": f.get("label", ""),
            "is_naip": bool(f.get("is_naip")),
        }
        stat = ndvi_stats[i]
        if stat is not None:
            entry["mean"] = float(stat["mean"])
            entry["min"] = float(stat["min"])
            entry["max"] = float(stat["max"])
        else:
            entry["mean"] = None
            entry["min"] = None
            entry["max"] = None
        timeseries.append(entry)
    return timeseries


def _frontend_transform_weather(
    monthly_weather: dict[str, Any],
) -> list[dict[str, Any]]:
    """Mirrors website/index.html weatherTimeseries builder."""
    timeseries: list[dict[str, Any]] = []
    labels: list[Any] = monthly_weather.get("labels", [])
    temps: list[Any] = monthly_weather.get("temp", [])
    precips: list[Any] = monthly_weather.get("precip", [])
    length = min(len(labels), len(temps), len(precips))
    for j in range(length):
        if temps[j] is not None and precips[j] is not None:
            timeseries.append(
                {
                    "month": labels[j],
                    "month_index": j,
                    "temperature": float(temps[j]),
                    "precipitation": float(precips[j]),
                }
            )
    return timeseries


# ---------------------------------------------------------------------------
# Fixtures: realistic enrichment data
# ---------------------------------------------------------------------------

# UK coords (Mountsorrel area — within CONUS check will FAIL, so no NAIP)
# All coordinates are [lon, lat] per project convention (see constants.py).
UK_COORDS = [[-1.15, 52.72], [-1.14, 52.72], [-1.14, 52.71], [-1.15, 52.71]]

# Tiny UK parcel (~20 m across) — too small for useful Sentinel-2 RGB.
TINY_UK_COORDS = [
    [-1.15000, 52.72000],
    [-1.14972, 52.72000],
    [-1.14972, 52.71982],
    [-1.15000, 52.71982],
]

# US coords (Colorado, within CONUS — has NAIP)
US_COORDS = [[-105.0, 39.0], [-104.9, 39.0], [-104.9, 38.9], [-105.0, 38.9]]

# Tiny US parcel (~20 m across) — still suitable for NAIP RGB.
TINY_US_COORDS = [
    [-105.00000, 39.00000],
    [-104.99978, 39.00000],
    [-104.99978, 38.99982],
    [-105.00000, 38.99982],
]


def _make_fake_ndvi_stats(
    frame_plan: list[dict[str, Any]],
    base_ndvi: dict[str, float] | None = None,
    yearly_trend: float = 0.0,
    gap_indices: set[int] | None = None,
) -> list[dict[str, Any] | None]:
    """Generate fake NDVI stats aligned to a frame plan.

    base_ndvi: season → base mean NDVI value
    yearly_trend: per-year change added to base
    gap_indices: indices that return None (cloud cover / no data)
    """
    if base_ndvi is None:
        base_ndvi = {
            "winter": 0.22,
            "spring": 0.42,
            "summer": 0.62,
            "autumn": 0.35,
        }
    if gap_indices is None:
        gap_indices = set()

    stats: list[dict[str, Any] | None] = []
    first_year: int = frame_plan[0]["year"] if frame_plan else 2018
    for i, f in enumerate(frame_plan):
        if i in gap_indices:
            stats.append(None)
            continue
        season = f["season"]
        year = f["year"]
        base = base_ndvi.get(season, 0.40)
        mean = round(base + (year - first_year) * yearly_trend, 3)
        stats.append(
            {
                "mean": mean,
                "min": round(mean - 0.12, 3),
                "max": round(mean + 0.15, 3),
            }
        )
    return stats


def _make_fake_weather_daily(
    start_year: int = 2018,
    end_year: int = 2025,
) -> dict[str, Any]:
    """Generate fake daily weather data for aggregate_weather_monthly."""
    dates: list[str] = []
    temps: list[float] = []
    precips: list[float] = []
    for yr in range(start_year, end_year + 1):
        for m in range(1, 13):
            for d in [1, 15]:
                dates.append(f"{yr}-{m:02d}-{d:02d}")
                # Seasonal temperature pattern
                seasonal_temp = 10 + 10 * _seasonal_factor(m)
                temps.append(round(seasonal_temp, 1))
                # Precipitation: higher in winter
                seasonal_precip = 2.5 if m in (6, 7, 8) else 4.0
                precips.append(round(seasonal_precip, 1))
    return {
        "dates": dates,
        "temp": temps,
        "precip": precips,
        "latitude": 52.72,
        "longitude": -1.15,
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
    }


def _seasonal_factor(month: int) -> float:
    """Sine-wave seasonal factor: -1 in winter, +1 in summer."""
    return math.sin((month - 1) / 12 * 2 * math.pi - math.pi / 2)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestFramePlanIntegrity:
    """Verify enrichment frame plan has the metadata analysis needs."""

    def test_uk_frames_have_season_metadata(self):
        """UK frame plan (no NAIP) should have year/season on every frame."""
        plan = build_frame_plan(UK_COORDS)
        assert len(plan) > 0
        for f in plan:
            assert "year" in f, f"Missing year: {f}"
            assert "season" in f, f"Missing season: {f}"
            assert "start" in f, f"Missing start: {f}"
            assert "end" in f, f"Missing end: {f}"
            assert f["season"] in ("winter", "spring", "summer", "autumn")

    def test_us_frames_include_naip(self):
        """US frame plan should include NAIP summer-only frames."""
        plan = build_frame_plan(US_COORDS)
        naip_frames = [f for f in plan if f.get("is_naip")]
        assert len(naip_frames) > 0
        for f in naip_frames:
            assert f["season"] == "summer"
            assert f["collection"] == "naip"

    def test_frame_dates_are_chronological(self):
        """Frame start dates should be monotonically increasing."""
        plan = build_frame_plan(UK_COORDS)
        starts = [f["start"] for f in plan]
        assert starts == sorted(starts)

    def test_small_non_naip_aoi_marks_rgb_as_unsuitable(self):
        """Tiny non-US AOIs should prefer NDVI over coarse RGB display."""
        plan = build_frame_plan(TINY_UK_COORDS)
        assert len(plan) > 0

        s2_frames = [f for f in plan if f["collection"] == "sentinel-2-l2a"]
        assert s2_frames, "expected Sentinel-2 frames for tiny UK AOI"
        assert any(f["rgb_display_suitable"] is False for f in s2_frames)
        assert all(
            f["preferred_layer"] == "ndvi" for f in s2_frames if not f["rgb_display_suitable"]
        )

    def test_small_naip_aoi_keeps_rgb_as_suitable(self):
        """Tiny CONUS AOIs should keep NAIP RGB as the preferred display layer."""
        plan = build_frame_plan(TINY_US_COORDS)
        naip_frames = [f for f in plan if f.get("is_naip")]
        assert naip_frames, "expected NAIP frames for tiny US AOI"
        assert all(f["rgb_display_suitable"] is True for f in naip_frames)
        assert all(f["preferred_layer"] == "rgb" for f in naip_frames)

    def test_legacy_naip_frames_use_higher_gsd(self):
        """NAIP frames from 2014 or earlier must use 1.0 m/px GSD, not 0.6 m/px.

        Pre-2015 NAIP was collected at 1 m/px; using 0.6 m/px under-estimates
        the display-pixel count and could incorrectly flag frames as unsuitable.
        """
        from treesight.constants import NAIP_LEGACY_GSD_M
        from treesight.pipeline.enrichment.frames import _annotate_display_metadata

        legacy_frame = {
            "label": "2014 Summer",
            "year": 2014,
            "season": "summer",
            "start": "2014-06-01",
            "end": "2014-08-31",
            "collection": "naip",
            "is_naip": True,
        }
        modern_frame = dict(legacy_frame, year=2020, label="2020 Summer")

        annotated = _annotate_display_metadata([legacy_frame, modern_frame], TINY_US_COORDS)
        legacy = annotated[0]
        modern = annotated[1]

        assert legacy["display_resolution_m"] == NAIP_LEGACY_GSD_M, (
            "2014 NAIP frame should use the legacy 1.0 m/px GSD"
        )
        assert modern["display_resolution_m"] < NAIP_LEGACY_GSD_M, (
            "post-2014 NAIP frame should use the finer 0.6 m/px GSD"
        )
        # Legacy is coarser → fewer estimated pixels for the same AOI
        assert legacy["estimated_display_pixels"] < modern["estimated_display_pixels"]


class TestFrontendTransform:
    """Verify the Python replica of the JS data transform is correct."""

    def test_ndvi_timeseries_preserves_all_frames(self):
        """Even frames with no NDVI should appear (mean=null)."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan, gap_indices={0, 5, 10})
        ts = _frontend_transform_ndvi(plan, stats)

        assert len(ts) == len(plan)
        assert ts[0]["mean"] is None
        assert ts[5]["mean"] is None
        assert ts[10]["mean"] is None
        # Non-gap frames have values
        assert ts[1]["mean"] is not None

    def test_ndvi_entries_have_season_and_year(self):
        """Every NDVI entry should carry season/year for trend grouping."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan)
        ts = _frontend_transform_ndvi(plan, stats)

        for entry in ts:
            assert entry["season"] in ("winter", "spring", "summer", "autumn")
            assert isinstance(entry["year"], int)
            assert entry["date"]  # non-empty start date

    def test_weather_timeseries_has_month_labels(self):
        """Weather entries should have actual YYYY-MM month strings."""
        weather = _make_fake_weather_daily()
        monthly = aggregate_weather_monthly(weather)
        ts = _frontend_transform_weather(monthly)

        assert len(ts) > 0
        for entry in ts:
            assert "month" in entry
            # Validate YYYY-MM format
            parts = entry["month"].split("-")
            assert len(parts) == 2
            assert len(parts[0]) == 4
            assert len(parts[1]) == 2

    def test_weather_monthly_aggregation_correct(self):
        """Monthly aggregation should produce correct label count."""
        weather = _make_fake_weather_daily(2020, 2023)
        monthly = aggregate_weather_monthly(weather)
        # 4 years × 12 months = 48 monthly labels
        assert len(monthly["labels"]) == 48
        assert monthly["labels"][0] == "2020-01"
        assert monthly["labels"][-1] == "2023-12"


class TestEndToEndAnalysis:
    """Full chain: frame_plan → fake NDVI → frontend transform → _calculate_trends."""

    def test_stable_uk_site(self):
        """UK site with stable vegetation across 8 years."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan, yearly_trend=0.0)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        weather = _make_fake_weather_daily()
        monthly = aggregate_weather_monthly(weather)
        weather_ts = _frontend_transform_weather(monthly)

        result = _calculate_trends(ndvi_ts, weather_ts)

        assert result["ndvi_trajectory"] == "Stable"
        assert len(result.get("significant_events", [])) == 0
        assert "ndvi_by_season" in result
        assert len(result["ndvi_by_season"]) == 4
        # Weather period should span our full range
        assert "weather_period" in result
        assert "2018" in result["weather_period"]

    def test_declining_vegetation(self):
        """Declining NDVI of -0.01/year across all seasons → Declining."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan, yearly_trend=-0.01)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        result = _calculate_trends(ndvi_ts, [])

        # -0.01/yr × 7 years = -0.07 total, but yoy_avg_change = avg of per-season
        # Each season has ~8 data points spanning 2018-2025
        assert result["ndvi_trajectory"] == "Declining"
        assert result["ndvi_yoy_avg_change"] < -0.02

    def test_improving_vegetation(self):
        """Improving NDVI of +0.01/year across all seasons → Improving."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan, yearly_trend=0.01)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        result = _calculate_trends(ndvi_ts, [])

        assert result["ndvi_trajectory"] == "Improving"
        assert result["ndvi_yoy_avg_change"] > 0.02

    def test_gaps_dont_break_trends(self):
        """Missing frames (clouds, etc.) shouldn't break trend detection."""
        plan = build_frame_plan(UK_COORDS)
        # ~10% gaps
        gaps = set(range(0, len(plan), 10))
        stats = _make_fake_ndvi_stats(plan, yearly_trend=0.0, gap_indices=gaps)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        result = _calculate_trends(ndvi_ts, [])

        assert result["ndvi_trajectory"] == "Stable"
        assert "ndvi_by_season" in result

    def test_per_season_means_are_sensible(self):
        """Season means should reflect the base NDVI values we set."""
        plan = build_frame_plan(UK_COORDS)
        base = {"winter": 0.20, "spring": 0.40, "summer": 0.65, "autumn": 0.35}
        stats = _make_fake_ndvi_stats(plan, base_ndvi=base, yearly_trend=0.0)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        result = _calculate_trends(ndvi_ts, [])

        for season, expected_avg in base.items():
            actual = result["ndvi_by_season"][season]["avg"]
            assert actual == pytest.approx(expected_avg, abs=0.01), (  # pyright: ignore[reportUnknownMemberType]
                f"{season}: expected ~{expected_avg}, got {actual}"
            )

    def test_weather_dry_wet_detection(self):
        """Integration: dry/wet months detected from realistic weather chain."""
        # Construct weather with known dry July and wet January
        dates: list[str] = []
        temp: list[float] = []
        precip: list[float] = []
        for d in range(1, 32):
            dates.append(f"2023-01-{d:02d}")
            temp.append(3.0)
            precip.append(6.0)  # 6mm/day × 31 = 186mm (wet)
        for d in range(1, 32):
            dates.append(f"2023-07-{d:02d}")
            temp.append(22.0)
            precip.append(0.2)  # 0.2mm/day × 31 = 6.2mm (dry)
        weather: dict[str, Any] = {
            "dates": dates,
            "temp": temp,
            "precip": precip,
        }

        monthly = aggregate_weather_monthly(weather)
        weather_ts = _frontend_transform_weather(monthly)

        result = _calculate_trends([], weather_ts)

        assert "2023-07" in result.get("dry_months", [])
        assert "2023-01" in result.get("wet_months", [])

    def test_us_site_with_naip_frames(self):
        """US site NAIP frames should be included and stats computed."""
        plan = build_frame_plan(US_COORDS)
        stats = _make_fake_ndvi_stats(plan, yearly_trend=0.0)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        naip_entries = [e for e in ndvi_ts if e.get("is_naip")]
        assert len(naip_entries) > 0

        result = _calculate_trends(ndvi_ts, [])

        # NAIP frames are all summer — they contribute to summer season
        assert "summer" in result.get("ndvi_by_season", {})
        assert result["ndvi_trajectory"] == "Stable"

    def test_significant_events_only_for_real_changes(self):
        """Only same-season year-over-year NDVI jumps > 0.1 trigger events."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan, yearly_trend=0.0)

        # Inject a dramatic summer 2022 drop
        for i, f in enumerate(plan):
            if f["year"] == 2022 and f["season"] == "summer":
                stats[i] = {"mean": 0.20, "min": 0.08, "max": 0.35}
                break

        ndvi_ts = _frontend_transform_ndvi(plan, stats)
        result = _calculate_trends(ndvi_ts, [])

        events = result.get("significant_events", [])
        assert len(events) >= 1
        # Should mention summer and 2022
        event_text = " ".join(events)
        assert "Summer" in event_text or "summer" in event_text
        assert "2022" in event_text


class TestPromptContextBuilding:
    """Verify that the context string built for the LLM is well-formed."""

    def test_context_has_all_sections(self):
        """The analysis prompt context should include NDVI, weather, events."""
        plan = build_frame_plan(UK_COORDS)
        stats = _make_fake_ndvi_stats(plan)
        ndvi_ts = _frontend_transform_ndvi(plan, stats)

        weather = _make_fake_weather_daily()
        monthly = aggregate_weather_monthly(weather)
        weather_ts = _frontend_transform_weather(monthly)

        trends = _calculate_trends(ndvi_ts, weather_ts)

        # Build the same context lines the blueprint builds
        context_lines: list[str] = []
        context_lines.append(f"NDVI Average: {trends['ndvi_avg']:.3f}")
        context_lines.append(
            f"NDVI Range: {trends['ndvi_min_val']:.3f} to {trends['ndvi_max_val']:.3f}"
        )
        context_lines.append(f"Volatility: {trends['ndvi_volatility']}")
        context_lines.append(f"Multi-year Trajectory: {trends['ndvi_trajectory']}")

        if trends.get("ndvi_by_season"):
            for skey, sdata in trends["ndvi_by_season"].items():
                context_lines.append(f"{skey.capitalize()}: avg={sdata['avg']:.3f}")

        assert trends.get("weather_period")
        context_lines.append(f"Weather data: {trends['weather_period']}")
        context_lines.append(f"Temperature: avg {trends['temp_avg']:.1f}°C")

        context_str = "\n".join(context_lines)

        # All key data should be present, non-empty, and contain real numbers
        assert "NDVI Average:" in context_str
        assert "Trajectory:" in context_str
        assert "Winter:" in context_str or "winter:" in context_str.lower()
        assert "Summer:" in context_str or "summer:" in context_str.lower()
        assert "Weather data:" in context_str
        assert "Temperature:" in context_str
