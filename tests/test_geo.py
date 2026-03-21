"""Tests for geometry computation — prepare_aoi, bbox, area, centroid (§3.1)."""

from __future__ import annotations

import pytest

from treesight.geo import (
    _buffer_bbox,
    _centroid,
    _compute_bbox,
    _geodesic_area_ha,
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
        area = _geodesic_area_ha(coords)
        assert area > 0
        # ~120 hectares for a 1.1km square
        assert 50 < area < 200

    def test_degenerate_polygon(self):
        assert _geodesic_area_ha([]) == 0.0
        assert _geodesic_area_ha([[0, 0]]) == 0.0
        assert _geodesic_area_ha([[0, 0], [1, 0]]) == 0.0


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
