"""Tests for geometry computation — prepare_aoi, bbox, area, centroid (§3.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from treesight.geo import (
    _buffer_bbox,
    _compute_bbox,
    _geodesic_area_and_perimeter,
    centroid,
    cluster_aois,
    prepare_aoi,
)
from treesight.models.aoi import AOI
from treesight.models.feature import Feature
from treesight.models.geometry import PolygonGeometry, PolygonPart


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
        c = centroid(coords)
        assert c[0] == pytest.approx(5.0, abs=0.5)
        assert c[1] == pytest.approx(5.0, abs=0.5)

    def test_returns_lon_lat_list(self):
        """centroid() must return [lon, lat] — canonical project coordinate order."""
        coords = [[1.0, 2.0], [3.0, 4.0], [5.0, 2.0], [1.0, 2.0]]
        result = centroid(coords)
        assert isinstance(result, list)
        assert len(result) == 2
        # lon == mean of c[0]; lat == mean of c[1]
        assert result[0] == pytest.approx(3.0)
        assert result[1] == pytest.approx(8 / 3)

    def test_single_implementation_exists(self):
        """Regression: exactly one centroid implementation; no duplicate in enrichment runner."""
        import ast
        import pathlib

        runner_path = pathlib.Path(__file__).parents[1] / "treesight" / "pipeline" / "enrichment" / "runner.py"
        tree = ast.parse(runner_path.read_text())
        centroid_defs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in ("centroid", "_centroid")
        ]
        assert centroid_defs == [], (
            f"Found local centroid definition(s) in runner.py: "
            f"{[n.name for n in centroid_defs]}. Use treesight.geo.centroid instead."
        )


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
            geometry=PolygonGeometry(
                parts=(
                    PolygonPart(
                        outer=((30, -10), (40, -10), (40, 0), (30, 0), (30, -10)),
                    ),
                ),
            ),
        )
        aoi = prepare_aoi(f)
        assert aoi.area_warning != ""

    def test_prepare_aoi_metrics_account_for_holes_and_multipart_geometry(self):
        exterior = ((0, 0), (2, 0), (2, 2), (0, 2), (0, 0))
        hole = ((0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5), (0.5, 0.5))
        second_part = ((3, 0), (4, 0), (4, 1), (3, 1), (3, 0))
        geometry = PolygonGeometry(
            parts=(
                PolygonPart(outer=exterior, inners=(hole,)),
                PolygonPart(outer=second_part),
            ),
        )
        feature = Feature(name="Multi-part plot", geometry=geometry)

        aoi = prepare_aoi(feature)
        outer_area, outer_perimeter = _geodesic_area_and_perimeter([list(point) for point in exterior])
        hole_area, hole_perimeter = _geodesic_area_and_perimeter([list(point) for point in hole])
        second_area, second_perimeter = _geodesic_area_and_perimeter([list(point) for point in second_part])

        assert aoi.area_ha == pytest.approx(outer_area - hole_area + second_area, rel=1e-6)
        assert aoi.perimeter_km == pytest.approx(outer_perimeter + hole_perimeter + second_perimeter, rel=1e-6)
        assert aoi.bbox == [0.0, 0.0, 4.0, 2.0]


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
        lon_m = result_lon_span * METRES_PER_DEGREE_LATITUDE * math.cos(math.radians((result[1] + result[3]) / 2))
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


# ---------------------------------------------------------------------------
# Spatial clustering (#581)
# ---------------------------------------------------------------------------


class TestClusterAois:
    """Tests for DBSCAN-style spatial clustering of AOI centroids."""

    def test_single_aoi_returns_one_cluster(self):
        aois = [{"name": "Farm A", "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31]]}]
        clusters = cluster_aois(aois, eps_km=25.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_nearby_aois_in_same_cluster(self):
        """AOIs within eps_km should be grouped together."""
        aois = [
            {"name": "A", "coords": [[36.80, -1.30], [36.81, -1.30], [36.81, -1.31]]},
            {"name": "B", "coords": [[36.82, -1.30], [36.83, -1.30], [36.83, -1.31]]},
        ]
        clusters = cluster_aois(aois, eps_km=25.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_distant_aois_in_separate_clusters(self):
        """AOIs far apart should be in different clusters."""
        aois = [
            {"name": "Kenya", "coords": [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31]]},
            {"name": "Brazil", "coords": [[-50.0, -10.0], [-49.9, -10.0], [-49.9, -10.1]]},
        ]
        clusters = cluster_aois(aois, eps_km=25.0)
        assert len(clusters) == 2

    def test_three_groups(self):
        """Three widely-separated groups should form three clusters."""
        aois = [
            # Group 1: Kenya
            {"name": "Kenya-1", "coords": [[36.80, -1.30], [36.81, -1.31]]},
            {"name": "Kenya-2", "coords": [[36.82, -1.30], [36.83, -1.31]]},
            # Group 2: Brazil
            {"name": "Brazil-1", "coords": [[-50.0, -10.0], [-49.9, -10.1]]},
            # Group 3: Indonesia
            {"name": "Indo-1", "coords": [[110.0, -7.0], [110.1, -7.1]]},
            {"name": "Indo-2", "coords": [[110.05, -7.0], [110.15, -7.1]]},
        ]
        clusters = cluster_aois(aois, eps_km=25.0)
        assert len(clusters) == 3
        sizes = sorted(len(c) for c in clusters)
        assert sizes == [1, 2, 2]

    def test_empty_input(self):
        assert cluster_aois([], eps_km=25.0) == []

    def test_preserves_aoi_dicts(self):
        """Clustered items should be the same dicts (by identity)."""
        aois = [
            {"name": "A", "coords": [[36.8, -1.3]], "area_ha": 10},
            {"name": "B", "coords": [[36.81, -1.3]], "area_ha": 20},
        ]
        clusters = cluster_aois(aois, eps_km=100.0)
        flat = [item for cluster in clusters for item in cluster]
        assert len(flat) == 2
        assert flat[0]["area_ha"] in {10, 20}


# ---------------------------------------------------------------------------
# Geometry edge cases (regression guards for pipeline flakiness)
# ---------------------------------------------------------------------------


class TestPrepareAoiEdgeCases:
    """Guards against degenerate geometry that can stall the ingestion phase."""

    @pytest.mark.parametrize(
        "ring",
        [
            ((36.8, -1.3), (36.81, -1.3), (36.82, -1.3), (36.8, -1.3)),
            ((36.8, -1.3), (36.81, -1.31)),
            ((36.8, -1.3),),
        ],
    )
    def test_rejects_degenerate_rings(self, ring):
        """Invalid geometry fails at model construction rather than producing zero-area AOIs."""
        with pytest.raises(ValidationError):
            PolygonPart(outer=ring)

    def test_polygon_near_antimeridian(self):
        """Do not mistake a short dateline crossing for a world-spanning plot."""
        with pytest.raises(ValidationError, match="antimeridian"):
            (
                PolygonPart(
                    outer=(
                        (179.9, -16.5),
                        (-179.8, -16.5),
                        (-179.8, -16.6),
                        (179.9, -16.6),
                        (179.9, -16.5),
                    ),
                ),
            )

    def test_rejects_duplicate_ring_with_insufficient_distinct_vertices(self):
        with pytest.raises(ValidationError):
            PolygonPart(outer=((36.8, -1.3), (36.8, -1.3), (36.81, -1.31), (36.8, -1.3)))


class TestGeodesicAreaEdgeCases:
    def test_three_collinear_points_zero_area(self):
        """Three collinear points have zero geodesic area."""
        coords = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
        area, _ = _geodesic_area_and_perimeter(coords)
        assert area == pytest.approx(0.0, abs=1.0)

    def test_negative_buffer_treated_as_zero(self):
        """Negative buffer should not shrink the bbox (clamp to original)."""
        bbox = [36.8, -1.31, 36.81, -1.3]
        result = _buffer_bbox(bbox, -100)
        assert result == bbox

    def test_chain_linkage(self):
        """AOIs forming a chain should be merged into one cluster via transitivity."""
        # A-B close, B-C close, but A-C might be > eps apart
        # With eps=30km, each pair ~15km apart, but chain links them
        aois = [
            {"name": "A", "coords": [[36.80, -1.30]]},
            {"name": "B", "coords": [[36.93, -1.30]]},  # ~14km east of A
            {"name": "C", "coords": [[37.06, -1.30]]},  # ~14km east of B
        ]
        clusters = cluster_aois(aois, eps_km=20.0)
        assert len(clusters) == 1

    def test_aois_with_missing_coords_skipped(self):
        """AOIs without coords should still be included as singleton clusters."""
        aois = [
            {"name": "Good", "coords": [[36.8, -1.3]]},
            {"name": "Empty", "coords": []},
        ]
        clusters = cluster_aois(aois, eps_km=25.0)
        # Both returned: good in one cluster, empty in another
        flat = [item for cluster in clusters for item in cluster]
        assert len(flat) == 2
