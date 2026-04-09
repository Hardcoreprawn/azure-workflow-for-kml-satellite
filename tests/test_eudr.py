"""Tests for EUDR features — date filtering, coordinate conversion, assessment, PDF export."""

from __future__ import annotations

import json

import pytest

from treesight.constants import EUDR_CUTOFF_DATE
from treesight.pipeline.enrichment.frames import build_frame_plan
from treesight.pipeline.eudr import (
    WORLDCOVER_CLASSES,
    _point_buffer,
    _sample_worldcover_cog,
    _xml_escape,
    check_wdpa_overlap,
    coords_to_kml,
    query_worldcover,
)

# ---------------------------------------------------------------------------
# §1 — EUDR date filtering in frame plan
# ---------------------------------------------------------------------------

LONDON_COORDS = [[-0.12, 51.51], [-0.11, 51.51], [-0.11, 51.50], [-0.12, 51.50], [-0.12, 51.51]]
KENYA_COORDS = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31], [36.8, -1.3]]


class TestBuildFramePlanDateFiltering:
    """Test date_start / date_end filtering on build_frame_plan."""

    def test_no_filter_returns_all_frames(self):
        frames = build_frame_plan(KENYA_COORDS)
        # Should include frames from 2018 to 2026, 4 seasons each = 36 frames
        assert len(frames) >= 36

    def test_date_start_filters_early_frames(self):
        frames = build_frame_plan(KENYA_COORDS, date_start="2021-01-01")
        # All frames should have end dates >= 2021-01-01
        for f in frames:
            assert f["end"] >= "2021-01-01", f"Frame {f} should be filtered out"

    def test_date_end_filters_late_frames(self):
        frames = build_frame_plan(KENYA_COORDS, date_end="2023-12-31")
        for f in frames:
            assert f["start"] <= "2023-12-31", f"Frame {f} should be filtered out"

    def test_date_range_narrows_frames(self):
        all_frames = build_frame_plan(KENYA_COORDS)
        filtered = build_frame_plan(KENYA_COORDS, date_start="2022-01-01", date_end="2023-12-31")
        assert len(filtered) < len(all_frames)
        for f in filtered:
            assert f["end"] >= "2022-01-01"
            assert f["start"] <= "2023-12-31"

    def test_eudr_cutoff_filters_pre_2021(self):
        """EUDR mode: only post-2020 frames."""
        frames = build_frame_plan(KENYA_COORDS, date_start="2021-01-01")
        years = {f["year"] for f in frames}
        assert 2018 not in years
        assert 2019 not in years
        assert 2020 not in years
        assert 2021 in years

    def test_empty_result_when_range_impossible(self):
        frames = build_frame_plan(KENYA_COORDS, date_start="2030-01-01")
        assert frames == []


# ---------------------------------------------------------------------------
# §2 — Coordinate-to-KML converter
# ---------------------------------------------------------------------------


class TestCoordsToKml:
    """Test KML generation from coordinate plots."""

    def test_point_plot_generates_kml(self):
        plots = [{"name": "Test Point", "lon": 2.35, "lat": 48.86}]
        kml = coords_to_kml(plots, doc_name="Test Doc")
        assert '<?xml version="1.0"' in kml
        assert "<kml" in kml
        assert "Test Point" in kml
        assert "Test Doc" in kml
        assert "<Polygon>" in kml
        assert "<coordinates>" in kml

    def test_polygon_plot_generates_kml(self):
        plots = [
            {
                "name": "Field A",
                "coordinates": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
            }
        ]
        kml = coords_to_kml(plots)
        assert "Field A" in kml
        assert "36.8" in kml

    def test_multiple_plots(self):
        plots = [
            {"name": "Plot 1", "lon": 2.35, "lat": 48.86},
            {"name": "Plot 2", "lon": 2.36, "lat": 48.87},
            {"name": "Block 3", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 1]]},
        ]
        kml = coords_to_kml(plots)
        assert kml.count("<Placemark>") == 3
        assert "Plot 1" in kml
        assert "Plot 2" in kml
        assert "Block 3" in kml

    def test_custom_buffer_radius(self):
        plots = [{"name": "Big Buffer", "lon": 0.0, "lat": 0.0, "radius_m": 500}]
        kml = coords_to_kml(plots, buffer_m=100)
        assert "500" in kml  # radius_m should override buffer_m
        assert "Big Buffer" in kml

    def test_xml_special_chars_escaped(self):
        plots = [{"name": "Test <>&\"'", "lon": 0.0, "lat": 0.0}]
        kml = coords_to_kml(plots)
        assert "&lt;" in kml
        assert "&amp;" in kml
        assert "&gt;" in kml

    def test_empty_plots_returns_valid_kml(self):
        kml = coords_to_kml([])
        assert "<kml" in kml
        assert "</kml>" in kml
        assert "<Placemark>" not in kml


class TestPointBuffer:
    """Test the circular buffer geometry generation."""

    def test_returns_closed_ring(self):
        ring = _point_buffer(0.0, 0.0, 100.0)
        assert len(ring) == 33  # 32 + 1 for closure
        # First and last should be (approximately) the same
        assert abs(ring[0][0] - ring[-1][0]) < 1e-10
        assert abs(ring[0][1] - ring[-1][1]) < 1e-10

    def test_radius_scales_ring(self):
        small = _point_buffer(0.0, 45.0, 100.0)
        large = _point_buffer(0.0, 45.0, 1000.0)
        # Large buffer should span wider
        small_span = max(p[0] for p in small) - min(p[0] for p in small)
        large_span = max(p[0] for p in large) - min(p[0] for p in large)
        assert large_span > small_span * 5


class TestXmlEscape:
    """Test XML escaping utility."""

    def test_escapes_ampersand(self):
        assert _xml_escape("a & b") == "a &amp; b"

    def test_escapes_angle_brackets(self):
        assert _xml_escape("<script>") == "&lt;script&gt;"

    def test_escapes_quotes(self):
        assert _xml_escape('say "hello"') == "say &quot;hello&quot;"

    def test_clean_string_unchanged(self):
        assert _xml_escape("normal text") == "normal text"


# ---------------------------------------------------------------------------
# §3 — WDPA check (unit tests with no API call)
# ---------------------------------------------------------------------------


class TestWdpaCheck:
    """Test WDPA check behaviour when no API token is set."""

    def test_no_token_returns_unchecked(self, monkeypatch):
        monkeypatch.delenv("WDPA_API_TOKEN", raising=False)
        result = check_wdpa_overlap(36.8, -1.3)
        assert result["checked"] is False
        assert result["reason"] == "no_api_token"
        assert result["protected_areas"] == []


class TestWdpaAreaParsing:
    """Verify safe extraction of nested WDPA attributes (#457)."""

    def _parse_area(self, area: dict) -> dict:
        """Call the internal area-parsing logic."""
        from treesight.pipeline.eudr import _parse_wdpa_area

        return _parse_wdpa_area(area)

    def test_extracts_country_from_populated_list(self):
        area = {
            "id": 1,
            "attributes": {
                "name": "Park",
                "countries": [{"name": "Kenya"}],
            },
        }
        result = self._parse_area(area)
        assert result["country"] == "Kenya"

    def test_empty_countries_list(self):
        area = {"id": 1, "attributes": {"name": "Park", "countries": []}}
        result = self._parse_area(area)
        assert result["country"] == ""

    def test_missing_countries_key(self):
        area = {"id": 1, "attributes": {"name": "Park"}}
        result = self._parse_area(area)
        assert result["country"] == ""

    def test_missing_designation_nested(self):
        area = {"id": 1, "attributes": {"name": "Park"}}
        result = self._parse_area(area)
        assert result["designation"] == ""

    def test_designation_name_extracted(self):
        area = {
            "id": 1,
            "attributes": {
                "name": "Park",
                "designation": {"name": "National Park"},
            },
        }
        result = self._parse_area(area)
        assert result["designation"] == "National Park"


# ---------------------------------------------------------------------------
# §4 — WorldCover classes
# ---------------------------------------------------------------------------


class TestWorldCoverClasses:
    """Test the WorldCover class lookup table."""

    def test_tree_cover_class_exists(self):
        assert WORLDCOVER_CLASSES[10] == "Tree cover"

    def test_cropland_class_exists(self):
        assert WORLDCOVER_CLASSES[40] == "Cropland"

    def test_all_classes_are_strings(self):
        for code, label in WORLDCOVER_CLASSES.items():
            assert isinstance(code, int)
            assert isinstance(label, str)
            assert len(label) > 0


# ---------------------------------------------------------------------------
# §4b — WorldCover raster sampling (stub mode)
# ---------------------------------------------------------------------------


class TestWorldCoverQuery:
    """Test query_worldcover with stub_mode=True (no network)."""

    def test_stub_returns_available(self):
        result = query_worldcover([-1.5, 51.4, -1.4, 51.5], stub_mode=True)
        assert result["available"] is True
        assert result["collection"] == "esa-worldcover"
        assert "land_cover" in result

    def test_stub_has_land_cover_breakdown(self):
        result = query_worldcover([-1.5, 51.4, -1.4, 51.5], stub_mode=True)
        lc = result["land_cover"]
        assert lc["total_pixels"] > 0
        assert len(lc["classes"]) > 0
        assert lc["dominant_class"] == "Tree cover"

    def test_stub_classes_have_required_fields(self):
        result = query_worldcover([-1.5, 51.4, -1.4, 51.5], stub_mode=True)
        for cls in result["land_cover"]["classes"]:
            assert "code" in cls
            assert "label" in cls
            assert "pixel_count" in cls
            assert "area_pct" in cls
            assert cls["code"] in WORLDCOVER_CLASSES

    def test_stub_area_pct_sums_to_100(self):
        result = query_worldcover([-1.5, 51.4, -1.4, 51.5], stub_mode=True)
        total_pct = sum(c["area_pct"] for c in result["land_cover"]["classes"])
        assert total_pct == pytest.approx(100.0, abs=0.1)

    def test_stub_center_coordinates(self):
        result = query_worldcover([10.0, 50.0, 11.0, 51.0], stub_mode=True)
        assert result["center"]["lon"] == pytest.approx(10.5)
        assert result["center"]["lat"] == pytest.approx(50.5)

    def test_stub_bbox_preserved(self):
        bbox = [2.0, 48.0, 3.0, 49.0]
        result = query_worldcover(bbox, stub_mode=True)
        assert result["bbox"] == bbox


# ---------------------------------------------------------------------------
# §4c — WorldCover COG sampling (in-memory raster, no network)
# ---------------------------------------------------------------------------


class TestSampleWorldcoverCog:
    """Test _sample_worldcover_cog with a synthetic in-memory raster."""

    @staticmethod
    def _make_cog(classes: dict[int, int], width: int = 10, height: int = 10) -> bytes:
        """Create a minimal single-band GeoTIFF in memory.

        *classes* maps WorldCover code → pixel count.  Remaining pixels are
        filled with nodata (0).
        """
        import numpy as np
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds

        data = np.zeros((height, width), dtype=np.uint8)
        offset = 0
        for code, count in classes.items():
            flat = data.ravel()
            flat[offset : offset + count] = code
            offset += count

        transform = from_bounds(10.0, 50.0, 11.0, 51.0, width, height)
        memfile = MemoryFile()
        with memfile.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)
        return memfile.read()

    def test_basic_class_breakdown(self, monkeypatch, tmp_path):
        """Dominant class and percentages are correct for a known raster."""
        import planetary_computer

        raster_bytes = self._make_cog({10: 60, 40: 30, 50: 10})
        raster_path = tmp_path / "wc.tif"
        raster_path.write_bytes(raster_bytes)

        monkeypatch.setattr(planetary_computer, "sign_url", lambda href: href)

        result = _sample_worldcover_cog(str(raster_path), [10.0, 50.0, 11.0, 51.0])

        assert result["dominant_class"] == "Tree cover"
        assert result["total_pixels"] == 100
        codes = {c["code"]: c for c in result["classes"]}
        assert codes[10]["area_pct"] == pytest.approx(60.0, abs=0.1)
        assert codes[40]["area_pct"] == pytest.approx(30.0, abs=0.1)
        assert codes[50]["area_pct"] == pytest.approx(10.0, abs=0.1)

    def test_nodata_excluded_from_percentage(self, monkeypatch, tmp_path):
        """Nodata pixels (code 0) are excluded so percentages sum to 100%."""
        import planetary_computer

        # 40 tree, 20 crop, 40 nodata → valid_total = 60
        raster_bytes = self._make_cog({10: 40, 40: 20})
        raster_path = tmp_path / "wc_nodata.tif"
        raster_path.write_bytes(raster_bytes)

        monkeypatch.setattr(planetary_computer, "sign_url", lambda href: href)

        result = _sample_worldcover_cog(str(raster_path), [10.0, 50.0, 11.0, 51.0])

        total_pct = sum(c["area_pct"] for c in result["classes"])
        assert total_pct == pytest.approx(100.0, abs=0.1)
        codes = {c["code"]: c for c in result["classes"]}
        assert codes[10]["area_pct"] == pytest.approx(66.67, abs=0.1)
        assert codes[40]["area_pct"] == pytest.approx(33.33, abs=0.1)

    def test_all_nodata_returns_empty(self, monkeypatch, tmp_path):
        """A raster with only nodata returns empty classes."""
        import planetary_computer

        raster_bytes = self._make_cog({})  # all zeros = nodata
        raster_path = tmp_path / "wc_empty.tif"
        raster_path.write_bytes(raster_bytes)

        monkeypatch.setattr(planetary_computer, "sign_url", lambda href: href)

        result = _sample_worldcover_cog(str(raster_path), [10.0, 50.0, 11.0, 51.0])

        assert result["classes"] == []
        assert result["dominant_class"] is None


# ---------------------------------------------------------------------------


class TestEudrConstant:
    """Test the EUDR cutoff date constant."""

    def test_cutoff_date_is_correct(self):
        assert EUDR_CUTOFF_DATE == "2020-12-31"


# ---------------------------------------------------------------------------
# §6 — EUDR assessment endpoint (blueprints.analysis)
# ---------------------------------------------------------------------------


class TestEudrAssessmentEndpoint:
    """Test the EUDR assessment endpoint request/response structure."""

    def _make_request(self, body: dict, method: str = "POST"):
        """Create a mock Azure Functions HttpRequest."""
        import azure.functions as func

        body_bytes = json.dumps(body).encode("utf-8")
        return func.HttpRequest(
            method=method,
            url="/api/eudr-assessment",
            headers={"Content-Type": "application/json"},
            body=body_bytes,
        )

    def test_missing_context_returns_400(self):
        from blueprints.analysis import eudr_assessment

        req = self._make_request({})
        resp = eudr_assessment(req)
        assert resp.status_code == 400

    def test_missing_ndvi_returns_400(self):
        from blueprints.analysis import eudr_assessment

        req = self._make_request({"context": {"aoi_name": "Test"}})
        resp = eudr_assessment(req)
        assert resp.status_code == 400

    def test_no_post_2020_data_returns_400(self):
        from blueprints.analysis import eudr_assessment

        req = self._make_request(
            {
                "context": {
                    "ndvi_timeseries": [
                        {"date": "2019-06-01", "mean": 0.5, "season": "summer", "year": 2019},
                        {"date": "2020-06-01", "mean": 0.52, "season": "summer", "year": 2020},
                    ],
                }
            }
        )
        resp = eudr_assessment(req)
        assert resp.status_code == 400

    def test_options_returns_204(self):
        import azure.functions as func

        from blueprints.analysis import eudr_assessment

        req = func.HttpRequest(
            method="OPTIONS",
            url="/api/eudr-assessment",
            headers={},
            body=b"",
        )
        resp = eudr_assessment(req)
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# §7 — Convert-coordinates endpoint
# ---------------------------------------------------------------------------


class TestConvertCoordinatesEndpoint:
    """Test the coordinate conversion endpoint."""

    def _make_request(self, body: dict, method: str = "POST"):
        import azure.functions as func

        body_bytes = json.dumps(body).encode("utf-8")
        return func.HttpRequest(
            method=method,
            url="/api/convert-coordinates",
            headers={"Content-Type": "application/json"},
            body=body_bytes,
        )

    def test_point_conversion_returns_kml(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request(
            {
                "doc_name": "Test",
                "plots": [{"name": "P1", "lon": 2.35, "lat": 48.86}],
            }
        )
        resp = convert_coordinates(req)
        assert resp.status_code == 200
        assert resp.mimetype == "application/vnd.google-earth.kml+xml"
        body = resp.get_body().decode("utf-8")
        assert "<kml" in body
        assert "P1" in body

    def test_polygon_conversion_returns_kml(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request(
            {
                "plots": [
                    {
                        "name": "Field",
                        "coordinates": [[0, 0], [1, 0], [1, 1], [0, 1]],
                    }
                ],
            }
        )
        resp = convert_coordinates(req)
        assert resp.status_code == 200
        body = resp.get_body().decode("utf-8")
        assert "Field" in body

    def test_missing_plots_returns_400(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request({"doc_name": "Test"})
        resp = convert_coordinates(req)
        assert resp.status_code == 400

    def test_empty_plots_returns_400(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request({"plots": []})
        resp = convert_coordinates(req)
        assert resp.status_code == 400

    def test_invalid_coords_returns_400(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request(
            {
                "plots": [{"name": "Bad", "lon": 999, "lat": 999}],
            }
        )
        resp = convert_coordinates(req)
        assert resp.status_code == 400

    def test_too_few_polygon_points_returns_400(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request(
            {
                "plots": [{"name": "Line", "coordinates": [[0, 0], [1, 1]]}],
            }
        )
        resp = convert_coordinates(req)
        assert resp.status_code == 400

    def test_plot_without_coords_returns_400(self):
        from blueprints.eudr import convert_coordinates

        req = self._make_request(
            {
                "plots": [{"name": "Nothing"}],
            }
        )
        resp = convert_coordinates(req)
        assert resp.status_code == 400

    def test_options_returns_204(self):
        import azure.functions as func

        from blueprints.eudr import convert_coordinates

        req = func.HttpRequest(
            method="OPTIONS",
            url="/api/convert-coordinates",
            headers={},
            body=b"",
        )
        resp = convert_coordinates(req)
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# §8 — PDF export
# ---------------------------------------------------------------------------


class TestPdfExport:
    """Test PDF generation from enrichment manifest."""

    @pytest.fixture()
    def manifest(self):
        return {
            "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]],
            "center": {"lat": -1.305, "lon": 36.805},
            "enriched_at": "2025-01-15T10:30:00+00:00",
            "enrichment_duration_seconds": 12.3,
            "eudr_mode": True,
            "eudr_date_start": "2021-01-01",
            "frame_plan": [
                {
                    "year": 2021,
                    "season": "summer",
                    "start": "2021-06-01",
                    "end": "2021-08-31",
                    "collection": "sentinel-2-l2a",
                    "is_naip": False,
                    "label": "Summer 2021",
                },
                {
                    "year": 2022,
                    "season": "summer",
                    "start": "2022-06-01",
                    "end": "2022-08-31",
                    "collection": "sentinel-2-l2a",
                    "is_naip": False,
                    "label": "Summer 2022",
                },
            ],
            "ndvi_stats": [
                {"mean": 0.55, "min": 0.2, "max": 0.8, "std": 0.1},
                {"mean": 0.58, "min": 0.25, "max": 0.82, "std": 0.09},
            ],
            "change_detection": {
                "summary": {"trajectory": "Stable", "comparisons": 1},
            },
            "worldcover": {
                "available": True,
                "item_id": "ESA_WC_2021",
                "collection": "esa-worldcover",
                "center": {"lon": -0.115, "lat": 51.505},
                "bbox": [-0.12, 51.50, -0.11, 51.51],
                "land_cover": {
                    "total_pixels": 10000,
                    "classes": [
                        {"code": 50, "label": "Built-up", "pixel_count": 7000, "area_pct": 70.0},
                        {"code": 10, "label": "Tree cover", "pixel_count": 2000, "area_pct": 20.0},
                        {"code": 30, "label": "Grassland", "pixel_count": 1000, "area_pct": 10.0},
                    ],
                    "dominant_class": "Built-up",
                },
            },
            "wdpa": {"checked": True, "is_protected": False, "protected_areas": []},
        }

    def test_pdf_generation(self, manifest):
        from blueprints.export import _build_pdf

        pdf_bytes = _build_pdf(manifest, "test-instance-123")
        assert isinstance(pdf_bytes, (bytes, bytearray))
        assert len(pdf_bytes) > 100
        # PDF magic bytes
        assert pdf_bytes[:4] == b"%PDF"

    def test_pdf_without_eudr_mode(self, manifest):
        from blueprints.export import _build_pdf

        manifest["eudr_mode"] = False
        pdf_bytes = _build_pdf(manifest, "test-456")
        assert pdf_bytes[:4] == b"%PDF"

    def test_pdf_with_empty_manifest(self):
        from blueprints.export import _build_pdf

        pdf_bytes = _build_pdf({}, "empty")
        assert pdf_bytes[:4] == b"%PDF"

    def test_pdf_format_in_allowed_formats(self):
        from blueprints.export import _ALLOWED_FORMATS

        assert "pdf" in _ALLOWED_FORMATS
