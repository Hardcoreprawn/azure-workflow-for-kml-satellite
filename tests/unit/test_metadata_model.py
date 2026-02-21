"""Tests for the Pydantic metadata model (PID Section 9.2).

Covers:
- AOIMetadataRecord construction from AOI dataclass
- JSON serialisation/deserialisation
- Schema validation (required fields, types)
- Orchard name extraction logic
- Edge cases: missing metadata, empty strings, special characters
"""

from __future__ import annotations

import json

import pytest

from kml_satellite.models.aoi import AOI
from kml_satellite.models.metadata import (
    SCHEMA_VERSION,
    AnalysisMetadata,
    AOIMetadataRecord,
    GeometryMetadata,
    ImageryMetadata,
    ProcessingMetadata,
    _extract_project_name,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_aoi(
    *,
    feature_name: str = "Block A",
    source_file: str = "orchard_alpha.kml",
    metadata: dict[str, str] | None = None,
    area_ha: float = 12.5,
    buffer_m: float = 100.0,
) -> AOI:
    """Build a minimal AOI for testing."""
    return AOI(
        feature_name=feature_name,
        source_file=source_file,
        feature_index=0,
        exterior_coords=[
            (-120.52, 46.60),
            (-120.52, 46.61),
            (-120.51, 46.61),
            (-120.51, 46.60),
            (-120.52, 46.60),
        ],
        interior_coords=[],
        bbox=(-120.52, 46.60, -120.51, 46.61),
        buffered_bbox=(-120.521, 46.599, -120.509, 46.611),
        area_ha=area_ha,
        centroid=(-120.515, 46.605),
        buffer_m=buffer_m,
        crs="EPSG:4326",
        metadata=metadata or {"orchard_name": "Alpha Orchard", "tree_variety": "Fuji Apple"},
        area_warning="",
    )


# ===========================================================================
# AOIMetadataRecord.from_aoi
# ===========================================================================


class TestFromAOI:
    """Test constructing metadata records from AOI dataclasses."""

    def test_basic_construction(self) -> None:
        """from_aoi produces a valid record with all required fields."""
        aoi = _make_aoi()
        record = AOIMetadataRecord.from_aoi(aoi, processing_id="inst-001")
        assert record.processing_id == "inst-001"
        assert record.feature_name == "Block A"
        assert record.kml_filename == "orchard_alpha.kml"

    def test_schema_version(self) -> None:
        """Schema version matches the constant."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        assert record.schema_version == SCHEMA_VERSION
        assert record.schema_version == "aoi-metadata-v2"

    def test_project_name_from_metadata(self) -> None:
        """Project name is extracted from metadata."""
        aoi = _make_aoi(metadata={"orchard_name": "Beta Ranch"})
        record = AOIMetadataRecord.from_aoi(aoi)
        assert record.project_name == "Beta Ranch"

    def test_tree_variety_from_metadata(self) -> None:
        """Tree variety is extracted from metadata key."""
        aoi = _make_aoi(metadata={"orchard_name": "X", "tree_variety": "Gala Apple"})
        record = AOIMetadataRecord.from_aoi(aoi)
        assert record.tree_variety == "Gala Apple"

    def test_geometry_section(self) -> None:
        """Geometry section contains correct bbox, centroid, area, CRS."""
        aoi = _make_aoi(area_ha=50.3)
        record = AOIMetadataRecord.from_aoi(aoi)
        geo = record.geometry
        assert geo.type == "Polygon"
        assert geo.area_hectares == pytest.approx(50.3)
        assert geo.crs == "EPSG:4326"
        assert len(geo.bounding_box) == 4
        assert len(geo.buffered_bounding_box) == 4
        assert len(geo.centroid) == 2

    def test_coordinates_geojson_format(self) -> None:
        """Coordinates are in GeoJSON format: [exterior_ring, *holes]."""
        aoi = _make_aoi()
        record = AOIMetadataRecord.from_aoi(aoi)
        coords = record.geometry.coordinates
        # One ring (exterior), no holes
        assert len(coords) == 1
        # 5 vertices in the exterior ring
        assert len(coords[0]) == 5
        # Each vertex is [lon, lat]
        assert len(coords[0][0]) == 2

    def test_coordinates_with_holes(self) -> None:
        """Interior rings (holes) appear as additional coordinate arrays."""
        aoi = AOI(
            feature_name="Holed",
            exterior_coords=[(-1.0, 0.0), (-1.0, 1.0), (1.0, 1.0), (1.0, 0.0), (-1.0, 0.0)],
            interior_coords=[
                [(-0.5, 0.3), (-0.5, 0.7), (-0.1, 0.7), (-0.1, 0.3), (-0.5, 0.3)],
            ],
            bbox=(-1.0, 0.0, 1.0, 1.0),
            buffered_bbox=(-1.001, -0.001, 1.001, 1.001),
            area_ha=10.0,
            centroid=(0.0, 0.5),
        )
        record = AOIMetadataRecord.from_aoi(aoi)
        assert len(record.geometry.coordinates) == 2  # exterior + 1 hole

    def test_processing_section(self) -> None:
        """Processing section has buffer_m and status."""
        aoi = _make_aoi(buffer_m=150.0)
        record = AOIMetadataRecord.from_aoi(aoi, timestamp="2026-02-16T12:00:00+00:00")
        proc = record.processing
        assert proc.buffer_m == 150.0
        assert proc.status == "metadata_written"
        assert proc.timestamp == "2026-02-16T12:00:00+00:00"

    def test_imagery_section_defaults(self) -> None:
        """Imagery section defaults to empty (populated in M-2.x)."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        img = record.imagery
        assert img.provider == ""
        assert img.scene_id == ""
        assert img.spatial_resolution_m == 0.0

    def test_rejects_non_aoi(self) -> None:
        """from_aoi raises TypeError for non-AOI input."""
        with pytest.raises(TypeError, match="Expected AOI instance"):
            AOIMetadataRecord.from_aoi({"not": "an AOI"})  # type: ignore[arg-type]

    def test_tenant_id_default(self) -> None:
        """tenant_id defaults to empty string."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        assert record.tenant_id == ""

    def test_tenant_id_from_factory(self) -> None:
        """from_aoi accepts and sets tenant_id."""
        record = AOIMetadataRecord.from_aoi(_make_aoi(), tenant_id="tenant-abc123")
        assert record.tenant_id == "tenant-abc123"

    def test_analysis_defaults_to_none(self) -> None:
        """analysis field defaults to None."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        assert record.analysis is None

    def test_analysis_populated(self) -> None:
        """analysis field can be populated with AnalysisMetadata."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        record.analysis = AnalysisMetadata(
            ndvi_blob_path="/ndvi/2026/01/alpha-orchard/block-a.tif",
            ndvi_mean=0.72,
            ndvi_min=0.18,
            ndvi_max=0.89,
            canopy_cover_pct=68.4,
            tree_count=342,
            detections_blob_path="/detections/2026/01/alpha-orchard/block-a.geojson",
        )
        assert record.analysis.ndvi_mean == pytest.approx(0.72)
        assert record.analysis.tree_count == 342

    def test_custom_timestamp(self) -> None:
        """Custom timestamp is used when provided."""
        aoi = _make_aoi()
        record = AOIMetadataRecord.from_aoi(aoi, timestamp="2026-01-01T00:00:00Z")
        assert record.processing.timestamp == "2026-01-01T00:00:00Z"

    def test_auto_timestamp_when_empty(self) -> None:
        """Timestamp is auto-generated when not provided."""
        aoi = _make_aoi()
        record = AOIMetadataRecord.from_aoi(aoi)
        assert record.processing.timestamp != ""


# ===========================================================================
# JSON Serialisation
# ===========================================================================


class TestJSONSerialisation:
    """Test JSON round-trip serialisation."""

    def test_to_json_valid(self) -> None:
        """to_json produces valid JSON."""
        record = AOIMetadataRecord.from_aoi(_make_aoi(), processing_id="test-123")
        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_schema_alias_in_json(self) -> None:
        """JSON output uses '$schema' key (not 'schema_version')."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert "$schema" in parsed
        assert parsed["$schema"] == SCHEMA_VERSION
        assert "schema_version" not in parsed

    def test_required_fields_present(self) -> None:
        """All PID-required fields are present in JSON output."""
        record = AOIMetadataRecord.from_aoi(
            _make_aoi(), processing_id="inst-001", timestamp="2026-02-16T12:00:00Z"
        )
        parsed = json.loads(record.to_json())
        # Top-level required fields
        assert "processing_id" in parsed
        assert "kml_filename" in parsed
        assert "feature_name" in parsed
        # Geometry section
        geo = parsed["geometry"]
        assert "bounding_box" in geo
        assert "area_hectares" in geo
        assert "centroid" in geo
        assert "crs" in geo
        # Processing section
        proc = parsed["processing"]
        assert "timestamp" in proc
        assert "status" in proc
        assert "buffer_m" in proc

    def test_to_dict_round_trip(self) -> None:
        """to_dict produces a dict that can reconstruct the model."""
        record = AOIMetadataRecord.from_aoi(_make_aoi(), processing_id="rt-001")
        d = record.to_dict()
        restored = AOIMetadataRecord.model_validate(d)
        assert restored.processing_id == "rt-001"
        assert restored.feature_name == record.feature_name

    def test_json_indent(self) -> None:
        """to_json respects the indent parameter."""
        record = AOIMetadataRecord.from_aoi(_make_aoi())
        compact = record.to_json(indent=0)
        pretty = record.to_json(indent=4)
        # Pretty-printed is longer due to indentation
        assert len(pretty) > len(compact)


# ===========================================================================
# Schema Validation
# ===========================================================================


class TestSchemaValidation:
    """Test Pydantic model validation on metadata records."""

    def test_geometry_metadata_defaults(self) -> None:
        """GeometryMetadata has sensible defaults."""
        geo = GeometryMetadata()
        assert geo.type == "Polygon"
        assert geo.coordinates == []
        assert geo.area_hectares == 0.0
        assert geo.crs == "EPSG:4326"

    def test_imagery_metadata_defaults(self) -> None:
        """ImageryMetadata defaults to empty/zero."""
        img = ImageryMetadata()
        assert img.provider == ""
        assert img.spatial_resolution_m == 0.0
        assert img.cloud_cover_pct == 0.0

    def test_processing_metadata_defaults(self) -> None:
        """ProcessingMetadata defaults to pending status."""
        proc = ProcessingMetadata()
        assert proc.status == "pending"
        assert proc.errors == []
        assert proc.buffer_m == 100.0

    def test_full_record_from_dict(self) -> None:
        """A full metadata record can be constructed from a raw dict."""
        raw = {
            "$schema": "aoi-metadata-v2",
            "processing_id": "test-456",
            "tenant_id": "tenant-xyz",
            "kml_filename": "test.kml",
            "feature_name": "Plot 1",
            "project_name": "Test Orchard",
            "tree_variety": "Cherry",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [-1.0, 0.0]]],
                "centroid": [0.0, 0.33],
                "bounding_box": [-1.0, 0.0, 1.0, 1.0],
                "buffered_bounding_box": [-1.01, -0.01, 1.01, 1.01],
                "area_hectares": 5.5,
                "crs": "EPSG:4326",
            },
            "imagery": {"provider": "", "scene_id": ""},
            "processing": {
                "buffer_m": 100.0,
                "timestamp": "2026-02-16T12:00:00Z",
                "status": "metadata_written",
            },
        }
        record = AOIMetadataRecord.model_validate(raw)
        assert record.processing_id == "test-456"
        assert record.tenant_id == "tenant-xyz"
        assert record.geometry.area_hectares == 5.5

    def test_v1_backward_compatibility(self) -> None:
        """v1 metadata (no tenant_id, no analysis) deserialises with defaults."""
        raw = {
            "$schema": "aoi-metadata-v1",
            "processing_id": "old-001",
            "kml_filename": "legacy.kml",
            "feature_name": "Block X",
            "project_name": "Legacy Orchard",
            "tree_variety": "Fuji",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [-1.0, 0.0]]],
                "centroid": [0.0, 0.33],
                "bounding_box": [-1.0, 0.0, 1.0, 1.0],
                "buffered_bounding_box": [-1.01, -0.01, 1.01, 1.01],
                "area_hectares": 3.0,
                "crs": "EPSG:4326",
            },
            "imagery": {"provider": ""},
            "processing": {
                "buffer_m": 100.0,
                "timestamp": "2025-12-01T00:00:00Z",
                "status": "metadata_written",
            },
        }
        record = AOIMetadataRecord.model_validate(raw)
        assert record.schema_version == "aoi-metadata-v1"
        assert record.tenant_id == ""
        assert record.analysis is None
        assert record.processing_id == "old-001"

    def test_analysis_metadata_defaults(self) -> None:
        """AnalysisMetadata fields default to empty/None."""
        analysis = AnalysisMetadata()
        assert analysis.ndvi_blob_path == ""
        assert analysis.ndvi_mean is None
        assert analysis.ndvi_min is None
        assert analysis.ndvi_max is None
        assert analysis.canopy_cover_pct is None
        assert analysis.tree_count is None
        assert analysis.detections_blob_path == ""


# ===========================================================================
# Orchard Name Extraction
# ===========================================================================


class TestProjectNameExtraction:
    """Test the _extract_project_name helper."""

    def test_from_project_name_key(self) -> None:
        """Uses 'project_name' metadata key first."""
        name = _extract_project_name({"project_name": "Alpha"}, "fallback.kml")
        assert name == "Alpha"

    def test_from_orchard_name_key(self) -> None:
        """Falls back to 'orchard_name' metadata key."""
        name = _extract_project_name({"orchard_name": "Beta Ranch"}, "fallback.kml")
        assert name == "Beta Ranch"

    def test_from_filename(self) -> None:
        """Falls back to filename stem when metadata is empty."""
        name = _extract_project_name({}, "my_orchard.kml")
        assert name == "my_orchard"

    def test_empty_metadata_and_file(self) -> None:
        """Returns 'unknown' when both metadata and filename are empty."""
        name = _extract_project_name({}, "")
        assert name == "unknown"

    def test_whitespace_only_value(self) -> None:
        """Whitespace-only metadata values are treated as empty."""
        name = _extract_project_name({"orchard_name": "  "}, "backup.kml")
        assert name == "backup"

    def test_project_name_takes_priority(self) -> None:
        """project_name is preferred over orchard_name."""
        name = _extract_project_name(
            {"orchard_name": "Second", "project_name": "First"}, "file.kml"
        )
        assert name == "First"
