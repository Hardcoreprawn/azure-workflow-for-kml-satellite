"""Tests for geometry computation — prepare_aoi, bbox, area, centroid (§3.1)."""

from __future__ import annotations

import pytest

from treesight.geo import (
    _buffer_bbox,
    _centroid,
    _compute_bbox,
    _geodesic_area_and_perimeter,
    prepare_aoi,
)
from treesight.models.aoi import AOI
from treesight.models.feature import Feature


class TestComputeBbox:
    def test_simple_rectangle(self):
        coords = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31]]
        bbox = _compute_bbox(coords)
        assert bbox[0] == pytest.approx(36.8)  # min_lon
        assert bbox[1] == pytest.approx(-1.31)  # min_lat
        assert bbox[2] == pytest.approx(36.81)  # max_lon
        assert bbox[3] == pytest.approx(-1.3)  # max_lat

    def test_empty_coords(self):
        assert _compute_bbox([]) == [0.0, 0.0, 0.0, 0.0]

    def test_single_point(self):
        bbox = _compute_bbox([[10.0, 20.0]])
        assert bbox == [10.0, 20.0, 10.0, 20.0]


class TestBufferBbox:
    def test_zero_buffer(self):
        bbox = [36.8, -1.31, 36.81, -1.3]
        buffered = _buffer_bbox(bbox, 0)
        assert buffered == bbox

    def test_positive_buffer_expands(self):
        bbox = [36.8, -1.31, 36.81, -1.3]
        buffered = _buffer_bbox(bbox, 100)
        assert buffered[0] < bbox[0]  # min_lon decreased
        assert buffered[1] < bbox[1]  # min_lat decreased
        assert buffered[2] > bbox[2]  # max_lon increased
        assert buffered[3] > bbox[3]  # max_lat increased

    def test_buffer_magnitude(self):
        """100m buffer should be roughly 0.0009 degrees latitude."""
        bbox = [0.0, 0.0, 1.0, 1.0]
        buffered = _buffer_bbox(bbox, 100)
        lat_offset = buffered[3] - bbox[3]
        assert 0.0005 < lat_offset < 0.002


class TestGeodesicArea:
    def test_small_polygon_positive_area(self):
        # ~1.1km x 1.1km rectangle near equator
        coords = [
            [36.8, -1.3],
            [36.81, -1.3],
            [36.81, -1.31],
            [36.8, -1.31],
            [36.8, -1.3],
        ]
        area, _peri = _geodesic_area_and_perimeter(coords)
        assert area > 0
        # ~120 hectares for a 1.1km square
        assert 50 < area < 200

    def test_degenerate_polygon(self):
        assert _geodesic_area_and_perimeter([]) == (0.0, 0.0)
        assert _geodesic_area_and_perimeter([[0, 0]]) == (0.0, 0.0)
        assert _geodesic_area_and_perimeter([[0, 0], [1, 0]]) == (0.0, 0.0)


class TestCentroid:
    def test_rectangle_centroid(self):
        coords = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        c = _centroid(coords)
        assert c[0] == pytest.approx(5.0, abs=0.5)
        assert c[1] == pytest.approx(5.0, abs=0.5)


class TestPrepareAOI:
    def test_returns_aoi(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature)
        assert isinstance(aoi, AOI)
        assert aoi.feature_name == "Block A - Fuji Apple"

    def test_bbox_computed(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature)
        assert aoi.bbox[0] == pytest.approx(36.8)
        assert aoi.bbox[2] == pytest.approx(36.81)

    def test_buffered_bbox_larger(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature, buffer_m=100)
        assert aoi.buffered_bbox[0] < aoi.bbox[0]
        assert aoi.buffered_bbox[2] > aoi.bbox[2]

    def test_area_positive(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature)
        assert aoi.area_ha > 0

    def test_centroid_within_bbox(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature)
        assert aoi.bbox[0] <= aoi.centroid[0] <= aoi.bbox[2]
        assert aoi.bbox[1] <= aoi.centroid[1] <= aoi.bbox[3]

    def test_metadata_preserved(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature)
        assert aoi.metadata == sample_feature.metadata

    def test_custom_buffer(self, sample_feature: Feature):
        aoi = prepare_aoi(sample_feature, buffer_m=200)
        assert aoi.buffer_m == 200

    def test_area_warning_for_huge_polygon(self):
        """A polygon spanning 10 degrees should trigger area warning."""
        f = Feature(
            name="Huge",
            exterior_coords=[[30, -10], [40, -10], [40, 0], [30, 0], [30, -10]],
        )
        aoi = prepare_aoi(f)
        assert aoi.area_warning != ""


class TestSquareBbox:
    """Tests for ``square_bbox``."""

    def test_already_square_adds_padding(self):
        from treesight.geo import square_bbox

        # ~111m per side at equator → square already
        bbox = [36.0, 0.0, 36.001, 0.001]
        result = square_bbox(bbox, padding_pct=10.0)

        # Should still be centred on original
        mid_lon = (bbox[0] + bbox[2]) / 2
        mid_lat = (bbox[1] + bbox[3]) / 2
        result_mid_lon = (result[0] + result[2]) / 2
        result_mid_lat = (result[1] + result[3]) / 2
        assert abs(result_mid_lon - mid_lon) < 1e-6
        assert abs(result_mid_lat - mid_lat) < 1e-6

        # Side should be ~10% larger than original
        orig_lat_span = bbox[3] - bbox[1]
        result_lat_span = result[3] - result[1]
        assert result_lat_span > orig_lat_span

    def test_rectangular_becomes_square(self):
        from treesight.geo import square_bbox

        # Wide rectangle: lon span > lat span
        bbox = [36.0, 0.0, 36.01, 0.001]  # ~10x wider than tall
        result = square_bbox(bbox, padding_pct=0.0)

        result_lon_span = result[2] - result[0]
        result_lat_span = result[3] - result[1]
        # In metres they should be approximately equal
        import math

        from treesight.constants import METRES_PER_DEGREE_LATITUDE

        lat_m = result_lat_span * METRES_PER_DEGREE_LATITUDE
        lon_m = (
            result_lon_span
            * METRES_PER_DEGREE_LATITUDE
            * math.cos(math.radians((result[1] + result[3]) / 2))
        )
        assert abs(lat_m - lon_m) / max(lat_m, lon_m) < 0.01  # <1% difference

    def test_contains_original_bbox(self):
        from treesight.geo import square_bbox

        bbox = [36.8, -1.31, 36.81, -1.3]
        result = square_bbox(bbox, padding_pct=10.0)
        assert result[0] <= bbox[0]
        assert result[1] <= bbox[1]
        assert result[2] >= bbox[2]
        assert result[3] >= bbox[3]

    def test_zero_padding(self):
        from treesight.geo import square_bbox

        bbox = [0.0, 0.0, 0.001, 0.001]
        result = square_bbox(bbox, padding_pct=0.0)
        # Side should be >= original span (no padding, but squaring)
        assert result[2] - result[0] >= bbox[2] - bbox[0] - 1e-10
        assert result[3] - result[1] >= bbox[3] - bbox[1] - 1e-10
