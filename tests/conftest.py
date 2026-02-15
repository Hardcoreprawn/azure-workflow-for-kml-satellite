"""Shared pytest fixtures for the KML Satellite test suite."""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).parent
DATA_DIR = TESTS_DIR / "data"
EDGE_CASES_DIR = DATA_DIR / "edge_cases"


@pytest.fixture()
def data_dir() -> Path:
    """Return the path to the test data directory."""
    return DATA_DIR


@pytest.fixture()
def edge_cases_dir() -> Path:
    """Return the path to the edge-cases test data directory."""
    return EDGE_CASES_DIR


# ---------------------------------------------------------------------------
# Sample KML file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def single_polygon_kml(data_dir: Path) -> Path:
    """Path to a simple single-polygon KML (orchard, ~12 ha)."""
    return data_dir / "01_single_polygon_orchard.kml"


@pytest.fixture()
def multipolygon_kml(data_dir: Path) -> Path:
    """Path to a MultiGeometry KML with 3 polygon blocks."""
    return data_dir / "02_multipolygon_orchard_blocks.kml"


@pytest.fixture()
def multi_feature_kml(data_dir: Path) -> Path:
    """Path to a multi-feature KML with 4 separate Placemarks."""
    return data_dir / "03_multi_feature_vineyard.kml"


@pytest.fixture()
def polygon_with_hole_kml(data_dir: Path) -> Path:
    """Path to a polygon-with-hole KML (innerBoundaryIs)."""
    return data_dir / "04_complex_polygon_with_hole.kml"


@pytest.fixture()
def nested_folders_kml(data_dir: Path) -> Path:
    """Path to a KML with nested Folder hierarchy."""
    return data_dir / "09_folder_nested_features.kml"


# ---------------------------------------------------------------------------
# Edge-case KML file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def not_xml_kml(edge_cases_dir: Path) -> Path:
    """Path to a file that is not valid XML."""
    return edge_cases_dir / "11_malformed_not_xml.kml"


@pytest.fixture()
def empty_kml(edge_cases_dir: Path) -> Path:
    """Path to a valid KML with no features."""
    return edge_cases_dir / "13_empty_no_features.kml"


@pytest.fixture()
def point_only_kml(edge_cases_dir: Path) -> Path:
    """Path to a KML containing only Point geometry (no polygons)."""
    return edge_cases_dir / "14_point_only_no_polygons.kml"


@pytest.fixture()
def degenerate_kml(edge_cases_dir: Path) -> Path:
    """Path to a KML with degenerate geometries."""
    return edge_cases_dir / "15_degenerate_geometries.kml"


@pytest.fixture()
def invalid_coords_kml(edge_cases_dir: Path) -> Path:
    """Path to a KML with out-of-range coordinates."""
    return edge_cases_dir / "16_invalid_coordinates.kml"
