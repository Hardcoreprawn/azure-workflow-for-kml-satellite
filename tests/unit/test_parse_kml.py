"""Unit tests for KML parsing (M-1.3 + M-1.4).

Tests the parse_kml activity function against the test KML files,
covering valid inputs, multi-feature / multi-geometry files, nested
folders, Schema/SchemaData metadata, degenerate geometries, and edge cases.

References:
- Issue #4: M-1.3 KML parsing — single polygon
- Issue #5: M-1.4 KML parsing — multipolygon + multi-feature
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
    """Parse edge case 16: coordinates outside WGS 84 bounds.

    With M-1.4 graceful degradation (PID 7.4.2), invalid-coordinate
    features are *skipped* (returns empty list) rather than raising.
    """

    def test_invalid_coordinates_skipped(self) -> None:
        """All features have out-of-bounds coords → empty list."""
        features = parse_kml_file(EDGE_CASES_DIR / "16_invalid_coordinates.kml")
        assert features == []

    def test_does_not_raise(self) -> None:
        """Graceful degradation — no exception."""
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
        from kml_satellite.activities.parse_kml import validate_coordinates

        validate_coordinates([(-120.5, 46.6), (-120.4, 46.7)], "test")

    def test_longitude_out_of_range(self) -> None:
        from kml_satellite.activities.parse_kml import validate_coordinates

        with pytest.raises(InvalidCoordinateError, match="Longitude"):
            validate_coordinates([(-200.0, 46.6)], "test")

    def test_latitude_out_of_range(self) -> None:
        from kml_satellite.activities.parse_kml import validate_coordinates

        with pytest.raises(InvalidCoordinateError, match="Latitude"):
            validate_coordinates([(-120.5, 95.0)], "test")

    def test_boundary_values_pass(self) -> None:
        """Coordinates exactly at WGS 84 bounds should be valid."""
        from kml_satellite.activities.parse_kml import validate_coordinates

        validate_coordinates([(-180.0, -90.0), (180.0, 90.0)], "test")


# ---------------------------------------------------------------------------
# Test: Polygon ring validation
# ---------------------------------------------------------------------------


class TestPolygonRingValidation:
    """Test ring closure and minimum vertex requirements."""

    def test_auto_closes_unclosed_ring(self) -> None:
        from kml_satellite.activities.parse_kml import validate_polygon_ring

        coords = [(-120.5, 46.6), (-120.5, 46.7), (-120.4, 46.7), (-120.4, 46.6)]
        result = validate_polygon_ring(coords, "test")
        assert result[0] == result[-1]
        assert len(result) == 5

    def test_already_closed_ring_unchanged(self) -> None:
        from kml_satellite.activities.parse_kml import validate_polygon_ring

        coords = [(-120.5, 46.6), (-120.5, 46.7), (-120.4, 46.7), (-120.4, 46.6), (-120.5, 46.6)]
        result = validate_polygon_ring(coords, "test")
        assert len(result) == 5

    def test_too_few_points_raises(self) -> None:
        from kml_satellite.activities.parse_kml import validate_polygon_ring

        with pytest.raises(KmlValidationError, match="only 2 point"):
            validate_polygon_ring([(-120.5, 46.6), (-120.4, 46.7)], "test")

    def test_duplicate_vertices_raises(self) -> None:
        from kml_satellite.activities.parse_kml import validate_polygon_ring

        with pytest.raises(KmlValidationError, match="fewer than 3 distinct"):
            validate_polygon_ring(
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
    """Test that shapely geometry validation catches degenerate polygons.

    With M-1.4 graceful degradation (PID 7.4.2), a single invalid feature
    in a file is now *skipped* (returns empty list) rather than raising.
    """

    def test_zero_area_polygon_skipped(self, tmp_path: Path) -> None:
        """A polygon with all collinear points has zero area → skipped."""
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
        features = parse_kml_file(kml_file)
        assert features == []


# ===========================================================================
# M-1.4 Tests: Multi-feature, MultiGeometry, nested folders, edge cases
# ===========================================================================


# ---------------------------------------------------------------------------
# Test: MultiPolygon orchard blocks (02_multipolygon_orchard_blocks.kml)
# ---------------------------------------------------------------------------


class TestMultiPolygonOrchardBlocks:
    """Parse test file 02: single Placemark with MultiGeometry containing 3 polygons."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "02_multipolygon_orchard_blocks.kml")

    def test_returns_three_features(self, features: list[Feature]) -> None:
        """MultiGeometry with 3 polygons → 3 separate Feature objects (fan-out)."""
        assert len(features) == 3

    def test_all_features_have_same_metadata(self, features: list[Feature]) -> None:
        """All 3 polygons come from the same Placemark → share metadata."""
        for f in features:
            assert f.metadata.get("orchard_name") == "Beta Ranch"

    def test_tree_variety_metadata(self, features: list[Feature]) -> None:
        for f in features:
            assert f.metadata.get("tree_variety") == "Valencia Orange"

    def test_planting_year_metadata(self, features: list[Feature]) -> None:
        for f in features:
            assert f.metadata.get("planting_year") == "2015"

    def test_all_crs_wgs84(self, features: list[Feature]) -> None:
        for f in features:
            assert f.crs == "EPSG:4326"

    def test_all_polygons_closed(self, features: list[Feature]) -> None:
        for f in features:
            assert f.exterior_coords[0] == f.exterior_coords[-1]

    def test_all_polygons_have_enough_vertices(self, features: list[Feature]) -> None:
        for f in features:
            assert f.vertex_count >= 4

    def test_no_holes(self, features: list[Feature]) -> None:
        for f in features:
            assert not f.has_holes

    def test_source_file_recorded(self, features: list[Feature]) -> None:
        for f in features:
            assert f.source_file == "02_multipolygon_orchard_blocks.kml"

    def test_coordinates_in_central_valley(self, features: list[Feature]) -> None:
        """Coordinates should be in Central Valley, CA area."""
        for f in features:
            for lon, lat in f.exterior_coords:
                assert -120 < lon < -119, f"Longitude {lon} not in Central Valley"
                assert 36 < lat < 37, f"Latitude {lat} not in Central Valley"


# ---------------------------------------------------------------------------
# Test: Multi-feature vineyard (03_multi_feature_vineyard.kml)
# ---------------------------------------------------------------------------


class TestMultiFeatureVineyard:
    """Parse test file 03: 4 separate Placemarks, each with one polygon."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "03_multi_feature_vineyard.kml")

    def test_returns_four_features(self, features: list[Feature]) -> None:
        assert len(features) == 4

    def test_feature_names(self, features: list[Feature]) -> None:
        names = {f.name for f in features}
        expected = {
            "Block SB-1 - Sauvignon Blanc",
            "Block PN-2 - Pinot Noir",
            "Block A-3 - Braeburn Apple",
            "Block AV-4 - Hass Avocado",
        }
        assert names == expected

    def test_each_feature_has_metadata(self, features: list[Feature]) -> None:
        for f in features:
            assert f.metadata.get("orchard_name") == "Gamma Estate"

    def test_crop_types_varied(self, features: list[Feature]) -> None:
        """Features include both vineyard and orchard crop types."""
        crop_types = {f.metadata.get("crop_type") for f in features}
        assert "vineyard" in crop_types
        assert "orchard" in crop_types

    def test_irregular_polygon_vertex_count(self, features: list[Feature]) -> None:
        """Block AV-4 (Hass Avocado) has an irregular shape with 9 vertices."""
        avocado = next(f for f in features if "AV-4" in f.name)
        assert avocado.vertex_count == 9

    def test_all_polygons_valid(self, features: list[Feature]) -> None:
        for f in features:
            assert f.vertex_count >= 4
            assert f.exterior_coords[0] == f.exterior_coords[-1]

    def test_distinct_feature_indices(self, features: list[Feature]) -> None:
        """Each feature should have a distinct index."""
        indices = [f.feature_index for f in features]
        assert len(set(indices)) == 4

    def test_coordinates_in_hawkes_bay(self, features: list[Feature]) -> None:
        """Coordinates should be in Hawke's Bay, New Zealand."""
        for f in features:
            for lon, lat in f.exterior_coords:
                assert 176 < lon < 177, f"Longitude {lon} not in Hawke's Bay"
                assert -40 < lat < -39, f"Latitude {lat} not in Hawke's Bay"


# ---------------------------------------------------------------------------
# Test: Complex polygon with hole (04_complex_polygon_with_hole.kml)
# ---------------------------------------------------------------------------


class TestComplexPolygonWithHole:
    """Parse test file 04: polygon with inner boundary (hole)."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "04_complex_polygon_with_hole.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        assert len(features) == 1

    def test_has_hole(self, features: list[Feature]) -> None:
        assert features[0].has_holes is True

    def test_one_interior_ring(self, features: list[Feature]) -> None:
        assert len(features[0].interior_coords) == 1

    def test_interior_ring_is_closed(self, features: list[Feature]) -> None:
        hole = features[0].interior_coords[0]
        assert hole[0] == hole[-1]

    def test_interior_ring_has_enough_vertices(self, features: list[Feature]) -> None:
        hole = features[0].interior_coords[0]
        assert len(hole) >= 4

    def test_feature_name(self, features: list[Feature]) -> None:
        assert "Delta Farm" in features[0].name or "Macadamia" in features[0].name

    def test_metadata_orchard_name(self, features: list[Feature]) -> None:
        assert features[0].metadata.get("orchard_name") == "Delta Farm"

    def test_metadata_tree_variety(self, features: list[Feature]) -> None:
        assert features[0].metadata.get("tree_variety") == "Macadamia"

    def test_exterior_ring_is_closed(self, features: list[Feature]) -> None:
        coords = features[0].exterior_coords
        assert coords[0] == coords[-1]

    def test_hole_inside_exterior(self, features: list[Feature]) -> None:
        """The hole coordinates should be inside the exterior bounding box."""
        ext = features[0].exterior_coords
        lons = [c[0] for c in ext]
        lats = [c[1] for c in ext]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        for lon, lat in features[0].interior_coords[0]:
            assert min_lon <= lon <= max_lon
            assert min_lat <= lat <= max_lat


# ---------------------------------------------------------------------------
# Test: Irregular polygon, steep terrain (05_irregular_polygon_steep_terrain.kml)
# ---------------------------------------------------------------------------


class TestIrregularPolygonSteepTerrain:
    """Parse test file 05: high vertex-count polygon tracing terrain contours."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "05_irregular_polygon_steep_terrain.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        assert len(features) == 1

    def test_vertex_count_is_19(self, features: list[Feature]) -> None:
        """Polygon has 19 vertices (18 unique + closing)."""
        assert features[0].vertex_count == 19

    def test_polygon_is_closed(self, features: list[Feature]) -> None:
        coords = features[0].exterior_coords
        assert coords[0] == coords[-1]

    def test_no_holes(self, features: list[Feature]) -> None:
        assert not features[0].has_holes

    def test_feature_name(self, features: list[Feature]) -> None:
        assert features[0].name != ""

    def test_metadata_orchard_name(self, features: list[Feature]) -> None:
        assert features[0].metadata.get("orchard_name") == "Epsilon Vineyards"

    def test_coordinates_in_douro_valley(self, features: list[Feature]) -> None:
        """Coordinates should be in Douro Valley, Portugal."""
        for lon, lat in features[0].exterior_coords:
            assert -8 < lon < -7, f"Longitude {lon} not in Douro Valley"
            assert 41 < lat < 42, f"Latitude {lat} not in Douro Valley"


# ---------------------------------------------------------------------------
# Test: Folder nested features (09_folder_nested_features.kml)
# ---------------------------------------------------------------------------


class TestFolderNestedFeatures:
    """Parse test file 09: 4 features nested inside 3 Folders (2 levels deep)."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "09_folder_nested_features.kml")

    def test_returns_four_features(self, features: list[Feature]) -> None:
        """All 4 Placemarks found despite nested Folder structure."""
        assert len(features) == 4

    def test_feature_names(self, features: list[Feature]) -> None:
        names = {f.name for f in features}
        expected = {
            "N1 - Granny Smith",
            "N2 - Gala",
            "S1 - Bartlett Pear",
            "S2 - Bing Cherry",
        }
        assert names == expected

    def test_all_metadata_from_same_orchard(self, features: list[Feature]) -> None:
        for f in features:
            assert f.metadata.get("orchard_name") == "Theta Estate"

    def test_tree_varieties(self, features: list[Feature]) -> None:
        varieties = {f.metadata.get("tree_variety") for f in features}
        expected = {"Granny Smith Apple", "Gala Apple", "Bartlett Pear", "Bing Cherry"}
        assert varieties == expected

    def test_all_polygons_valid(self, features: list[Feature]) -> None:
        for f in features:
            assert f.vertex_count >= 4
            assert f.exterior_coords[0] == f.exterior_coords[-1]

    def test_no_holes(self, features: list[Feature]) -> None:
        for f in features:
            assert not f.has_holes


# ---------------------------------------------------------------------------
# Test: Schema/SchemaData typed metadata (10_schema_typed_extended_data.kml)
# ---------------------------------------------------------------------------


class TestSchemaTypedExtendedData:
    """Parse test file 10: SchemaData/SimpleData typed metadata extraction."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "10_schema_typed_extended_data.kml")

    def test_returns_two_features(self, features: list[Feature]) -> None:
        assert len(features) == 2

    def test_feature_names(self, features: list[Feature]) -> None:
        names = {f.name for f in features}
        assert "I1 - Honeycrisp Block" in names
        assert "I2 - Pink Lady Block" in names

    def test_orchard_name_from_schema_data(self, features: list[Feature]) -> None:
        """SchemaData orchard_name should be extracted."""
        for f in features:
            assert f.metadata.get("orchard_name") == "Iota Farms"

    def test_tree_variety_from_schema_data(self, features: list[Feature]) -> None:
        varieties = {f.metadata.get("tree_variety") for f in features}
        assert "Honeycrisp Apple" in varieties
        assert "Pink Lady Apple" in varieties

    def test_numeric_metadata_as_strings(self, features: list[Feature]) -> None:
        """Typed numeric values (xsd:int, xsd:float) are stored as strings."""
        honeycrisp = next(f for f in features if "Honeycrisp" in f.name)
        assert honeycrisp.metadata.get("planting_year") == "2020"
        assert honeycrisp.metadata.get("expected_yield_tonnes") == "45.5"

    def test_irrigation_type_metadata(self, features: list[Feature]) -> None:
        types = {f.metadata.get("irrigation_type") for f in features}
        assert "drip" in types
        assert "micro-sprinkler" in types

    def test_all_polygons_valid(self, features: list[Feature]) -> None:
        for f in features:
            assert f.vertex_count >= 4
            assert f.exterior_coords[0] == f.exterior_coords[-1]


# ---------------------------------------------------------------------------
# Test: Degenerate geometries (15_degenerate_geometries.kml)
# ---------------------------------------------------------------------------


class TestDegenerateGeometries:
    """Parse test file 15: self-intersecting, zero-area, duplicate vertices.

    Per PID 7.4.2 (graceful degradation), bad features are skipped with
    warnings — they should NOT crash parsing of the entire file.
    """

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(EDGE_CASES_DIR / "15_degenerate_geometries.kml")

    def test_does_not_raise(self) -> None:
        """Parsing should not raise — bad features are skipped."""
        parse_kml_file(EDGE_CASES_DIR / "15_degenerate_geometries.kml")

    def test_at_most_three_features(self, features: list[Feature]) -> None:
        """File has 3 Placemarks; some or all may be rejected."""
        assert len(features) <= 3

    def test_some_features_survive(self, features: list[Feature]) -> None:
        """At least the duplicate-vertex polygon should survive after cleanup."""
        # Self-intersecting bowtie may survive (make_valid → MultiPolygon)
        # Zero-area collinear is always rejected
        # Duplicate vertices may survive after dedup
        assert len(features) >= 1

    def test_all_surviving_features_are_closed(self, features: list[Feature]) -> None:
        for f in features:
            assert f.exterior_coords[0] == f.exterior_coords[-1]


# ---------------------------------------------------------------------------
# Test: Unclosed ring (17_unclosed_ring.kml)
# ---------------------------------------------------------------------------


class TestUnclosedRing:
    """Parse test file 17: polygon with first != last coordinate."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(EDGE_CASES_DIR / "17_unclosed_ring.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        """Unclosed ring should be auto-closed, not rejected."""
        assert len(features) == 1

    def test_ring_is_auto_closed(self, features: list[Feature]) -> None:
        coords = features[0].exterior_coords
        assert coords[0] == coords[-1]

    def test_closing_adds_one_vertex(self, features: list[Feature]) -> None:
        """Auto-closure adds one vertex: 4 original + 1 closing = 5."""
        assert features[0].vertex_count == 5


# ---------------------------------------------------------------------------
# Test: Large area plantation (06_large_area_plantation.kml)
# ---------------------------------------------------------------------------


class TestLargeAreaPlantation:
    """Parse test file 06: ~500 ha plantation in Sabah, Malaysia."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "06_large_area_plantation.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        assert len(features) == 1

    def test_polygon_valid(self, features: list[Feature]) -> None:
        assert features[0].vertex_count >= 4
        assert features[0].exterior_coords[0] == features[0].exterior_coords[-1]


# ---------------------------------------------------------------------------
# Test: Very small area garden (07_small_area_garden.kml)
# ---------------------------------------------------------------------------


class TestSmallAreaGarden:
    """Parse test file 07: ~0.1 ha garden in Riverside, CA."""

    @pytest.fixture()
    def features(self) -> list[Feature]:
        return parse_kml_file(DATA_DIR / "07_small_area_garden.kml")

    def test_returns_one_feature(self, features: list[Feature]) -> None:
        assert len(features) == 1

    def test_polygon_valid(self, features: list[Feature]) -> None:
        assert features[0].vertex_count >= 4
        assert features[0].exterior_coords[0] == features[0].exterior_coords[-1]


# ---------------------------------------------------------------------------
# Test: Partial failure — synthetic multi-feature with one bad polygon
# ---------------------------------------------------------------------------


class TestPartialFailure:
    """Verify that one invalid feature does not crash the entire parse.

    PID 7.4.2: Graceful degradation — partial failures produce partial results.
    """

    def test_good_features_survive_bad_neighbour(self, tmp_path: Path) -> None:
        """A good polygon + a zero-area polygon → only the good polygon returned."""
        kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Good Polygon</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          -120.5,46.6,0 -120.5,46.7,0 -120.4,46.7,0 -120.4,46.6,0 -120.5,46.6,0
        </coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Bad Polygon (collinear)</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          -120.5,46.6,0 -120.4,46.6,0 -120.3,46.6,0 -120.2,46.6,0 -120.5,46.6,0
        </coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "partial.kml"
        kml_file.write_text(kml_content)
        features = parse_kml_file(kml_file)
        assert len(features) == 1
        assert features[0].name == "Good Polygon"

    def test_all_bad_features_returns_empty(self, tmp_path: Path) -> None:
        """If all features are invalid, return empty list (no crash)."""
        kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Collinear A</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          -120.5,46.6,0 -120.4,46.6,0 -120.3,46.6,0 -120.5,46.6,0
        </coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Collinear B</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          -120.5,46.7,0 -120.4,46.7,0 -120.3,46.7,0 -120.5,46.7,0
        </coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
        kml_file = tmp_path / "all_bad.kml"
        kml_file.write_text(kml_content)
        features = parse_kml_file(kml_file)
        assert features == []
