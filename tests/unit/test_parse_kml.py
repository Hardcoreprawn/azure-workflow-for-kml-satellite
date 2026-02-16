"""Unit tests for KML parsing (M-1.3).

Tests the parse_kml activity function against the test KML files,
covering valid inputs, malformed files, and coordinate validation.

References:
- Issue #4: M-1.3 KML parsing — single polygon
- PID 7.4.1: Zero-assumption input handling
- PID 7.4.3: Defensive geometry processing
- PID 7.4.7: Test pyramid — unit tier
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kml_satellite.activities.parse_kml import (
    InvalidCoordinateError,
    KmlParseError,
    KmlValidationError,
    parse_kml_file,
)
from kml_satellite.models.feature import Feature

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EDGE_CASES_DIR = DATA_DIR / "edge_cases"


# ---------------------------------------------------------------------------
# Test: Valid single polygon (01_single_polygon_orchard.kml)
# ---------------------------------------------------------------------------


class TestSinglePolygonOrchard:
    """Parse test file 01: single polygon orchard in Yakima Valley, WA."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "01_single_polygon_orchard.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        assert len(features) == 1

    def test_feature_name(self, features: list[Feature]) -> None:
        assert features[0].name == "Block A - Fuji Apple"

    def test_feature_description(self, features: list[Feature]) -> None:
        assert "Fuji apple" in features[0].description

    def test_crs_is_wgs84(self, features: list[Feature]) -> None:
        assert features[0].crs == "EPSG:4326"

    def test_exterior_coords_count(self, features: list[Feature]) -> None:
        # 5 vertices (4 corners + closing point)
        assert features[0].vertex_count == 5

    def test_exterior_coords_are_closed(self, features: list[Feature]) -> None:
        coords = features[0].exterior_coords
        assert coords[0] == coords[-1]

    def test_no_interior_rings(self, features: list[Feature]) -> None:
        assert not features[0].has_holes

    def test_coordinates_within_wgs84_bounds(self, features: list[Feature]) -> None:
        for lon, lat in features[0].exterior_coords:
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90

    def test_coordinates_in_yakima_valley(self, features: list[Feature]) -> None:
        """Coordinates should be in Yakima Valley, WA area."""
        for lon, lat in features[0].exterior_coords:
            assert -121 < lon < -120, f"Longitude {lon} not in Yakima Valley"
            assert 46 < lat < 47, f"Latitude {lat} not in Yakima Valley"

    def test_extended_data_orchard_name(self, features: list[Feature]) -> None:
        assert features[0].metadata.get("orchard_name") == "Alpha Orchard"

    def test_extended_data_tree_variety(self, features: list[Feature]) -> None:
        assert features[0].metadata.get("tree_variety") == "Fuji Apple"

    def test_extended_data_planting_year(self, features: list[Feature]) -> None:
        assert features[0].metadata.get("planting_year") == "2018"

    def test_source_file_recorded(self, features: list[Feature]) -> None:
        assert features[0].source_file == "01_single_polygon_orchard.kml"

    def test_feature_index_is_zero(self, features: list[Feature]) -> None:
        assert features[0].feature_index == 0


# ---------------------------------------------------------------------------
# Test: No extended data (08_no_extended_data.kml)
# ---------------------------------------------------------------------------


class TestNoExtendedData:
    """Parse test file 08: bare polygon with no ExtendedData."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "08_no_extended_data.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        assert len(features) == 1

    def test_feature_name(self, features: list[Feature]) -> None:
        assert features[0].name == "Unnamed Field"

    def test_metadata_is_empty(self, features: list[Feature]) -> None:
        # No ExtendedData → empty metadata dict
        assert features[0].metadata == {} or all(
            v.strip() == "" for v in features[0].metadata.values()
        )

    def test_valid_polygon(self, features: list[Feature]) -> None:
        assert features[0].vertex_count >= 4
        assert features[0].exterior_coords[0] == features[0].exterior_coords[-1]


# ---------------------------------------------------------------------------
# Test: Malformed — not XML (11_malformed_not_xml.kml)
# ---------------------------------------------------------------------------


class TestMalformedNotXml:
    """Parse edge case 11: file is plain text, not XML."""

    def test_raises_kml_parse_error(self) -> None:
        with pytest.raises(KmlParseError, match="Not valid XML"):
            parse_kml_file(EDGE_CASES_DIR / "11_malformed_not_xml.kml")


# ---------------------------------------------------------------------------
# Test: Malformed — unclosed tags (12_malformed_unclosed_tags.kml)
# ---------------------------------------------------------------------------


class TestMalformedUnclosedTags:
    """Parse edge case 12: XML with unclosed tags."""

    def test_raises_kml_parse_error(self) -> None:
        with pytest.raises(KmlParseError, match="Not valid XML"):
            parse_kml_file(EDGE_CASES_DIR / "12_malformed_unclosed_tags.kml")


# ---------------------------------------------------------------------------
# Test: Invalid coordinates (16_invalid_coordinates.kml)
# ---------------------------------------------------------------------------


class TestInvalidCoordinates:
    """Parse edge case 16: coordinates outside WGS 84 bounds."""

    def test_raises_invalid_coordinate_error(self) -> None:
        with pytest.raises(InvalidCoordinateError):
            parse_kml_file(EDGE_CASES_DIR / "16_invalid_coordinates.kml")

    def test_error_message_contains_value(self) -> None:
        with pytest.raises(InvalidCoordinateError, match=r"-200|95"):
            parse_kml_file(EDGE_CASES_DIR / "16_invalid_coordinates.kml")


# ---------------------------------------------------------------------------
# Test: Feature model serialisation
# ---------------------------------------------------------------------------


class TestFeatureSerialisation:
    """Test Feature.to_dict() / Feature.from_dict() round-trip."""

    @pytest.fixture()
    def sample_feature(self) -> Feature:
        return Feature(
            name="Test Orchard",
            description="A test polygon",
            exterior_coords=[
                (-120.5, 46.6),
                (-120.5, 46.7),
                (-120.4, 46.7),
                (-120.4, 46.6),
                (-120.5, 46.6),
            ],
            interior_coords=[],
            crs="EPSG:4326",
            metadata={"orchard_name": "Test", "variety": "Granny Smith"},
            source_file="test.kml",
            feature_index=0,
        )

    def test_to_dict_round_trip(self, sample_feature: Feature) -> None:
        d = sample_feature.to_dict()
        restored = Feature.from_dict(d)
        assert restored.name == sample_feature.name
        assert restored.description == sample_feature.description
        assert restored.crs == sample_feature.crs
        assert restored.metadata == sample_feature.metadata
        assert restored.source_file == sample_feature.source_file
        assert restored.feature_index == sample_feature.feature_index

    def test_to_dict_coords_are_lists(self, sample_feature: Feature) -> None:
        """Durable Functions requires JSON-serialisable output (lists, not tuples)."""
        d = sample_feature.to_dict()
        for coord in d["exterior_coords"]:  # type: ignore[union-attr]
            assert isinstance(coord, list)

    def test_from_dict_with_missing_optional_fields(self) -> None:
        minimal = {"name": "Minimal", "exterior_coords": []}
        f = Feature.from_dict(minimal)
        assert f.name == "Minimal"
        assert f.crs == "EPSG:4326"
        assert f.metadata == {}

    def test_from_dict_rejects_invalid_exterior_type(self) -> None:
        with pytest.raises(TypeError, match="exterior_coords must be a list"):
            Feature.from_dict({"name": "Bad", "exterior_coords": "not a list"})

    def test_from_dict_rejects_invalid_metadata_type(self) -> None:
        with pytest.raises(TypeError, match="metadata must be a dict"):
            Feature.from_dict({"name": "Bad", "metadata": "not a dict"})


# ---------------------------------------------------------------------------
# Test: Feature properties
# ---------------------------------------------------------------------------


class TestFeatureProperties:
    """Test computed properties on the Feature dataclass."""

    def test_vertex_count(self) -> None:
        f = Feature(
            name="Test",
            exterior_coords=[(-1, 1), (-1, 2), (0, 2), (0, 1), (-1, 1)],
        )
        assert f.vertex_count == 5

    def test_has_holes_true(self) -> None:
        f = Feature(
            name="With Hole",
            exterior_coords=[(-1, 1), (-1, 2), (0, 2), (0, 1), (-1, 1)],
            interior_coords=[[(-0.5, 1.2), (-0.5, 1.8), (-0.2, 1.8), (-0.2, 1.2), (-0.5, 1.2)]],
        )
        assert f.has_holes is True

    def test_has_holes_false(self) -> None:
        f = Feature(name="No Hole", exterior_coords=[(-1, 1), (-1, 2), (0, 2), (0, 1), (-1, 1)])
        assert f.has_holes is False


# ---------------------------------------------------------------------------
# Test: Empty and point-only inputs
# ---------------------------------------------------------------------------


class TestEmptyAndNonPolygonInputs:
    """Parse files 13-14: no polygon features to extract."""

    def test_empty_no_features_returns_empty(self) -> None:
        """File 13: valid KML document with no Placemarks → empty list."""
        features = parse_kml_file(EDGE_CASES_DIR / "13_empty_no_features.kml")
        assert features == []

    def test_point_only_returns_empty(self) -> None:
        """File 14: KML with Point geometry only → empty list (no polygons)."""
        features = parse_kml_file(EDGE_CASES_DIR / "14_point_only_no_polygons.kml")
        assert features == []


# ---------------------------------------------------------------------------
# Test: Coordinate validation edge cases
# ---------------------------------------------------------------------------


class TestCoordinateValidation:
    """Direct tests for coordinate validation functions."""

    def test_valid_coords_pass(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_coordinates

        _validate_coordinates([(-120.5, 46.6), (-120.4, 46.7)], "test")

    def test_longitude_out_of_range(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_coordinates

        with pytest.raises(InvalidCoordinateError, match="Longitude"):
            _validate_coordinates([(-200.0, 46.6)], "test")

    def test_latitude_out_of_range(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_coordinates

        with pytest.raises(InvalidCoordinateError, match="Latitude"):
            _validate_coordinates([(-120.5, 95.0)], "test")

    def test_boundary_values_pass(self) -> None:
        """Coordinates exactly at WGS 84 bounds should be valid."""
        from kml_satellite.activities.parse_kml import _validate_coordinates

        _validate_coordinates([(-180.0, -90.0), (180.0, 90.0)], "test")


# ---------------------------------------------------------------------------
# Test: Polygon ring validation
# ---------------------------------------------------------------------------


class TestPolygonRingValidation:
    """Test ring closure and minimum vertex requirements."""

    def test_auto_closes_unclosed_ring(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_polygon_ring

        coords = [(-120.5, 46.6), (-120.5, 46.7), (-120.4, 46.7), (-120.4, 46.6)]
        result = _validate_polygon_ring(coords, "test")
        assert result[0] == result[-1]
        assert len(result) == 5

    def test_already_closed_ring_unchanged(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_polygon_ring

        coords = [(-120.5, 46.6), (-120.5, 46.7), (-120.4, 46.7), (-120.4, 46.6), (-120.5, 46.6)]
        result = _validate_polygon_ring(coords, "test")
        assert len(result) == 5

    def test_too_few_points_raises(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_polygon_ring

        with pytest.raises(KmlValidationError, match="only 2 point"):
            _validate_polygon_ring([(-120.5, 46.6), (-120.4, 46.7)], "test")

    def test_duplicate_vertices_raises(self) -> None:
        from kml_satellite.activities.parse_kml import _validate_polygon_ring

        with pytest.raises(KmlValidationError, match="fewer than 3 distinct"):
            _validate_polygon_ring(
                [(-120.5, 46.6), (-120.5, 46.6), (-120.5, 46.6), (-120.5, 46.6)],
                "test",
            )


# ---------------------------------------------------------------------------
# Test: XML validation
# ---------------------------------------------------------------------------


class TestXmlValidation:
    """Test XML and KML namespace validation."""

    def test_rejects_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.kml"
        empty.write_text("")
        with pytest.raises(KmlParseError, match="empty"):
            parse_kml_file(empty)

    def test_rejects_non_kml_xml(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "not_kml.kml"
        xml_file.write_text('<?xml version="1.0"?><root><element/></root>')
        with pytest.raises(KmlParseError, match="Not a KML file"):
            parse_kml_file(xml_file)

    def test_nonexistent_file_raises(self) -> None:
        with pytest.raises(KmlParseError, match="Cannot read"):
            parse_kml_file(Path("/nonexistent/path/file.kml"))


# ---------------------------------------------------------------------------
# Test: Shapely geometry validation
# ---------------------------------------------------------------------------


class TestShapelyValidation:
    """Test that shapely geometry validation catches degenerate polygons."""

    def test_zero_area_polygon_raises(self, tmp_path: Path) -> None:
        """A polygon with all collinear points has zero area."""
        kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Collinear</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -120.5,46.6,0
              -120.4,46.6,0
              -120.3,46.6,0
              -120.2,46.6,0
              -120.5,46.6,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "zero_area.kml"
        kml_file.write_text(kml_content)
        with pytest.raises(KmlValidationError, match=r"Zero-area|make_valid"):
            parse_kml_file(kml_file)
