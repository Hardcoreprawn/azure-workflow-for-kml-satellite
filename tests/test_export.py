"""Tests for export endpoints — GeoJSON and CSV (M4 §4.6)."""

from __future__ import annotations

import csv
import io
import json

import pytest

from blueprints.export import _build_csv, _build_geojson


@pytest.fixture()
def enrichment_manifest():
    """Realistic enrichment manifest as stored in blob storage."""
    return {
        "coords": [
            [36.8, -1.3],
            [36.81, -1.3],
            [36.81, -1.31],
            [36.8, -1.31],
        ],
        "bbox": [[36.8, -1.31], [36.81, -1.31], [36.81, -1.3], [36.8, -1.3]],
        "center": {"lat": -1.305, "lon": 36.805},
        "frame_plan": [
            {
                "year": 2023,
                "season": "spring",
                "start": "2023-03-01",
                "end": "2023-05-31",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "label": "Spring 2023",
            },
            {
                "year": 2023,
                "season": "summer",
                "start": "2023-06-01",
                "end": "2023-08-31",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "label": "Summer 2023",
            },
            {
                "year": 2024,
                "season": "spring",
                "start": "2024-03-01",
                "end": "2024-05-31",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "label": "Spring 2024",
            },
        ],
        "ndvi_stats": [
            {"mean": 0.45, "min": 0.1, "max": 0.72, "std": 0.12, "scene_id": "S2A_123"},
            {"mean": 0.62, "min": 0.3, "max": 0.85, "std": 0.09},
            {"mean": 0.48, "min": 0.15, "max": 0.74, "std": 0.11, "scene_id": "S2A_456"},
        ],
        "weather_daily": {
            "dates": ["2023-03-15", "2023-06-15", "2024-03-15"],
            "temperature_2m_mean": [12.5, 22.3, 13.1],
            "precipitation_sum": [5.2, 1.0, 4.8],
        },
        "weather_monthly": [
            {"month": "2023-03", "mean_temp": 12.5, "total_precip": 45.0},
            {"month": "2023-06", "mean_temp": 22.3, "total_precip": 12.0},
        ],
        "change_detection": {
            "season_changes": [
                {
                    "season": "spring",
                    "year_a": 2023,
                    "year_b": 2024,
                    "ndvi_mean_delta": 0.03,
                },
            ],
            "summary": {
                "comparisons": 1,
                "trajectory": "stable",
            },
        },
        "enriched_at": "2025-01-15T10:30:00Z",
        "enrichment_duration_seconds": 42.5,
    }


class TestBuildGeoJSON:
    """Unit tests for GeoJSON construction."""

    def test_returns_feature_collection(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        assert result["type"] == "FeatureCollection"
        assert "features" in result

    def test_one_feature_per_frame_plus_summary(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        # 3 frame features + 1 summary feature
        assert len(result["features"]) == 4

    def test_frame_features_have_polygon_geometry(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        for feat in result["features"][:3]:
            assert feat["geometry"]["type"] == "Polygon"

    def test_polygon_ring_is_closed(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        ring = result["features"][0]["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1], "Polygon ring must be closed"

    def test_frame_properties_include_ndvi(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        props = result["features"][0]["properties"]
        assert props["ndvi_mean"] == 0.45
        assert props["ndvi_min"] == 0.1
        assert props["ndvi_max"] == 0.72
        assert props["ndvi_std"] == 0.12
        assert props["ndvi_scene_id"] == "S2A_123"

    def test_frame_properties_include_metadata(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        props = result["features"][0]["properties"]
        assert props["label"] == "Spring 2023"
        assert props["year"] == 2023
        assert props["season"] == "spring"
        assert props["start_date"] == "2023-03-01"
        assert props["end_date"] == "2023-05-31"
        assert props["collection"] == "sentinel-2-l2a"

    def test_summary_feature_is_point(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        summary = result["features"][-1]
        assert summary["geometry"]["type"] == "Point"
        assert summary["properties"]["type"] == "summary"

    def test_summary_includes_change_detection(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        summary = result["features"][-1]["properties"]
        assert summary["change_detection_summary"]["trajectory"] == "stable"

    def test_summary_includes_weather_monthly(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        summary = result["features"][-1]["properties"]
        assert len(summary["weather_monthly"]) == 2

    def test_empty_manifest_produces_empty_collection(self):
        result = _build_geojson({})
        assert result["type"] == "FeatureCollection"
        assert result["features"] == []

    def test_geojson_is_serialisable(self, enrichment_manifest):
        result = _build_geojson(enrichment_manifest)
        body = json.dumps(result, default=str)
        parsed = json.loads(body)
        assert parsed["type"] == "FeatureCollection"


class TestBuildCSV:
    """Unit tests for CSV construction."""

    def test_returns_string(self, enrichment_manifest):
        result = _build_csv(enrichment_manifest)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_has_header_row(self, enrichment_manifest):
        result = _build_csv(enrichment_manifest)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "frame_index" in header
        assert "ndvi_mean" in header
        assert "mean_temp_c" in header

    def test_one_row_per_frame(self, enrichment_manifest):
        result = _build_csv(enrichment_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 3

    def test_ndvi_values_present(self, enrichment_manifest):
        result = _build_csv(enrichment_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["ndvi_mean"] == "0.45"
        assert rows[1]["ndvi_mean"] == "0.62"

    def test_weather_aggregated_per_frame(self, enrichment_manifest):
        result = _build_csv(enrichment_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        # Frame 0 (spring 2023-03-01 to 2023-05-31) includes daily date 2023-03-15
        assert rows[0]["mean_temp_c"] == "12.5"
        assert rows[0]["total_precip_mm"] == "5.2"

    def test_change_detection_delta(self, enrichment_manifest):
        result = _build_csv(enrichment_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        # Frame 2 is spring 2024 — has a change detection entry
        assert rows[2]["ndvi_change_from_previous"] == "0.03"
        # Frame 0 and 1 have no change entry
        assert rows[0]["ndvi_change_from_previous"] == ""

    def test_empty_manifest_produces_header_only(self):
        result = _build_csv({})
        lines = result.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_missing_ndvi_produces_empty_cells(self):
        manifest = {
            "frame_plan": [
                {
                    "year": 2023,
                    "season": "spring",
                    "start": "2023-03-01",
                    "end": "2023-05-31",
                    "collection": "sentinel-2-l2a",
                    "is_naip": False,
                    "label": "Spring 2023",
                },
            ],
            "ndvi_stats": [None],
        }
        result = _build_csv(manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["ndvi_mean"] == ""
        assert rows[0]["ndvi_min"] == ""
