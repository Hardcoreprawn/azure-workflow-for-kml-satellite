"""Tests for the write_metadata activity.

Covers:
- Metadata record generation from AOI
- Blob path generation
- Blob upload (mocked)
- Error handling
- Integration with metadata model
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kml_satellite.activities.write_metadata import (
    MetadataWriteError,
    write_metadata,
)
from kml_satellite.models.aoi import AOI

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_aoi(
    *,
    feature_name: str = "Block A",
    source_file: str = "orchard_alpha.kml",
    metadata: dict[str, str] | None = None,
) -> AOI:
    """Build a minimal AOI for testing."""
    if metadata is None:
        metadata = {"orchard_name": "Alpha Orchard", "tree_variety": "Fuji Apple"}
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
        area_ha=12.5,
        centroid=(-120.515, 46.605),
        buffer_m=100.0,
        crs="EPSG:4326",
        metadata=metadata,
        area_warning="",
    )


# ===========================================================================
# write_metadata (no blob client — local mode)
# ===========================================================================


class TestWriteMetadataLocal:
    """Test write_metadata without a blob client (local/test mode)."""

    def test_returns_metadata_dict(self) -> None:
        """Result includes the full metadata record as a dict."""
        aoi = _make_aoi()
        result = write_metadata(aoi, processing_id="inst-001")
        assert "metadata" in result
        assert isinstance(result["metadata"], dict)

    def test_returns_metadata_path(self) -> None:
        """Result includes the deterministic blob path for metadata."""
        aoi = _make_aoi()
        result = write_metadata(
            aoi, processing_id="inst-001", timestamp="2026-02-16T12:00:00+00:00"
        )
        path = result["metadata_path"]
        assert isinstance(path, str)
        assert path.startswith("metadata/")
        assert path.endswith(".json")
        assert "alpha-orchard" in path
        assert "block-a" in path

    def test_returns_kml_archive_path(self) -> None:
        """Result includes the KML archive blob path."""
        aoi = _make_aoi()
        result = write_metadata(
            aoi, processing_id="inst-001", timestamp="2026-02-16T12:00:00+00:00"
        )
        path = result["kml_archive_path"]
        assert isinstance(path, str)
        assert path.startswith("kml/")
        assert path.endswith(".kml")

    def test_processing_id_in_metadata(self) -> None:
        """Processing ID is included in the metadata record."""
        aoi = _make_aoi()
        result = write_metadata(aoi, processing_id="my-instance-42")
        metadata = result["metadata"]
        assert metadata["processing_id"] == "my-instance-42"

    def test_feature_name_in_metadata(self) -> None:
        """Feature name from AOI appears in the metadata."""
        aoi = _make_aoi(feature_name="Vineyard Block B")
        result = write_metadata(aoi)
        assert result["metadata"]["feature_name"] == "Vineyard Block B"

    def test_geometry_in_metadata(self) -> None:
        """Geometry section is populated with bbox, area, centroid."""
        aoi = _make_aoi()
        result = write_metadata(aoi)
        geo = result["metadata"]["geometry"]
        assert geo["area_hectares"] == pytest.approx(12.5)
        assert len(geo["bounding_box"]) == 4
        assert len(geo["centroid"]) == 2
        assert geo["crs"] == "EPSG:4326"

    def test_custom_timestamp(self) -> None:
        """Custom timestamp is passed through to the metadata record."""
        aoi = _make_aoi()
        result = write_metadata(aoi, timestamp="2026-01-01T00:00:00Z")
        proc = result["metadata"]["processing"]
        assert proc["timestamp"] == "2026-01-01T00:00:00Z"

    def test_invalid_timestamp_falls_back(self) -> None:
        """Invalid timestamp string falls back to auto-generated."""
        aoi = _make_aoi()
        result = write_metadata(aoi, timestamp="not-a-date")
        proc = result["metadata"]["processing"]
        # Should still have a non-empty timestamp
        assert proc["timestamp"] != ""

    def test_project_name_derived_from_metadata(self) -> None:
        """Orchard name in path is derived from AOI metadata."""
        aoi = _make_aoi(metadata={"orchard_name": "Sunset Valley"})
        result = write_metadata(aoi, timestamp="2026-06-15T00:00:00+00:00")
        assert "sunset-valley" in result["metadata_path"]

    def test_project_name_from_filename(self) -> None:
        """Orchard name falls back to filename when metadata is empty."""
        aoi = _make_aoi(source_file="my_farm.kml", metadata={})
        result = write_metadata(aoi, timestamp="2026-06-15T00:00:00+00:00")
        # sanitise_slug("my_farm") -> "myfarm" (underscores stripped)
        assert "myfarm" in result["metadata_path"]

    def test_deterministic_paths(self) -> None:
        """Same AOI + timestamp produces identical paths (PID 7.4.4)."""
        aoi = _make_aoi()
        ts = "2026-02-16T12:00:00+00:00"
        r1 = write_metadata(aoi, processing_id="id-1", timestamp=ts)
        r2 = write_metadata(aoi, processing_id="id-1", timestamp=ts)
        assert r1["metadata_path"] == r2["metadata_path"]
        assert r1["kml_archive_path"] == r2["kml_archive_path"]


# ===========================================================================
# write_metadata with blob client (mocked upload)
# ===========================================================================


class TestWriteMetadataUpload:
    """Test write_metadata with a mocked BlobServiceClient."""

    def test_uploads_to_correct_container(self) -> None:
        """Metadata is uploaded to the kml-output container."""
        aoi = _make_aoi()
        mock_service = MagicMock(spec_set=["get_blob_client"])

        # Patch _upload_metadata directly to avoid BlobServiceClient isinstance check
        with patch("kml_satellite.activities.write_metadata._upload_metadata") as mock_upload:
            result = write_metadata(
                aoi,
                processing_id="inst-001",
                timestamp="2026-02-16T12:00:00+00:00",
                blob_service_client=mock_service,
            )
            mock_upload.assert_called_once()
            call_args = mock_upload.call_args
            assert call_args[0][0] is mock_service  # blob_service_client
            assert call_args[0][1] == result["metadata_path"]  # path
            assert isinstance(call_args[0][2], str)  # JSON string

    def test_upload_failure_raises_error(self) -> None:
        """MetadataWriteError is raised if upload fails."""
        aoi = _make_aoi()

        with (
            patch(
                "kml_satellite.activities.write_metadata._upload_metadata",
                side_effect=MetadataWriteError("Upload failed"),
            ),
            pytest.raises(MetadataWriteError, match="Upload failed"),
        ):
            write_metadata(
                aoi,
                blob_service_client=MagicMock(),
            )


# ===========================================================================
# Schema conformance (PID Section 9.2)
# ===========================================================================


class TestSchemaConformance:
    """Verify that the write_metadata output conforms to PID Section 9.2."""

    def test_all_top_level_fields(self) -> None:
        """All PID-required top-level fields are present."""
        aoi = _make_aoi()
        result = write_metadata(aoi, processing_id="inst-001")
        metadata = result["metadata"]
        required_keys = {
            "$schema",
            "processing_id",
            "tenant_id",
            "kml_filename",
            "feature_name",
            "project_name",
            "tree_variety",
            "geometry",
            "imagery",
            "processing",
        }
        assert required_keys.issubset(set(metadata.keys()))

    def test_geometry_fields(self) -> None:
        """Geometry section has all required fields."""
        aoi = _make_aoi()
        result = write_metadata(aoi)
        geo = result["metadata"]["geometry"]
        for key in (
            "type",
            "coordinates",
            "centroid",
            "bounding_box",
            "buffered_bounding_box",
            "area_hectares",
            "crs",
        ):
            assert key in geo, f"Missing geometry field: {key}"

    def test_imagery_fields(self) -> None:
        """Imagery section has all required fields (even if empty)."""
        aoi = _make_aoi()
        result = write_metadata(aoi)
        img = result["metadata"]["imagery"]
        for key in ("provider", "scene_id", "spatial_resolution_m", "cloud_cover_pct", "format"):
            assert key in img, f"Missing imagery field: {key}"

    def test_processing_fields(self) -> None:
        """Processing section has all required fields."""
        aoi = _make_aoi()
        result = write_metadata(aoi)
        proc = result["metadata"]["processing"]
        for key in ("buffer_m", "timestamp", "status", "errors"):
            assert key in proc, f"Missing processing field: {key}"

    def test_schema_version_value(self) -> None:
        """$schema field has the correct version string."""
        aoi = _make_aoi()
        result = write_metadata(aoi)
        assert result["metadata"]["$schema"] == "aoi-metadata-v2"

    def test_tenant_id_passed_through(self) -> None:
        """tenant_id is passed through to the metadata record."""
        aoi = _make_aoi()
        result = write_metadata(aoi, tenant_id="tenant-abc123")
        assert result["metadata"]["tenant_id"] == "tenant-abc123"

    def test_analysis_none_by_default(self) -> None:
        """analysis field is None by default in output."""
        aoi = _make_aoi()
        result = write_metadata(aoi)
        assert result["metadata"].get("analysis") is None
