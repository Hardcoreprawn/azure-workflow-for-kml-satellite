"""Unit tests for AOI processing (M-1.5).

Tests the prepare_aoi activity function: bounding box, buffered bounding box,
geodesic area in hectares, centroid, and area reasonableness checks.

Tests written BEFORE implementation (TDD  --  Hamilton standard).

References:
- Issue #6: M-1.5 AOI processing
- PID FR-1.6 (bounding box), FR-1.7 (area in hectares), FR-1.8 (centroid)
- PID FR-2.1 (buffered bounding box, configurable 50-200 m)
- PID FR-2.3 (log AOI metadata)
- PID 7.4.3 (Defensive Geometry  --  buffer arithmetic, area reasonableness)
- PID 7.4.5 (Explicit units  --  hectares, metres)
- PID 7.4.7 (Test pyramid  --  unit tier)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from kml_satellite.activities.prepare_aoi import (
    AOIError,
    compute_bbox,
    compute_buffered_bbox,
    compute_centroid,
    compute_geodesic_area_ha,
    prepare_aoi,
)
from kml_satellite.models.aoi import AOI
from kml_satellite.models.feature import Feature

# ---------------------------------------------------------------------------
# Test data paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EDGE_CASES_DIR = DATA_DIR / "edge_cases"

# ---------------------------------------------------------------------------
# Reference polygons (from test KML files)
# ---------------------------------------------------------------------------

# File 01: Yakima Valley orchard  --  roughly rectangular, ~100 ha (0.013 x 0.009 deg at 46.6N)
YAKIMA_EXTERIOR = [
    (-120.5210, 46.6040),
    (-120.5210, 46.6130),
    (-120.5080, 46.6130),
    (-120.5080, 46.6040),
    (-120.5210, 46.6040),
]

# File 06: Sabah plantation  --  large rectangular, ~500 ha per description
SABAH_EXTERIOR = [
    (117.8500, 5.3000),
    (117.8500, 5.3450),
    (117.9000, 5.3450),
    (117.9000, 5.3000),
    (117.8500, 5.3000),
]

# File 07: Riverside garden  --  tiny rectangular, ~0.1 ha per description
RIVERSIDE_EXTERIOR = [
    (-117.3960, 33.9535),
    (-117.3960, 33.9539),
    (-117.3955, 33.9539),
    (-117.3955, 33.9535),
    (-117.3960, 33.9535),
]

# File 04: Bundaberg orchard with hole
BUNDABERG_EXTERIOR = [
    (152.3480, -24.8700),
    (152.3480, -24.8610),
    (152.3600, -24.8610),
    (152.3600, -24.8700),
    (152.3480, -24.8700),
]
BUNDABERG_HOLE = [
    (152.3520, -24.8670),
    (152.3520, -24.8645),
    (152.3555, -24.8645),
    (152.3555, -24.8670),
    (152.3520, -24.8670),
]


def _make_feature(
    exterior: list[tuple[float, float]],
    interior: list[list[tuple[float, float]]] | None = None,
    name: str = "Test Feature",
    metadata: dict[str, str] | None = None,
    source_file: str = "test.kml",
) -> Feature:
    """Helper to create a Feature for testing."""
    return Feature(
        name=name,
        exterior_coords=exterior,
        interior_coords=interior or [],
        metadata=metadata or {},
        source_file=source_file,
    )


# ===========================================================================
# Bounding Box (FR-1.6)
# ===========================================================================


class TestBoundingBox:
    """Test tight bounding box computation from polygon coordinates."""

    def test_rectangle_bbox(self) -> None:
        """Simple rectangle produces correct (min_lon, min_lat, max_lon, max_lat)."""
        bbox = compute_bbox(YAKIMA_EXTERIOR)
        min_lon, min_lat, max_lon, max_lat = bbox
        assert min_lon == pytest.approx(-120.5210)
        assert min_lat == pytest.approx(46.6040)
        assert max_lon == pytest.approx(-120.5080)
        assert max_lat == pytest.approx(46.6130)

    def test_bbox_format_four_elements(self) -> None:
        """Bounding box is always a 4-tuple."""
        bbox = compute_bbox(YAKIMA_EXTERIOR)
        assert len(bbox) == 4

    def test_min_less_than_max(self) -> None:
        """min_lon < max_lon and min_lat < max_lat for every valid polygon."""
        bbox = compute_bbox(YAKIMA_EXTERIOR)
        assert bbox[0] < bbox[2]
        assert bbox[1] < bbox[3]

    def test_southern_hemisphere(self) -> None:
        """Bounding box handles negative latitudes (Bundaberg, Australia)."""
        bbox = compute_bbox(BUNDABERG_EXTERIOR)
        assert bbox[1] < 0  # min_lat is negative
        assert bbox[3] < 0  # max_lat is negative
        assert bbox[1] < bbox[3]  # still min < max

    def test_empty_coords_raises(self) -> None:
        """Empty coordinate list is rejected."""
        with pytest.raises(AOIError, match=r"[Ee]mpty|[Nn]o coord"):
            compute_bbox([])

    def test_single_point_raises(self) -> None:
        """A single point is not a polygon."""
        with pytest.raises(AOIError, match=r"[Ii]nsufficient|[Nn]eed"):
            compute_bbox([(-120.5, 46.6)])


# ===========================================================================
# Geodesic Area (FR-1.7)
# ===========================================================================


class TestGeodesicArea:
    """Test geodesic area computation in hectares.

    Uses pyproj.Geod for WGS 84 ellipsoidal area. All values in hectares
    (PID 7.4.5: explicit units).
    """

    def test_yakima_orchard_area(self) -> None:
        """File 01: Yakima Valley rectangle  --  area is reasonable for an orchard."""
        area_ha = compute_geodesic_area_ha(YAKIMA_EXTERIOR)
        # ~99 ha based on approximate manual calc (0.013° x 0.009° at 46.6°N)
        assert 90 < area_ha < 110, f"Expected ~100 ha, got {area_ha:.1f}"

    def test_sabah_plantation_area(self) -> None:
        """File 06: Sabah plantation rectangle  --  large area."""
        area_ha = compute_geodesic_area_ha(SABAH_EXTERIOR)
        # ~2770 ha based on 0.05° x 0.045° near equator
        assert 2700 < area_ha < 2850, f"Expected ~2770 ha, got {area_ha:.1f}"

    def test_riverside_garden_area(self) -> None:
        """File 07: Riverside garden  --  tiny area."""
        area_ha = compute_geodesic_area_ha(RIVERSIDE_EXTERIOR)
        # ~0.2 ha (46m x 44m)
        assert 0.1 < area_ha < 0.3, f"Expected ~0.2 ha, got {area_ha:.2f}"

    def test_area_is_positive(self) -> None:
        """Area is always a positive number regardless of winding order."""
        area_ha = compute_geodesic_area_ha(YAKIMA_EXTERIOR)
        assert area_ha > 0

    def test_reversed_winding_same_area(self) -> None:
        """Clockwise vs counter-clockwise gives the same area (absolute value)."""
        area_cw = compute_geodesic_area_ha(YAKIMA_EXTERIOR)
        area_ccw = compute_geodesic_area_ha(list(reversed(YAKIMA_EXTERIOR)))
        assert area_cw == pytest.approx(area_ccw, rel=1e-6)

    def test_area_with_hole_is_smaller(self) -> None:
        """Polygon with hole has less area than the same polygon without hole."""
        area_no_hole = compute_geodesic_area_ha(BUNDABERG_EXTERIOR)
        area_with_hole = compute_geodesic_area_ha(
            BUNDABERG_EXTERIOR, interior_rings=[BUNDABERG_HOLE]
        )
        assert area_with_hole < area_no_hole

    def test_hole_area_subtracted_correctly(self) -> None:
        """The hole area should be subtracted: outer - inner = net."""
        area_outer = compute_geodesic_area_ha(BUNDABERG_EXTERIOR)
        area_hole = compute_geodesic_area_ha(BUNDABERG_HOLE)
        area_net = compute_geodesic_area_ha(BUNDABERG_EXTERIOR, interior_rings=[BUNDABERG_HOLE])
        assert area_net == pytest.approx(area_outer - area_hole, rel=0.01)

    def test_empty_coords_raises(self) -> None:
        with pytest.raises(AOIError):
            compute_geodesic_area_ha([])


# ===========================================================================
# Centroid (FR-1.8)
# ===========================================================================


class TestCentroid:
    """Test centroid computation."""

    def test_rectangle_centroid(self) -> None:
        """Centroid of a rectangle is at its geometric centre."""
        lon, lat = compute_centroid(YAKIMA_EXTERIOR)
        assert lon == pytest.approx(-120.5145, abs=0.001)
        assert lat == pytest.approx(46.6085, abs=0.001)

    def test_centroid_inside_bbox(self) -> None:
        """Centroid must fall within the bounding box."""
        lon, lat = compute_centroid(YAKIMA_EXTERIOR)
        bbox = compute_bbox(YAKIMA_EXTERIOR)
        assert bbox[0] <= lon <= bbox[2]
        assert bbox[1] <= lat <= bbox[3]

    def test_centroid_southern_hemisphere(self) -> None:
        """Centroid works for southern hemisphere polygons."""
        lon, lat = compute_centroid(BUNDABERG_EXTERIOR)
        assert lat < 0
        assert 152 < lon < 153

    def test_empty_coords_raises(self) -> None:
        with pytest.raises(AOIError):
            compute_centroid([])


# ===========================================================================
# Buffered Bounding Box (FR-2.1)
# ===========================================================================


class TestBufferedBbox:
    """Test buffered bounding box computation.

    PID 7.4.3: Buffer arithmetic must use metric projection, not degrees.
    FR-2.1: Configurable margin  --  default 100 m, range 50-200 m.
    """

    def test_default_buffer_100m(self) -> None:
        """Default 100 m buffer expands the bbox by ~100 m on each side."""
        bbox = compute_bbox(YAKIMA_EXTERIOR)
        buffered = compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=100.0)

        # Buffered bbox must be larger than original
        assert buffered[0] < bbox[0]  # min_lon smaller
        assert buffered[1] < bbox[1]  # min_lat smaller
        assert buffered[2] > bbox[2]  # max_lon larger
        assert buffered[3] > bbox[3]  # max_lat larger

    def test_buffer_expansion_approximately_correct(self) -> None:
        """100 m buffer should expand lat by ~0.0009° and lon by ~0.0013° at 46.6°N.

        We check the expansion is in the right ballpark (50-200 m equivalent).
        """
        bbox = compute_bbox(YAKIMA_EXTERIOR)
        buffered = compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=100.0)

        # Latitude: 100 m ≈ 0.0009° (111,320 m per degree)
        lat_expansion_south = bbox[1] - buffered[1]
        lat_expansion_north = buffered[3] - bbox[3]
        assert 0.0005 < lat_expansion_south < 0.002
        assert 0.0005 < lat_expansion_north < 0.002

    def test_custom_buffer_50m(self) -> None:
        """50 m buffer is smaller than 100 m buffer."""
        buf_50 = compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=50.0)
        buf_100 = compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=100.0)
        # 50 m has tighter (larger) min_lon than 100 m
        assert buf_50[0] > buf_100[0]

    def test_custom_buffer_200m(self) -> None:
        """200 m buffer is larger than 100 m buffer."""
        buf_200 = compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=200.0)
        buf_100 = compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=100.0)
        assert buf_200[0] < buf_100[0]

    def test_buffer_below_minimum_raises(self) -> None:
        """Buffer < 50 m is rejected (FR-2.1: range 50-200 m)."""
        with pytest.raises(AOIError, match=r"[Bb]uffer.*range|50"):
            compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=30.0)

    def test_buffer_above_maximum_raises(self) -> None:
        """Buffer > 200 m is rejected (FR-2.1: range 50-200 m)."""
        with pytest.raises(AOIError, match=r"[Bb]uffer.*range|200"):
            compute_buffered_bbox(YAKIMA_EXTERIOR, buffer_m=300.0)

    def test_near_equator_buffer(self) -> None:
        """Buffer near equator (Sabah, 5.3°N)  --  metric projection still works."""
        bbox = compute_bbox(SABAH_EXTERIOR)
        buffered = compute_buffered_bbox(SABAH_EXTERIOR, buffer_m=100.0)
        assert buffered[0] < bbox[0]
        assert buffered[3] > bbox[3]

    def test_southern_hemisphere_buffer(self) -> None:
        """Buffer in southern hemisphere (Bundaberg, -24.8°)."""
        bbox = compute_bbox(BUNDABERG_EXTERIOR)
        buffered = compute_buffered_bbox(BUNDABERG_EXTERIOR, buffer_m=100.0)
        assert buffered[0] < bbox[0]
        assert buffered[1] < bbox[1]


# ===========================================================================
# Area Reasonableness Check (PID 7.4.3)
# ===========================================================================


class TestAreaReasonablenessCheck:
    """Test that unreasonably large areas are flagged.

    PID 7.4.3: "A 500,000-hectare orchard is almost certainly a data error."
    """

    def test_normal_area_no_warning(self) -> None:
        """A ~100 ha orchard should NOT produce a warning."""
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert aoi.area_warning == ""

    def test_large_area_produces_warning(self) -> None:
        """An area exceeding the threshold produces a warning string."""
        feature = _make_feature(SABAH_EXTERIOR)
        aoi = prepare_aoi(feature, area_threshold_ha=1000.0)
        assert aoi.area_warning != ""
        assert "1000" in aoi.area_warning or "exceed" in aoi.area_warning.lower()

    def test_custom_threshold(self) -> None:
        """Custom threshold of 50 ha flags the ~100 ha Yakima polygon."""
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature, area_threshold_ha=50.0)
        assert aoi.area_warning != ""

    def test_default_threshold_10000_ha(self) -> None:
        """Default threshold is 10,000 ha (per Issue #6 spec)."""
        feature = _make_feature(SABAH_EXTERIOR)
        # ~2770 ha  --  under 10,000 → no warning
        aoi = prepare_aoi(feature)
        assert aoi.area_warning == ""


# ===========================================================================
# Full prepare_aoi Function
# ===========================================================================


class TestPrepareAOI:
    """Test the complete prepare_aoi function end to end."""

    def test_returns_aoi_instance(self) -> None:
        """prepare_aoi returns an AOI dataclass instance."""
        feature = _make_feature(YAKIMA_EXTERIOR, name="Block A")
        aoi = prepare_aoi(feature)
        assert isinstance(aoi, AOI)

    def test_feature_name_preserved(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR, name="Block A - Fuji Apple")
        aoi = prepare_aoi(feature)
        assert aoi.feature_name == "Block A - Fuji Apple"

    def test_source_file_preserved(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR, source_file="orchard.kml")
        aoi = prepare_aoi(feature)
        assert aoi.source_file == "orchard.kml"

    def test_metadata_preserved(self) -> None:
        feature = _make_feature(
            YAKIMA_EXTERIOR, metadata={"orchard_name": "Alpha", "tree_variety": "Fuji"}
        )
        aoi = prepare_aoi(feature)
        assert aoi.metadata["orchard_name"] == "Alpha"
        assert aoi.metadata["tree_variety"] == "Fuji"

    def test_crs_is_wgs84(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert aoi.crs == "EPSG:4326"

    def test_bbox_populated(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert len(aoi.bbox) == 4
        assert aoi.bbox[0] < aoi.bbox[2]

    def test_buffered_bbox_larger_than_bbox(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert aoi.buffered_bbox[0] < aoi.bbox[0]
        assert aoi.buffered_bbox[1] < aoi.bbox[1]
        assert aoi.buffered_bbox[2] > aoi.bbox[2]
        assert aoi.buffered_bbox[3] > aoi.bbox[3]

    def test_area_ha_positive(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert aoi.area_ha > 0

    def test_centroid_within_bbox(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert aoi.bbox[0] <= aoi.centroid[0] <= aoi.bbox[2]
        assert aoi.bbox[1] <= aoi.centroid[1] <= aoi.bbox[3]

    def test_custom_buffer_m(self) -> None:
        """Buffer distance is configurable."""
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature, buffer_m=150.0)
        assert aoi.buffer_m == 150.0

    def test_default_buffer_is_100m(self) -> None:
        feature = _make_feature(YAKIMA_EXTERIOR)
        aoi = prepare_aoi(feature)
        assert aoi.buffer_m == 100.0

    def test_polygon_with_hole(self) -> None:
        """Polygon with inner boundary is processed; area accounts for hole."""
        feature = _make_feature(
            BUNDABERG_EXTERIOR,
            interior=[BUNDABERG_HOLE],
            name="Block D1",
        )
        aoi = prepare_aoi(feature)
        assert aoi.area_ha > 0
        # Area with hole should be less than without
        feature_no_hole = _make_feature(BUNDABERG_EXTERIOR, name="No hole")
        aoi_no_hole = prepare_aoi(feature_no_hole)
        assert aoi.area_ha < aoi_no_hole.area_ha

    def test_tiny_polygon_still_works(self) -> None:
        """Even a very small polygon (~0.2 ha) is processed successfully."""
        feature = _make_feature(RIVERSIDE_EXTERIOR, name="Garden")
        aoi = prepare_aoi(feature)
        assert aoi.area_ha > 0
        assert aoi.area_ha < 1.0

    def test_empty_exterior_raises(self) -> None:
        """Feature with no exterior coordinates is rejected."""
        feature = _make_feature([], name="Empty")
        with pytest.raises(AOIError):
            prepare_aoi(feature)

    def test_logging_of_aoi_metadata(self, caplog: pytest.LogCaptureFixture) -> None:
        """FR-2.3: AOI metadata is logged (area, buffer, bbox, centroid)."""
        feature = _make_feature(YAKIMA_EXTERIOR, name="Block A")
        with caplog.at_level(logging.INFO, logger="kml_satellite.activities.prepare_aoi"):
            prepare_aoi(feature)
        log_text = caplog.text.lower()
        assert "area" in log_text
        assert "buffer" in log_text


# ===========================================================================
# AOI Model Serialisation
# ===========================================================================


class TestAOISerialisation:
    """Test AOI.to_dict() / AOI.from_dict() round-trip."""

    @pytest.fixture()
    def sample_aoi(self) -> AOI:
        feature = _make_feature(
            YAKIMA_EXTERIOR,
            name="Block A",
            metadata={"orchard_name": "Alpha"},
            source_file="test.kml",
        )
        return prepare_aoi(feature)

    def test_to_dict_returns_dict(self, sample_aoi: AOI) -> None:
        d = sample_aoi.to_dict()
        assert isinstance(d, dict)

    def test_round_trip(self, sample_aoi: AOI) -> None:
        d = sample_aoi.to_dict()
        restored = AOI.from_dict(d)
        assert restored.feature_name == sample_aoi.feature_name
        assert restored.area_ha == pytest.approx(sample_aoi.area_ha)
        assert restored.buffer_m == sample_aoi.buffer_m
        assert restored.crs == sample_aoi.crs

    def test_bbox_round_trip(self, sample_aoi: AOI) -> None:
        d = sample_aoi.to_dict()
        restored = AOI.from_dict(d)
        for orig, rest in zip(sample_aoi.bbox, restored.bbox, strict=True):
            assert rest == pytest.approx(orig)

    def test_centroid_round_trip(self, sample_aoi: AOI) -> None:
        d = sample_aoi.to_dict()
        restored = AOI.from_dict(d)
        assert restored.centroid[0] == pytest.approx(sample_aoi.centroid[0])
        assert restored.centroid[1] == pytest.approx(sample_aoi.centroid[1])

    def test_metadata_round_trip(self, sample_aoi: AOI) -> None:
        d = sample_aoi.to_dict()
        restored = AOI.from_dict(d)
        assert restored.metadata == sample_aoi.metadata

    def test_from_dict_missing_fields_defaults(self) -> None:
        """Missing fields get sensible defaults  --  no crash."""
        aoi = AOI.from_dict({"feature_name": "Minimal"})
        assert aoi.feature_name == "Minimal"
        assert aoi.area_ha == 0.0
        assert aoi.crs == "EPSG:4326"

    def test_from_dict_type_error_on_bad_bbox(self) -> None:
        with pytest.raises(TypeError, match="bbox"):
            AOI.from_dict({"bbox": "not_a_list"})


# ===========================================================================
# Integration: parse KML → prepare AOI
# ===========================================================================


class TestParseToAOIIntegration:
    """End-to-end: parse a real KML file, then prepare AOI for each feature."""

    def test_single_polygon_kml(self) -> None:
        """File 01: parse → prepare_aoi → valid AOI."""
        from kml_satellite.activities.parse_kml import parse_kml_file

        features = parse_kml_file(DATA_DIR / "01_single_polygon_orchard.kml")
        assert len(features) == 1
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 0
        assert aoi.feature_name == "Block A - Fuji Apple"
        assert aoi.metadata.get("orchard_name") == "Alpha Orchard"

    def test_multi_feature_kml(self) -> None:
        """File 03: parse → prepare_aoi for each feature → 4 valid AOIs."""
        from kml_satellite.activities.parse_kml import parse_kml_file

        features = parse_kml_file(DATA_DIR / "03_multi_feature_vineyard.kml")
        assert len(features) == 4
        aois = [prepare_aoi(f) for f in features]
        for aoi in aois:
            assert aoi.area_ha > 0
            assert len(aoi.bbox) == 4
            assert len(aoi.centroid) == 2

    def test_polygon_with_hole_kml(self) -> None:
        """File 04: parse → prepare_aoi → AOI with hole handled."""
        from kml_satellite.activities.parse_kml import parse_kml_file

        features = parse_kml_file(DATA_DIR / "04_complex_polygon_with_hole.kml")
        assert len(features) == 1
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 0
        # The feature has a hole  --  area should account for it
        assert len(features[0].interior_coords) > 0

    def test_large_plantation_kml(self) -> None:
        """File 06: parse → prepare_aoi for a large polygon."""
        from kml_satellite.activities.parse_kml import parse_kml_file

        features = parse_kml_file(DATA_DIR / "06_large_area_plantation.kml")
        aoi = prepare_aoi(features[0])
        assert aoi.area_ha > 100  # large polygon

    def test_small_garden_kml(self) -> None:
        """File 07: parse → prepare_aoi for a tiny polygon."""
        from kml_satellite.activities.parse_kml import parse_kml_file

        features = parse_kml_file(DATA_DIR / "07_small_area_garden.kml")
        aoi = prepare_aoi(features[0])
        assert 0 < aoi.area_ha < 1.0
