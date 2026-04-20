"""Tests for export endpoints — GeoJSON, CSV, and PDF (M4 §4.6)."""

from __future__ import annotations

import csv
import io
import json

import pytest

from blueprints.export import (
    _build_bulk_csv,
    _build_csv,
    _build_eudr_csv,
    _build_eudr_geojson,
    _build_geojson,
    _build_pdf,
    _pdf_scene_provenance_section,
    build_eudr_audit_pdf,
)


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
            "temp": [12.5, 22.3, 13.1],
            "precip": [5.2, 1.0, 4.8],
        },
        "weather_monthly": {
            "labels": ["2023-03", "2023-06"],
            "temp": [12.5, 22.3],
            "precip": [45.0, 12.0],
        },
        "change_detection": {
            "season_changes": [
                {
                    "season": "spring",
                    "year_from": 2023,
                    "year_to": 2024,
                    "mean_delta": 0.03,
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

    def test_frame_properties_include_normalized_provenance(self, enrichment_manifest):
        enrichment_manifest["frame_plan"][0]["provenance"] = {
            "collection": "sentinel-2-l2a",
            "display_search_id": "sid-s2-spring-2023",
            "ndvi_search_id": "sid-s2-spring-2023",
            "ndvi_scene_id": "S2A_123",
            "resolution_m": 10.0,
            "cloud_cover_pct": 8.5,
            "acquired_at": "2023-03-17T10:20:00Z",
            "artifact_path": "enrichment/run-1/ndvi/2023_spring.tif",
        }
        result = _build_geojson(enrichment_manifest)
        props = result["features"][0]["properties"]
        assert props["provenance"]["display_search_id"] == "sid-s2-spring-2023"
        assert props["provenance"]["ndvi_scene_id"] == "S2A_123"

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
        assert summary["weather_monthly"]["labels"] == ["2023-03", "2023-06"]

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

    def test_flattens_normalized_provenance_fields(self, enrichment_manifest):
        enrichment_manifest["frame_plan"][0]["provenance"] = {
            "display_search_id": "sid-s2-spring-2023",
            "ndvi_search_id": "sid-s2-spring-2023",
            "ndvi_scene_id": "S2A_123",
            "resolution_m": 10.0,
            "cloud_cover_pct": 8.5,
            "acquired_at": "2023-03-17T10:20:00Z",
            "artifact_path": "enrichment/run-1/ndvi/2023_spring.tif",
        }
        result = _build_csv(enrichment_manifest)
        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)
        assert row["display_search_id"] == "sid-s2-spring-2023"
        assert row["ndvi_scene_id"] == "S2A_123"
        assert row["artifact_path"] == "enrichment/run-1/ndvi/2023_spring.tif"
        assert reader.fieldnames is not None
        assert "mean_temp_c" in reader.fieldnames

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


class TestBuildPDF:
    def test_returns_pdf_bytes(self, enrichment_manifest):
        result = _build_pdf(enrichment_manifest, "run-123")
        assert isinstance(result, bytes)
        assert result.startswith(b"%PDF")

    def test_normalises_unicode_punctuation_for_core_font(self, enrichment_manifest):
        manifest = dict(enrichment_manifest)
        manifest["ndvi_stats"] = [None, *enrichment_manifest["ndvi_stats"][1:]]
        manifest["wdpa"] = {
            "checked": True,
            "is_protected": True,
            "protected_areas": [
                {
                    "name": "Reserve d’Ivoire — North",
                    "designation": "Community preserve…",
                }
            ],
        }

        result = _build_pdf(manifest, "run-unicode")
        assert result.startswith(b"%PDF")

    def test_supports_legacy_monthly_weather_list(self, enrichment_manifest):
        manifest = dict(enrichment_manifest)
        manifest["weather_monthly"] = [
            {"month": "2023-03", "mean_temp": 12.5, "total_precip": 45.0},
            {"month": "2023-06", "mean_temp": 22.3, "total_precip": 12.0},
        ]

        result = _build_pdf(manifest, "run-legacy")
        assert result.startswith(b"%PDF")

    def test_pdf_includes_scene_provenance_when_present(self, enrichment_manifest):
        """#647 — PDF must render without error when frame_plan has provenance fields."""
        manifest = dict(enrichment_manifest)
        manifest["frame_plan"] = [
            {
                "label": "2023 Wet Season",
                "year": 2023,
                "season": "wet",
                "start": "2023-03-01",
                "end": "2023-05-31",
                "collection": "sentinel-2-l2a",
                "provenance": {
                    "collection": "sentinel-2-l2a",
                    "ndvi_scene_id": "S2_20230415_T18NXM",
                    "resolution_m": 10.0,
                    "cloud_cover_pct": 5.2,
                    "acquired_at": "2023-04-15",
                },
            }
        ]
        result = _build_pdf(manifest, "run-provenance-647")
        assert result.startswith(b"%PDF")

    def test_pdf_scene_provenance_section_renders_scene_id(self):
        """#647 — _pdf_scene_provenance_section must surface scene ID and resolution."""
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()
        frame_plan = [
            {
                "label": "2023-wet",
                "collection": "sentinel-2-l2a",
                "provenance": {
                    "ndvi_scene_id": "S2A_MSIL2A_20230415",
                    "resolution_m": 10.0,
                    "cloud_cover_pct": 3.1,
                    "acquired_at": "2023-04-15",
                },
            }
        ]
        _pdf_scene_provenance_section(pdf, frame_plan)
        result = bytes(pdf.output())
        assert result.startswith(b"%PDF")

    def test_pdf_scene_provenance_section_tolerates_missing_provenance(self):
        """#647 — section must not crash when provenance key is absent."""
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()
        frame_plan = [{"label": "2023-wet", "collection": "sentinel-2-l2a"}]
        _pdf_scene_provenance_section(pdf, frame_plan)
        result = bytes(pdf.output())
        assert result.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Bulk CSV export (#311)
# ---------------------------------------------------------------------------


class TestBuildBulkCsv:
    def test_produces_per_aoi_rows(self):
        manifest = {
            "per_aoi_metrics": [
                {
                    "feature_name": "Farm A",
                    "feature_index": 0,
                    "geometry": {
                        "area_ha": 12.5,
                        "perimeter_km": 1.4,
                        "centroid_lon": 36.8,
                        "centroid_lat": -1.3,
                    },
                    "vegetation": {
                        "health_class": "healthy",
                        "trend_direction": "stable",
                        "latest_detail": {"mean": 0.72},
                    },
                    "change": {
                        "total_loss_ha": 0.1,
                        "total_gain_ha": 0.3,
                        "net_change_ha": 0.2,
                        "trajectory": "improving",
                    },
                    "weather": {"temp_mean_c": 22.5, "precip_total_mm": 350.0},
                    "ndvi_data_scope": "union",
                },
                {
                    "feature_name": "Farm B",
                    "feature_index": 1,
                    "geometry": {
                        "area_ha": 8.0,
                        "perimeter_km": 1.1,
                        "centroid_lon": 36.9,
                        "centroid_lat": -1.4,
                    },
                    "vegetation": {
                        "health_class": "stressed",
                        "trend_direction": "declining",
                        "latest_detail": {"mean": 0.35},
                    },
                    "change": {
                        "total_loss_ha": 2.5,
                        "total_gain_ha": 0.0,
                        "net_change_ha": -2.5,
                        "trajectory": "degrading",
                    },
                    "weather": {"temp_mean_c": 23.1, "precip_total_mm": 280.0},
                    "ndvi_data_scope": "union",
                },
            ],
        }

        result = _build_bulk_csv(manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["feature_name"] == "Farm A"
        assert rows[0]["area_ha"] == "12.5"
        assert rows[0]["ndvi_latest_mean"] == "0.72"
        assert rows[1]["feature_name"] == "Farm B"
        assert rows[1]["trajectory"] == "degrading"

    def test_falls_back_to_regular_csv(self, enrichment_manifest):
        result = _build_bulk_csv(enrichment_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert "frame_index" in rows[0]


# ---------------------------------------------------------------------------
# EUDR per-parcel evidence export (#582)
# ---------------------------------------------------------------------------


@pytest.fixture()
def eudr_manifest():
    """Enrichment manifest with per_aoi_enrichment for EUDR export tests."""
    return {
        "eudr_mode": True,
        "eudr_date_start": "2021-01-01",
        "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
        "center": {"lat": -1.305, "lon": 36.805},
        "enriched_at": "2026-04-16T12:00:00Z",
        "frame_plan": [
            {"year": 2023, "season": "spring", "start": "2023-03-01", "end": "2023-05-31"},
        ],
        "per_aoi_enrichment": [
            {
                "name": "Farm A",
                "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
                "bbox": [[36.8, -1.31], [36.81, -1.3]],
                "center": {"lat": -1.305, "lon": 36.805},
                "area_ha": 12.5,
                "frame_plan": [
                    {
                        "year": 2023,
                        "season": "spring",
                        "start": "2023-03-01",
                        "end": "2023-05-31",
                    }
                ],
                "ndvi_stats": [{"mean": 0.72, "min": 0.5, "max": 0.85, "std": 0.08}],
                "change_detection": {
                    "summary": {"trajectory": "stable", "comparisons": 1},
                },
                "worldcover": {
                    "available": True,
                    "land_cover": {
                        "dominant_class": "Tree cover",
                        "classes": [
                            {"code": 10, "label": "Tree cover", "area_pct": 85.0},
                        ],
                    },
                },
                "wdpa": {"checked": True, "is_protected": False},
                "determination": {
                    "status": "deforestation_free",
                    "confidence": "high",
                    "flags": [],
                },
            },
            {
                "name": "Farm B",
                "coords": [[36.9, -1.4], [36.91, -1.4], [36.91, -1.41], [36.9, -1.41]],
                "bbox": [[36.9, -1.41], [36.91, -1.4]],
                "center": {"lat": -1.405, "lon": 36.905},
                "area_ha": 8.0,
                "frame_plan": [
                    {
                        "year": 2023,
                        "season": "spring",
                        "start": "2023-03-01",
                        "end": "2023-05-31",
                    }
                ],
                "ndvi_stats": [{"mean": 0.35, "min": 0.1, "max": 0.55, "std": 0.15}],
                "change_detection": {
                    "summary": {"trajectory": "declining", "comparisons": 1},
                    "season_changes": [
                        {"loss_ha": 2.5, "loss_pct": 8.0, "label": "spring 2023-2024"}
                    ],
                },
                "worldcover": {
                    "available": True,
                    "land_cover": {
                        "dominant_class": "Cropland",
                        "classes": [
                            {"code": 40, "label": "Cropland", "area_pct": 70.0},
                        ],
                    },
                },
                "wdpa": {"checked": True, "is_protected": True},
                "determination": {
                    "status": "further_review",
                    "confidence": "medium",
                    "flags": ["Vegetation loss 8.0% (2.5 ha) in spring 2023-2024"],
                },
            },
            {
                "name": "Farm C (failed)",
                "error": "enrichment_failed",
            },
        ],
    }


class TestBuildEudrGeoJson:
    """EUDR per-parcel GeoJSON export (#582)."""

    def test_returns_feature_collection(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        assert result["type"] == "FeatureCollection"

    def test_one_feature_per_aoi(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        # 2 successful parcels (Farm C failed — included with error flag)
        assert len(result["features"]) == 3

    def test_feature_has_polygon_geometry(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        feat = result["features"][0]
        assert feat["geometry"]["type"] == "Polygon"

    def test_polygon_ring_is_closed(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        ring = result["features"][0]["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1]

    def test_eudr_properties_present(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        props = result["features"][0]["properties"]
        assert props["parcel_name"] == "Farm A"
        assert props["area_ha"] == 12.5
        assert props["determination_status"] == "deforestation_free"
        assert props["determination_confidence"] == "high"

    def test_worldcover_in_properties(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        props = result["features"][0]["properties"]
        assert props["worldcover_dominant"] == "Tree cover"

    def test_wdpa_in_properties(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        props = result["features"][1]["properties"]
        assert props["wdpa_is_protected"] is True

    def test_ndvi_summary_in_properties(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        props = result["features"][0]["properties"]
        assert props["ndvi_latest_mean"] == 0.72
        assert props["change_trajectory"] == "stable"

    def test_failed_aoi_has_error_flag(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        failed = result["features"][2]
        assert failed["properties"]["error"] == "enrichment_failed"
        assert failed["geometry"] is None

    def test_flags_included(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        props = result["features"][1]["properties"]
        assert len(props["determination_flags"]) == 1

    def test_empty_per_aoi_falls_back_to_toplevel(self):
        """Single-parcel runs have no per_aoi_enrichment; use top-level evidence."""
        manifest = {
            "per_aoi_enrichment": [],
            "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
            "center": {"lat": -1.305, "lon": 36.805},
            "determination": {"status": "deforestation_free", "confidence": "high", "flags": []},
            "worldcover": {
                "available": True,
                "land_cover": {
                    "dominant_class": "Tree cover",
                    "classes": [{"code": 10, "area_pct": 80.0}],
                },
            },
            "wdpa": {"checked": True, "is_protected": False},
            "ndvi_stats": [{"mean": 0.7, "min": 0.5, "max": 0.85, "std": 0.1}],
            "change_detection": {"summary": {"trajectory": "stable", "comparisons": 1}},
        }
        result = _build_eudr_geojson(manifest)
        assert len(result["features"]) == 1
        props = result["features"][0]["properties"]
        assert props["determination_status"] == "deforestation_free"

    def test_no_per_aoi_falls_back_to_toplevel(self):
        manifest = {
            "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
            "determination": {"status": "unknown", "confidence": "low", "flags": []},
        }
        result = _build_eudr_geojson(manifest)
        assert len(result["features"]) == 1

    def test_no_per_aoi_no_toplevel_returns_empty(self):
        result = _build_eudr_geojson({})
        assert result["features"] == []

    def test_serialisable(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        body = json.dumps(result, default=str)
        parsed = json.loads(body)
        assert parsed["type"] == "FeatureCollection"


class TestBuildEudrCsv:
    """EUDR per-parcel CSV export (#582)."""

    def test_returns_string(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        assert isinstance(result, str)

    def test_has_header(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "parcel_name" in header
        assert "determination_status" in header
        assert "area_ha" in header

    def test_one_row_per_aoi(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 3

    def test_determination_values(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["determination_status"] == "deforestation_free"
        assert rows[1]["determination_status"] == "further_review"

    def test_failed_aoi_marked(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[2]["determination_status"] == "error"

    def test_empty_per_aoi_falls_back_to_toplevel(self):
        """Single-parcel: build one CSV row from top-level evidence."""
        manifest = {
            "per_aoi_enrichment": [],
            "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
            "center": {"lat": -1.305, "lon": 36.805},
            "determination": {"status": "deforestation_free", "confidence": "high", "flags": []},
            "worldcover": {
                "available": True,
                "land_cover": {
                    "dominant_class": "Tree cover",
                    "classes": [{"code": 10, "area_pct": 80.0}],
                },
            },
            "wdpa": {"checked": True, "is_protected": False},
            "ndvi_stats": [{"mean": 0.7, "min": 0.5, "max": 0.85, "std": 0.1}],
            "change_detection": {"summary": {"trajectory": "stable", "comparisons": 1}},
        }
        result = _build_eudr_csv(manifest)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["determination_status"] == "deforestation_free"


class TestBuildPdfEudrPerParcel:
    """EUDR per-parcel sections in PDF (#582)."""

    def test_eudr_pdf_with_per_aoi_enrichment(self, eudr_manifest):
        result = _build_pdf(eudr_manifest, "run-eudr-582")
        assert isinstance(result, bytes)
        assert result.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Audit-grade EUDR PDF report (#587)
# ---------------------------------------------------------------------------


class TestBuildEudrAuditPdf:
    """Audit-grade EUDR evidence PDF report (#587)."""

    def test_returns_valid_pdf(self, eudr_manifest):
        result = build_eudr_audit_pdf(eudr_manifest, "run-audit-587")
        assert isinstance(result, bytes)
        assert result.startswith(b"%PDF")

    def test_larger_than_basic_pdf(self, eudr_manifest):
        """Audit PDF should be bigger than the basic one (more sections)."""
        basic = _build_pdf(eudr_manifest, "run-basic")
        audit = build_eudr_audit_pdf(eudr_manifest, "run-audit")
        assert len(audit) > len(basic)

    def test_handles_empty_manifest(self):
        result = build_eudr_audit_pdf({}, "run-empty")
        assert result.startswith(b"%PDF")

    def test_handles_no_per_aoi(self, enrichment_manifest):
        """Non-EUDR manifest without per_aoi_enrichment should still work."""
        result = build_eudr_audit_pdf(enrichment_manifest, "run-no-aoi")
        assert result.startswith(b"%PDF")

    def test_filters_to_post_2020_frames(self, eudr_manifest):
        """Frames before 2021 should be excluded from the EUDR timeseries."""
        manifest = dict(eudr_manifest)
        manifest["frame_plan"] = [
            {"year": 2019, "season": "spring", "start": "2019-03-01", "end": "2019-05-31"},
            {"year": 2020, "season": "spring", "start": "2020-03-01", "end": "2020-05-31"},
            {"year": 2021, "season": "spring", "start": "2021-03-01", "end": "2021-05-31"},
            {"year": 2023, "season": "spring", "start": "2023-03-01", "end": "2023-05-31"},
        ]
        manifest["ndvi_stats"] = [
            {"mean": 0.5},
            {"mean": 0.6},
            {"mean": 0.55},
            {"mean": 0.58},
        ]
        result = build_eudr_audit_pdf(manifest, "run-filter")
        assert result.startswith(b"%PDF")

    def test_with_operator_context(self, eudr_manifest):
        """Operator metadata should be accepted."""
        manifest = dict(eudr_manifest)
        manifest["operator_name"] = "Acme Trading GmbH"
        manifest["commodity"] = "cocoa"
        result = build_eudr_audit_pdf(manifest, "run-operator")
        assert result.startswith(b"%PDF")

    def test_mixed_determinations(self, eudr_manifest):
        """Mix of deforestation_free and further_review parcels."""
        result = build_eudr_audit_pdf(eudr_manifest, "run-mixed")
        assert result.startswith(b"%PDF")
