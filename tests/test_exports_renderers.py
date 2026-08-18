"""Unit tests for domain-level export renderers in ``treesight/exports/``.

Each renderer is exercised in isolation, without HTTP types or Azure Functions.
These complement the endpoint-level tests in ``test_export.py``.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from treesight.exports.csv import _as_dict, _build_bulk_csv, _build_csv, _build_eudr_csv
from treesight.exports.eudr import _build_eudr_dds, _plot_geolocation
from treesight.exports.frame_row import FrameRow
from treesight.exports.geojson import _build_eudr_geojson, _build_geojson, _toplevel_as_single_aoi

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_manifest():
    """Minimal enrichment manifest with one frame."""
    return {
        "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
        "center": {"lat": -1.305, "lon": 36.805},
        "frame_plan": [
            {
                "label": "Spring 2023",
                "year": 2023,
                "season": "spring",
                "start": "2023-03-01",
                "end": "2023-05-31",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "provenance": {
                    "display_search_id": "sid-1",
                    "ndvi_scene_id": "S2A_001",
                    "resolution_m": 10.0,
                    "cloud_cover_pct": 5.0,
                    "acquired_at": "2023-03-15T09:00:00Z",
                    "artifact_path": "enrichment/run-1/ndvi/spring.tif",
                },
            },
            {
                "label": "Summer 2023",
                "year": 2023,
                "season": "summer",
                "start": "2023-06-01",
                "end": "2023-08-31",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "provenance": {},
            },
        ],
        "ndvi_stats": [
            {"mean": 0.62, "min": 0.40, "max": 0.78, "std": 0.08, "scene_id": "S2A_001"},
            {"mean": 0.58, "min": 0.35, "max": 0.72, "std": 0.10, "scene_id": "S2A_002"},
        ],
        "change_detection": {
            "summary": {"trajectory": "stable", "comparisons": 1},
            "season_changes": [],
        },
        "enriched_at": "2023-09-01T12:00:00Z",
    }


@pytest.fixture()
def eudr_manifest():
    """Manifest with two EUDR AOIs and commodity metadata."""
    return {
        "commodity": "timber",
        "operator_name": "Test Operator",
        "country_of_production": "BR",
        "per_aoi_enrichment": [
            {
                "name": "Parcel A",
                "area_ha": 10.5,
                "center": {"lat": -1.3, "lon": 36.8},
                "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
                "determination": {"status": "no_signal_detected", "confidence": "high", "flags": []},
                "worldcover": {
                    "available": True,
                    "land_cover": {
                        "dominant_class": "Tree cover",
                        "classes": [{"code": 10, "label": "Tree cover", "area_pct": 85.0}],
                    },
                },
                "wdpa": {"checked": True, "is_protected": False},
                "ndvi_stats": [{"mean": 0.65}, {"mean": 0.70}],
                "change_detection": {"summary": {"trajectory": "stable", "comparisons": 1}},
            },
            {
                "name": "Parcel B",
                "error": "enrichment failed",
            },
        ],
    }


# ---------------------------------------------------------------------------
# FrameRow
# ---------------------------------------------------------------------------


class TestFrameRow:
    def test_from_dict_basic(self):
        frame = {
            "label": "Spring 2023",
            "year": 2023,
            "season": "spring",
            "start": "2023-03-01",
            "end": "2023-05-31",
            "collection": "sentinel-2-l2a",
            "is_naip": False,
        }
        row = FrameRow.from_dict(0, frame)
        assert row.frame_index == 0
        assert row.label == "Spring 2023"
        assert row.year == 2023
        assert row.season == "spring"
        assert row.start == "2023-03-01"
        assert row.end == "2023-05-31"
        assert row.collection == "sentinel-2-l2a"
        assert row.is_naip is False
        assert row.provenance == {}

    def test_from_dict_with_provenance(self):
        frame = {
            "label": "S",
            "year": 2023,
            "season": "spring",
            "start": "2023-01-01",
            "end": "2023-03-31",
            "collection": "sentinel-2-l2a",
            "is_naip": False,
            "provenance": {"display_search_id": "sid-1"},
        }
        row = FrameRow.from_dict(2, frame)
        assert row.frame_index == 2
        assert row.provenance == {"display_search_id": "sid-1"}

    def test_from_dict_missing_fields_use_defaults(self):
        row = FrameRow.from_dict(0, {})
        assert row.label == ""
        assert row.year == ""
        assert row.season == ""
        assert row.is_naip is False

    def test_frozen(self):
        row = FrameRow.from_dict(0, {"year": 2023})
        with pytest.raises(AttributeError):
            row.label = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GeoJSON renderer
# ---------------------------------------------------------------------------


class TestBuildGeoJSON:
    def test_returns_feature_collection(self, minimal_manifest):
        result = _build_geojson(minimal_manifest)
        assert result["type"] == "FeatureCollection"
        assert isinstance(result["features"], list)

    def test_one_feature_per_frame_plus_summary(self, minimal_manifest):
        result = _build_geojson(minimal_manifest)
        # 2 frames + 1 summary
        assert len(result["features"]) == 3

    def test_frame_properties_from_frame_row(self, minimal_manifest):
        result = _build_geojson(minimal_manifest)
        props = result["features"][0]["properties"]
        assert props["label"] == "Spring 2023"
        assert props["year"] == 2023
        assert props["season"] == "spring"
        assert props["collection"] == "sentinel-2-l2a"
        assert props["is_naip"] is False

    def test_ndvi_props_on_frame(self, minimal_manifest):
        result = _build_geojson(minimal_manifest)
        props = result["features"][0]["properties"]
        assert props["ndvi_mean"] == pytest.approx(0.62)

    def test_summary_feature_is_point(self, minimal_manifest):
        result = _build_geojson(minimal_manifest)
        summary = result["features"][-1]
        assert summary["geometry"]["type"] == "Point"
        assert summary["properties"]["type"] == "summary"

    def test_empty_manifest_returns_empty_collection(self):
        result = _build_geojson({})
        assert result["features"] == []

    def test_output_is_json_serialisable(self, minimal_manifest):
        result = _build_geojson(minimal_manifest)
        body = json.dumps(result, default=str)
        parsed = json.loads(body)
        assert parsed["type"] == "FeatureCollection"


class TestTopLevelAsSingleAoi:
    def test_empty_manifest_returns_empty(self):
        assert _toplevel_as_single_aoi({}) == []

    def test_manifest_with_coords_returns_single_entry(self):
        manifest = {
            "coords": [[36.8, -1.3], [36.81, -1.3]],
            "feature_name": "Test",
            "area_ha": 5.0,
        }
        result = _toplevel_as_single_aoi(manifest)
        assert len(result) == 1
        assert result[0]["name"] == "Test"
        assert result[0]["area_ha"] == 5.0


class TestBuildEudrGeoJSON:
    def test_returns_feature_collection(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        assert result["type"] == "FeatureCollection"

    def test_one_feature_per_aoi(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        assert len(result["features"]) == 2

    def test_error_aoi_has_null_geometry(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        error_feature = result["features"][1]
        assert error_feature["geometry"] is None
        assert error_feature["properties"]["error"] == "enrichment failed"

    def test_good_aoi_has_determination_props(self, eudr_manifest):
        result = _build_eudr_geojson(eudr_manifest)
        props = result["features"][0]["properties"]
        assert "determination_status" in props
        assert props["worldcover_tree_pct"] == pytest.approx(85.0)
        assert props["ndvi_latest_mean"] == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# CSV renderer
# ---------------------------------------------------------------------------


class TestAsDict:
    def test_dict_passes_through(self):
        d = {"a": 1}
        assert _as_dict(d) is d

    def test_non_dict_returns_empty(self):
        assert _as_dict(None) == {}
        assert _as_dict("string") == {}
        assert _as_dict(42) == {}


class TestBuildCSV:
    def test_returns_string(self, minimal_manifest):
        result = _build_csv(minimal_manifest)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_has_header_row(self, minimal_manifest):
        result = _build_csv(minimal_manifest)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "frame_index" in header
        assert "ndvi_mean" in header

    def test_one_row_per_frame(self, minimal_manifest):
        result = _build_csv(minimal_manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert len(rows) == 2

    def test_provenance_fields_flattened(self, minimal_manifest):
        result = _build_csv(minimal_manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert rows[0]["display_search_id"] == "sid-1"
        assert rows[0]["ndvi_scene_id"] == "S2A_001"
        assert rows[0]["artifact_path"] == "enrichment/run-1/ndvi/spring.tif"

    def test_ndvi_values_present(self, minimal_manifest):
        result = _build_csv(minimal_manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert float(rows[0]["ndvi_mean"]) == pytest.approx(0.62)

    def test_empty_manifest_returns_header_only(self):
        result = _build_csv({})
        rows = list(csv.DictReader(io.StringIO(result)))
        assert rows == []


class TestBuildBulkCSV:
    def test_falls_back_to_build_csv_when_no_per_aoi(self, minimal_manifest):
        # Without per_aoi_metrics, should fall back to _build_csv output
        bulk = _build_bulk_csv(minimal_manifest)
        regular = _build_csv(minimal_manifest)
        assert bulk == regular

    def test_per_aoi_metrics_produces_one_row_per_aoi(self):
        manifest = {
            "per_aoi_metrics": [
                {
                    "feature_name": "AOI A",
                    "feature_index": 0,
                    "geometry": {"area_ha": 10.0, "perimeter_km": 1.2, "centroid_lon": 36.8, "centroid_lat": -1.3},
                    "vegetation": {
                        "latest_detail": {"mean": 0.65},
                        "health_class": "good",
                        "trend_direction": "stable",
                    },
                    "change": {"total_loss_ha": 0.0, "total_gain_ha": 0.5, "net_change_ha": 0.5, "trajectory": "gain"},
                    "weather": {"temp_mean_c": 22.0, "precip_total_mm": 800},
                    "ndvi_data_scope": "full",
                }
            ]
        }
        result = _build_bulk_csv(manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert len(rows) == 1
        assert rows[0]["feature_name"] == "AOI A"
        assert rows[0]["trajectory"] == "gain"


class TestBuildEudrCSV:
    def test_returns_string_with_header(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        assert isinstance(result, str)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "parcel_name" in header
        assert "determination_status" in header

    def test_one_row_per_aoi(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert len(rows) == 2

    def test_error_aoi_has_error_status(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert rows[1]["determination_status"] == "error"

    def test_good_aoi_has_correct_values(self, eudr_manifest):
        result = _build_eudr_csv(eudr_manifest)
        rows = list(csv.DictReader(io.StringIO(result)))
        row = rows[0]
        assert row["parcel_name"] == "Parcel A"
        assert "determination_status" in row
        assert row["worldcover_tree_pct"] == "85.0"

    def test_reviewer_data_included_when_run_record_provided(self, eudr_manifest):
        run_record = {
            "parcel_reviews": {
                "0": {"note": "Looks clean", "reviewed_by": "user@example.com", "reviewed_at": "2024-01-01T00:00:00Z"}
            }
        }
        result = _build_eudr_csv(eudr_manifest, run_record=run_record)
        rows = list(csv.DictReader(io.StringIO(result)))
        assert rows[0]["reviewer_note"] == "Looks clean"
        assert rows[0]["reviewed_by"] == "user@example.com"


# ---------------------------------------------------------------------------
# EUDR DDS renderer
# ---------------------------------------------------------------------------


class TestBuildEudrDds:
    def test_returns_dict_with_annex_ii_key(self, eudr_manifest):
        result = _build_eudr_dds(eudr_manifest)
        assert "dds_annex_ii" in result
        assert "_disclaimer" in result

    def test_annex_ii_has_six_sections(self, eudr_manifest):
        annex = _build_eudr_dds(eudr_manifest)["dds_annex_ii"]
        assert "1_operator" in annex
        assert "2_product" in annex
        assert "3_production" in annex
        assert "4_reference_to_existing_statement" in annex
        assert "5_declaration" in annex
        assert "6_signature" in annex

    def test_operator_block(self, eudr_manifest):
        annex = _build_eudr_dds(eudr_manifest)["dds_annex_ii"]
        assert annex["1_operator"]["name"] == "Test Operator"

    def test_product_block_recognises_timber(self, eudr_manifest):
        annex = _build_eudr_dds(eudr_manifest)["dds_annex_ii"]
        assert annex["2_product"]["commodity"] == "timber"
        assert annex["2_product"]["commodity_recognized"] is True

    def test_production_block_has_plot_per_aoi(self, eudr_manifest):
        annex = _build_eudr_dds(eudr_manifest)["dds_annex_ii"]
        plots = annex["3_production"]["plots"]
        assert len(plots) == 2

    def test_signature_block_is_blank(self, eudr_manifest):
        annex = _build_eudr_dds(eudr_manifest)["dds_annex_ii"]
        sig = annex["6_signature"]
        assert sig["date"] == ""
        assert sig["signature"] == ""


class TestPlotGeolocation:
    def test_cattle_always_returns_point(self):
        aoi = {"center": {"lat": -1.3, "lon": 36.8}, "area_ha": 100.0}
        result = _plot_geolocation(aoi, is_cattle=True)
        assert result["geolocation_type"] == "point"

    def test_small_area_returns_point(self):
        aoi = {"center": {"lat": -1.3, "lon": 36.8}, "area_ha": 2.0}
        result = _plot_geolocation(aoi, is_cattle=False)
        assert result["geolocation_type"] == "point"

    def test_large_area_returns_polygon(self):
        aoi = {
            "center": {"lat": -1.3, "lon": 36.8},
            "area_ha": 10.0,
            "coords": [[36.8, -1.3], [36.81, -1.3]],
        }
        result = _plot_geolocation(aoi, is_cattle=False)
        assert result["geolocation_type"] == "polygon"

    def test_source_geometry_type_point_overrides_area(self):
        aoi = {
            "center": {"lat": -1.3, "lon": 36.8},
            "area_ha": 100.0,
            "source_geometry_type": "Point",
        }
        result = _plot_geolocation(aoi, is_cattle=False)
        assert result["geolocation_type"] == "point"

    def test_source_geometry_type_polygon_overrides_area(self):
        aoi = {
            "center": {"lat": -1.3, "lon": 36.8},
            "area_ha": 1.0,
            "source_geometry_type": "Polygon",
            "coords": [[36.8, -1.3]],
        }
        result = _plot_geolocation(aoi, is_cattle=False)
        assert result["geolocation_type"] == "polygon"
