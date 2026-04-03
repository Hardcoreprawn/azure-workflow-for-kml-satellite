"""Tests for multi-AOI parsing, geometry, and end-to-end edge cases.

Exercises the pipeline from KML bytes → Feature list → AOI list with
a variety of polygon shapes, counts, and configurations.
"""

from __future__ import annotations

import pytest

from treesight.geo import (
    _compute_bbox,
    _geodesic_area_and_perimeter,
    prepare_aoi,
)
from treesight.models.aoi import AOI
from treesight.models.feature import Feature
from treesight.parsers.lxml_parser import parse_kml_lxml


def _geodesic_perimeter_km(coords):
    """Thin wrapper for tests — extracts perimeter from merged function."""
    _, perimeter = _geodesic_area_and_perimeter(coords)
    return perimeter


# ── Single-polygon KML ─────────────────────────────────────


class TestSinglePolygon:
    def test_parse_single(self, single_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(single_polygon_kml_bytes, source_file="single.kml")
        assert len(features) == 1
        assert features[0].name == "Block A - Avocado"

    def test_prepare_single_aoi(self, single_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(single_polygon_kml_bytes, source_file="single.kml")
        aoi = prepare_aoi(features[0])
        assert isinstance(aoi, AOI)
        assert aoi.area_ha > 0
        assert aoi.perimeter_km > 0

    def test_metadata_preserved(self, single_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(single_polygon_kml_bytes, source_file="single.kml")
        assert features[0].metadata.get("crop") == "avocado"


# ── Two-polygon KML (existing sample.kml) ──────────────────


class TestTwoPolygons:
    def test_parse_two(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        assert len(features) == 2

    def test_distinct_names(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        names = {f.name for f in features}
        assert len(names) == 2

    def test_distinct_bboxes(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        aois = [prepare_aoi(f) for f in features]
        # Non-overlapping blocks → distinct bboxes
        assert aois[0].bbox != aois[1].bbox

    def test_all_aois_have_positive_area(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        aois = [prepare_aoi(f) for f in features]
        assert all(a.area_ha > 0 for a in aois)

    def test_all_aois_have_positive_perimeter(self, sample_kml_bytes: bytes):
        features = parse_kml_lxml(sample_kml_bytes, source_file="sample.kml")
        aois = [prepare_aoi(f) for f in features]
        assert all(a.perimeter_km > 0 for a in aois)


# ── Five-polygon KML ───────────────────────────────────────


class TestFivePolygons:
    def test_parse_five(self, five_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(five_polygons_kml_bytes, source_file="five.kml")
        assert len(features) == 5

    def test_sequential_indices(self, five_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(five_polygons_kml_bytes, source_file="five.kml")
        assert [f.feature_index for f in features] == [0, 1, 2, 3, 4]

    def test_all_aois_valid(self, five_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(five_polygons_kml_bytes, source_file="five.kml")
        aois = [prepare_aoi(f) for f in features]
        assert len(aois) == 5
        assert all(a.area_ha > 0 for a in aois)

    def test_total_area_reasonable(self, five_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(five_polygons_kml_bytes, source_file="five.kml")
        aois = [prepare_aoi(f) for f in features]
        total = sum(a.area_ha for a in aois)
        # 5 blocks of ~0.01 deg² each, ~120 ha each → ~500-700 ha total
        assert 200 < total < 1000


# ── MultiPolygon in a single Placemark ──────────────────────


class TestMultiPolygon:
    def test_multi_geometry_produces_multiple_features(self, multi_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(multi_polygon_kml_bytes, source_file="multi.kml")
        assert len(features) == 2

    def test_multi_geometry_names_same(self, multi_polygon_kml_bytes: bytes):
        """Both polygons from a MultiGeometry share the placemark name."""
        features = parse_kml_lxml(multi_polygon_kml_bytes, source_file="multi.kml")
        assert features[0].name == features[1].name == "Multi Block"

    def test_multi_geometry_distinct_coords(self, multi_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(multi_polygon_kml_bytes, source_file="multi.kml")
        assert features[0].exterior_coords != features[1].exterior_coords


# ── Polygon with hole ──────────────────────────────────────


class TestPolygonWithHole:
    def test_parse_hole(self, polygon_with_hole_kml_bytes: bytes):
        features = parse_kml_lxml(polygon_with_hole_kml_bytes, source_file="hole.kml")
        assert len(features) == 1

    def test_interior_coords_present(self, polygon_with_hole_kml_bytes: bytes):
        features = parse_kml_lxml(polygon_with_hole_kml_bytes, source_file="hole.kml")
        assert features[0].has_holes is True
        assert len(features[0].interior_coords) == 1

    def test_interior_ring_has_coords(self, polygon_with_hole_kml_bytes: bytes):
        features = parse_kml_lxml(polygon_with_hole_kml_bytes, source_file="hole.kml")
        inner = features[0].interior_coords[0]
        assert len(inner) >= 4  # closed ring: at least 3 vertices + closing point

    def test_aoi_area_excludes_hole_indication(self, polygon_with_hole_kml_bytes: bytes):
        """AOI should still compute area from exterior ring (hole handling is geometry-level)."""
        features = parse_kml_lxml(polygon_with_hole_kml_bytes, source_file="hole.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 0
        assert aoi.perimeter_km > 0


# ── Tiny polygon ───────────────────────────────────────────


class TestTinyPolygon:
    def test_parse_tiny(self, tiny_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(tiny_polygon_kml_bytes, source_file="tiny.kml")
        assert len(features) == 1

    def test_area_very_small(self, tiny_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(tiny_polygon_kml_bytes, source_file="tiny.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha < 1.0  # Under 1 hectare

    def test_perimeter_very_small(self, tiny_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(tiny_polygon_kml_bytes, source_file="tiny.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.perimeter_km < 0.5  # Under 500m

    def test_no_area_warning(self, tiny_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(tiny_polygon_kml_bytes, source_file="tiny.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_warning == ""


# ── Huge polygon ───────────────────────────────────────────


class TestHugePolygon:
    def test_parse_huge(self, huge_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(huge_polygon_kml_bytes, source_file="huge.kml")
        assert len(features) == 1

    def test_area_warning_triggered(self, huge_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(huge_polygon_kml_bytes, source_file="huge.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_warning != ""

    def test_area_massive(self, huge_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(huge_polygon_kml_bytes, source_file="huge.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 100_000  # >100k ha for 10° x 10° near equator


# ── Concave (L-shaped) polygon ─────────────────────────────


class TestConcavePolygon:
    def test_parse_concave(self, concave_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(concave_polygon_kml_bytes, source_file="concave.kml")
        assert len(features) == 1

    def test_vertex_count(self, concave_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(concave_polygon_kml_bytes, source_file="concave.kml")
        # L-shape: 7 coords including closing vertex
        assert features[0].vertex_count == 7

    def test_area_positive(self, concave_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(concave_polygon_kml_bytes, source_file="concave.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 0

    def test_low_compactness(self, concave_polygon_kml_bytes: bytes):
        """L-shaped polygon should have lower compactness than a square."""
        features = parse_kml_lxml(concave_polygon_kml_bytes, source_file="concave.kml")
        aoi = prepare_aoi(features[0])
        # Compactness = 4πA/P² — L-shapes are less compact than circles
        import math

        area_km2 = aoi.area_ha / 100
        if aoi.perimeter_km > 0:
            compactness = 4 * math.pi * area_km2 / (aoi.perimeter_km**2)
            assert compactness < 0.8  # Far from circular


# ── Adjacent polygons ──────────────────────────────────────


class TestAdjacentPolygons:
    def test_parse_adjacent(self, adjacent_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(adjacent_polygons_kml_bytes, source_file="adjacent.kml")
        assert len(features) == 2

    def test_shared_edge(self, adjacent_polygons_kml_bytes: bytes):
        """North block south edge == South block north edge (lat -1.31)."""
        features = parse_kml_lxml(adjacent_polygons_kml_bytes, source_file="adjacent.kml")
        bbox_n = _compute_bbox(features[0].exterior_coords)
        bbox_s = _compute_bbox(features[1].exterior_coords)
        assert bbox_n[1] == pytest.approx(bbox_s[3])  # min_lat_N ≈ max_lat_S

    def test_distinct_metadata(self, adjacent_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(adjacent_polygons_kml_bytes, source_file="adjacent.kml")
        assert features[0].metadata.get("crop") == "wheat"
        assert features[1].metadata.get("crop") == "maize"

    def test_similar_areas(self, adjacent_polygons_kml_bytes: bytes):
        """Adjacent blocks of same size should have similar areas."""
        features = parse_kml_lxml(adjacent_polygons_kml_bytes, source_file="adjacent.kml")
        aois = [prepare_aoi(f) for f in features]
        ratio = aois[0].area_ha / aois[1].area_ha
        assert 0.9 < ratio < 1.1


# ── Overlapping polygons ───────────────────────────────────


class TestOverlappingPolygons:
    def test_parse_overlapping(self, overlapping_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(overlapping_polygons_kml_bytes, source_file="overlap.kml")
        assert len(features) == 2

    def test_bboxes_overlap(self, overlapping_polygons_kml_bytes: bytes):
        features = parse_kml_lxml(overlapping_polygons_kml_bytes, source_file="overlap.kml")
        aois = [prepare_aoi(f) for f in features]
        # Block West max_lon (36.82) > Block East min_lon (36.81)
        assert aois[0].bbox[2] > aois[1].bbox[0]

    def test_areas_independent(self, overlapping_polygons_kml_bytes: bytes):
        """Each polygon's area is computed independently, overlap doesn't reduce."""
        features = parse_kml_lxml(overlapping_polygons_kml_bytes, source_file="overlap.kml")
        aois = [prepare_aoi(f) for f in features]
        # Both are same-sized rectangles
        assert abs(aois[0].area_ha - aois[1].area_ha) < 1.0


# ── Triangle polygon ──────────────────────────────────────


class TestTrianglePolygon:
    def test_parse_triangle(self, triangle_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(triangle_polygon_kml_bytes, source_file="tri.kml")
        assert len(features) == 1

    def test_minimum_vertex_count(self, triangle_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(triangle_polygon_kml_bytes, source_file="tri.kml")
        # 3 unique vertices + closing vertex = 4
        assert features[0].vertex_count == 4

    def test_area_positive(self, triangle_polygon_kml_bytes: bytes):
        features = parse_kml_lxml(triangle_polygon_kml_bytes, source_file="tri.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 0


# ── Perimeter computation ─────────────────────────────────


class TestPerimeter:
    def test_rectangle_perimeter(self):
        """~1.1km × 1.1km rectangle near equator → perimeter ≈ 4.4km."""
        coords = [[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.31], [36.8, -1.3]]
        p = _geodesic_perimeter_km(coords)
        assert 3.0 < p < 6.0

    def test_triangle_perimeter(self):
        coords = [[36.80, -1.30], [36.82, -1.30], [36.81, -1.32], [36.80, -1.30]]
        p = _geodesic_perimeter_km(coords)
        assert p > 0

    def test_degenerate_coords(self):
        assert _geodesic_perimeter_km([]) == 0.0
        assert _geodesic_perimeter_km([[0, 0]]) == 0.0

    def test_two_point_line(self):
        """Two-point input is degenerate — merged function requires ≥3 coords."""
        p = _geodesic_perimeter_km([[0, 0], [1, 0]])
        assert p == 0.0

    def test_perimeter_increases_with_size(self):
        small = [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]
        large = [[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1], [0, 0]]
        assert _geodesic_perimeter_km(large) > _geodesic_perimeter_km(small)

    def test_perimeter_in_aoi(self, sample_feature: Feature):
        """prepare_aoi should populate perimeter_km."""
        aoi = prepare_aoi(sample_feature)
        assert aoi.perimeter_km > 0


# ── Edge case: empty and malformed KML ─────────────────────


class TestEdgeCases:
    def test_empty_kml(self):
        kml = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document></Document></kml>'
        features = parse_kml_lxml(kml)
        assert features == []

    def test_placemark_without_polygon(self):
        """Placemarks with only Points should produce zero features."""
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Just a Point</name>
              <Point><coordinates>36.8,-1.3,0</coordinates></Point>
            </Placemark>
          </Document>
        </kml>"""
        features = parse_kml_lxml(kml)
        assert len(features) == 0

    def test_mixed_geometries(self):
        """A document with both Points and Polygons — only Polygons become features."""
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>A Point</name>
              <Point><coordinates>36.8,-1.3,0</coordinates></Point>
            </Placemark>
            <Placemark>
              <name>A Polygon</name>
              <Polygon>
                <outerBoundaryIs><LinearRing><coordinates>
                  36.80,-1.30,0 36.81,-1.30,0 36.81,-1.31,0 36.80,-1.31,0 36.80,-1.30,0
                </coordinates></LinearRing></outerBoundaryIs>
              </Polygon>
            </Placemark>
          </Document>
        </kml>"""
        features = parse_kml_lxml(kml)
        assert len(features) == 1
        assert features[0].name == "A Polygon"

    def test_polygon_too_few_coords_skipped(self):
        """< 3 vertices → polygon skipped, not an error."""
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Degenerate</name>
              <Polygon>
                <outerBoundaryIs><LinearRing><coordinates>
                  36.8,-1.3,0 36.81,-1.3,0
                </coordinates></LinearRing></outerBoundaryIs>
              </Polygon>
            </Placemark>
          </Document>
        </kml>"""
        features = parse_kml_lxml(kml)
        assert len(features) == 0

    def test_large_coordinate_precision(self):
        """Coordinates with many decimal places should parse correctly."""
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Precise</name>
              <Polygon>
                <outerBoundaryIs><LinearRing><coordinates>
                  36.12345678,-1.23456789,0
                  36.12445678,-1.23456789,0
                  36.12445678,-1.23556789,0
                  36.12345678,-1.23556789,0
                  36.12345678,-1.23456789,0
                </coordinates></LinearRing></outerBoundaryIs>
              </Polygon>
            </Placemark>
          </Document>
        </kml>"""
        features = parse_kml_lxml(kml)
        assert len(features) == 1
        coord = features[0].exterior_coords[0]
        assert coord[0] == pytest.approx(36.12345678)
