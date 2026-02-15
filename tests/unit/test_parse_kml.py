"""Tests for the parse_kml activity function.

Covers:
- Valid single polygon extraction (01_single_polygon_orchard.kml)
- Valid extraction with no extended data (08_no_extended_data.kml)
- Malformed XML rejection (11_malformed_not_xml.kml)
- Unclosed tags rejection (12_malformed_unclosed_tags.kml)
- Invalid coordinates rejection (16_invalid_coordinates.kml)
- Coordinate validation (WGS 84 bounds)
- CRS validation (EPSG:4326)
- Metadata extraction
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from kml_satellite.activities.parse_kml import parse_kml
from kml_satellite.models.feature import (
    CoordinateValidationError,
    Feature,
    InvalidKMLError,
    MalformedXMLError,
    validate_polygon_coordinates,
    validate_wgs84_coordinate,
)


class TestValidSinglePolygon:
    """Test parsing of valid single polygon KML files."""

    def test_single_polygon_orchard_valid_extraction(
        self, single_polygon_kml: Path
    ) -> None:
        """Test extraction of valid single polygon with full metadata."""
        feature = parse_kml(single_polygon_kml)

        # Verify feature type
        assert isinstance(feature, Feature)

        # Verify geometry
        assert feature.geometry["type"] == "Polygon"
        assert "coordinates" in feature.geometry
        assert len(feature.geometry["coordinates"]) >= 1  # At least exterior ring

        # Get exterior ring
        exterior_ring = feature.geometry["coordinates"][0]
        assert len(exterior_ring) == 5  # Closed ring

        # Verify first coordinate
        first_coord = exterior_ring[0]
        assert len(first_coord) >= 2  # lon, lat (and maybe altitude)
        assert -180 <= first_coord[0] <= 180  # lon
        assert -90 <= first_coord[1] <= 90  # lat

        # Verify ring is closed
        assert exterior_ring[0] == exterior_ring[-1]

        # Verify CRS
        assert feature.crs == "EPSG:4326"

        # Verify metadata
        assert feature.properties["name"] == "Block A - Fuji Apple"
        assert "apple" in feature.properties["description"].lower()

        # Verify ExtendedData
        extended_data = feature.properties.get("extended_data", {})
        assert "orchard_name" in extended_data or "tree_variety" in extended_data

    def test_no_extended_data_valid_extraction(self, data_dir: Path) -> None:
        """Test extraction of polygon with no ExtendedData."""
        kml_path = data_dir / "08_no_extended_data.kml"
        feature = parse_kml(kml_path)

        # Verify feature type
        assert isinstance(feature, Feature)

        # Verify geometry
        assert feature.geometry["type"] == "Polygon"
        assert "coordinates" in feature.geometry

        # Verify metadata (should have name but minimal extended data)
        assert feature.properties["name"] == "Unnamed Field"
        assert feature.properties["description"] == ""

        # ExtendedData should be empty or missing
        extended_data = feature.properties.get("extended_data", {})
        assert len(extended_data) == 0

        # Verify CRS
        assert feature.crs == "EPSG:4326"

    def test_serialization_roundtrip(self, single_polygon_kml: Path) -> None:
        """Test Feature serialization and deserialization."""
        feature = parse_kml(single_polygon_kml)

        # Serialize
        feature_dict = feature.to_dict()
        assert isinstance(feature_dict, dict)
        assert "geometry" in feature_dict
        assert "properties" in feature_dict
        assert "crs" in feature_dict

        # Deserialize
        reconstructed = Feature.from_dict(feature_dict)
        assert reconstructed.geometry == feature.geometry
        assert reconstructed.properties == feature.properties
        assert reconstructed.crs == feature.crs


class TestMalformedInput:
    """Test rejection of malformed input files."""

    def test_malformed_not_xml(self, not_xml_kml: Path) -> None:
        """Test rejection of non-XML file with clear error message."""
        with pytest.raises(MalformedXMLError) as exc_info:
            parse_kml(not_xml_kml)

        # Verify error message is actionable
        error_msg = str(exc_info.value)
        assert "not valid XML" in error_msg
        assert "11_malformed_not_xml.kml" in error_msg

    def test_malformed_unclosed_tags(self, edge_cases_dir: Path) -> None:
        """Test rejection of XML with unclosed tags."""
        kml_path = edge_cases_dir / "12_malformed_unclosed_tags.kml"
        with pytest.raises(MalformedXMLError) as exc_info:
            parse_kml(kml_path)

        # Verify error message
        error_msg = str(exc_info.value)
        assert "not valid XML" in error_msg or "unclosed" in error_msg.lower()


class TestInvalidCoordinates:
    """Test rejection of invalid coordinates."""

    def test_invalid_coordinates_out_of_range(self, invalid_coords_kml: Path) -> None:
        """Test rejection of coordinates outside WGS 84 bounds."""
        with pytest.raises(CoordinateValidationError) as exc_info:
            parse_kml(invalid_coords_kml)

        # Verify error message mentions the specific invalid coordinate
        error_msg = str(exc_info.value)
        assert (
            "out of valid" in error_msg.lower()
            or "range" in error_msg.lower()
        )
        # Should mention either longitude or latitude
        assert "longitude" in error_msg.lower() or "latitude" in error_msg.lower()


class TestCoordinateValidation:
    """Test coordinate validation helpers."""

    def test_valid_wgs84_coordinate(self) -> None:
        """Test validation of valid WGS 84 coordinates."""
        # Should not raise
        validate_wgs84_coordinate(-120.5, 46.6)
        validate_wgs84_coordinate(0.0, 0.0)
        validate_wgs84_coordinate(180.0, 90.0)
        validate_wgs84_coordinate(-180.0, -90.0)

    def test_invalid_longitude_out_of_range(self) -> None:
        """Test rejection of longitude outside [-180, 180]."""
        with pytest.raises(CoordinateValidationError) as exc_info:
            validate_wgs84_coordinate(200.0, 46.6)
        assert "Longitude" in str(exc_info.value)
        assert "200" in str(exc_info.value)

        with pytest.raises(CoordinateValidationError) as exc_info:
            validate_wgs84_coordinate(-200.0, 46.6)
        assert "Longitude" in str(exc_info.value)

    def test_invalid_latitude_out_of_range(self) -> None:
        """Test rejection of latitude outside [-90, 90]."""
        with pytest.raises(CoordinateValidationError) as exc_info:
            validate_wgs84_coordinate(-120.5, 95.0)
        assert "Latitude" in str(exc_info.value)
        assert "95" in str(exc_info.value)

        with pytest.raises(CoordinateValidationError) as exc_info:
            validate_wgs84_coordinate(-120.5, -95.0)
        assert "Latitude" in str(exc_info.value)

    def test_valid_polygon_coordinates(self) -> None:
        """Test validation of valid polygon coordinates."""
        coords = [
            [-120.5, 46.6, 0],
            [-120.5, 46.7, 0],
            [-120.4, 46.7, 0],
            [-120.4, 46.6, 0],
            [-120.5, 46.6, 0],
        ]
        # Should not raise
        validate_polygon_coordinates(coords)

    def test_invalid_polygon_coordinates(self) -> None:
        """Test rejection of invalid polygon coordinates."""
        coords = [
            [-200.5, 46.6, 0],  # Invalid longitude
            [-120.5, 46.7, 0],
            [-120.4, 46.7, 0],
        ]
        with pytest.raises(CoordinateValidationError):
            validate_polygon_coordinates(coords)

    def test_coordinate_with_insufficient_dimensions(self) -> None:
        """Test rejection of coordinates with < 2 dimensions."""
        coords = [
            [-120.5],  # Only longitude
        ]
        with pytest.raises(CoordinateValidationError) as exc_info:
            validate_polygon_coordinates(coords)
        assert "at least lon, lat" in str(exc_info.value)


class TestEdgeCases:
    """Test edge cases and defensive behavior."""

    def test_empty_kml_no_features(self, empty_kml: Path) -> None:
        """Test rejection of KML with no features."""
        with pytest.raises(InvalidKMLError) as exc_info:
            parse_kml(empty_kml)

        error_msg = str(exc_info.value)
        assert "No" in error_msg and "feature" in error_msg.lower()

    def test_point_only_no_polygons(self, point_only_kml: Path) -> None:
        """Test rejection of KML with Point geometry but no Polygons."""
        with pytest.raises(InvalidKMLError) as exc_info:
            parse_kml(point_only_kml)

        error_msg = str(exc_info.value)
        # Should mention expected Polygon geometry
        assert "Polygon" in error_msg or "polygon" in error_msg.lower()

    def test_nonexistent_file(self) -> None:
        """Test handling of nonexistent file."""
        with pytest.raises((FileNotFoundError, MalformedXMLError)):
            parse_kml("/nonexistent/file.kml")


class TestMetadataExtraction:
    """Test metadata extraction from various KML structures."""

    def test_extended_data_extraction(self, single_polygon_kml: Path) -> None:
        """Test extraction of ExtendedData fields."""
        feature = parse_kml(single_polygon_kml)

        extended_data = feature.properties.get("extended_data", {})

        # Should have at least one extended data field
        assert len(extended_data) > 0

        # Check for expected fields
        assert (
            "orchard_name" in extended_data
            or "tree_variety" in extended_data
            or "planting_year" in extended_data
        )

    def test_name_and_description_extraction(self, single_polygon_kml: Path) -> None:
        """Test extraction of Placemark name and description."""
        feature = parse_kml(single_polygon_kml)

        # Should have non-empty name
        assert len(feature.properties["name"]) > 0

        # Should have non-empty description
        assert len(feature.properties["description"]) > 0


class TestParserSuccess:
    """Test that the lxml parser works correctly."""

    def test_parse_kml_success_with_metadata(self, single_polygon_kml: Path) -> None:
        """Verify parser can handle standard KML with metadata."""
        feature = parse_kml(single_polygon_kml)
        assert isinstance(feature, Feature)
        assert feature.geometry["type"] == "Polygon"

    def test_parse_kml_success_without_metadata(self, data_dir: Path) -> None:
        """Verify parser works for KML without extended data."""
        kml_path = data_dir / "08_no_extended_data.kml"
        feature = parse_kml(kml_path)
        assert isinstance(feature, Feature)
        assert feature.geometry["type"] == "Polygon"
