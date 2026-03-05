"""Integration test: end-to-end happy-path pipeline flow.

Validates a representative local flow from KML parsing through imagery
acquisition lifecycle and metadata generation, while mocking provider and
external storage boundaries.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import pytest

from kml_satellite.activities.acquire_imagery import ImageryAcquisitionError, acquire_imagery
from kml_satellite.activities.download_imagery import download_imagery
from kml_satellite.activities.parse_kml import parse_kml_file
from kml_satellite.activities.poll_order import poll_order
from kml_satellite.activities.prepare_aoi import prepare_aoi
from kml_satellite.activities.write_metadata import write_metadata
from kml_satellite.models.imagery import (
    BlobReference,
    OrderId,
    OrderState,
    OrderStatus,
    SearchResult,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeProvider:
    """Deterministic fake provider for integration-path validation."""

    def search(self, aoi, filters=None):
        _ = aoi
        _ = filters
        return [
            SearchResult(
                scene_id="pc-scene-integration-1",
                provider="planetary_computer",
                acquisition_date=datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
                cloud_cover_pct=7.5,
                spatial_resolution_m=0.6,
                asset_url="https://example.test/scene.tif",
            )
        ]

    def order(self, scene_id: str) -> OrderId:
        return OrderId(
            provider="planetary_computer",
            order_id=f"pc-{scene_id}",
            scene_id=scene_id,
        )

    def poll(self, order_id: str) -> OrderStatus:
        return OrderStatus(
            order_id=order_id,
            state=OrderState.READY,
            message="ready",
            progress_pct=100.0,
        )

    def download(self, order_id: str) -> BlobReference:
        return BlobReference(
            container="kml-output",
            blob_path=f"imagery/raw/{order_id}.tif",
            size_bytes=2048,
            content_type="image/tiff",
        )


class _NoResultProvider:
    """Fake provider that returns no search results."""

    def search(self, aoi, filters=None):
        _ = aoi
        _ = filters
        return []


@pytest.mark.integration
def test_pipeline_e2e_happy_path(single_polygon_kml: Path) -> None:
    """Runs parse → AOI → acquire → poll → download → metadata flow."""
    features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
    assert len(features) >= 1

    aoi = prepare_aoi(features[0])
    fake_provider = _FakeProvider()

    with (
        patch("kml_satellite.activities.acquire_imagery.get_provider", return_value=fake_provider),
        patch("kml_satellite.activities.poll_order.get_provider", return_value=fake_provider),
        patch(
            "kml_satellite.activities.download_imagery.get_provider", return_value=fake_provider
        ),
        patch(
            "kml_satellite.activities.download_imagery._validate_raster_content", return_value=None
        ),
    ):
        acquisition = acquire_imagery(aoi.to_dict(), provider_name="planetary_computer")
        poll = poll_order(
            {
                "order_id": acquisition["order_id"],
                "provider": acquisition["provider"],
            }
        )

        assert poll["state"] == "ready"
        assert poll["is_terminal"] is True

        download = download_imagery(
            {
                "order_id": acquisition["order_id"],
                "scene_id": acquisition["scene_id"],
                "provider": acquisition["provider"],
                "aoi_feature_name": acquisition["aoi_feature_name"],
                "state": "ready",
            },
            project_name="integration-test",
            timestamp="2026-03-02T12:00:00+00:00",
            max_retries=1,
        )

    metadata_result = write_metadata(
        aoi,
        processing_id="integration-001",
        timestamp="2026-03-02T12:00:00+00:00",
        tenant_id="tenant-int",
    )
    metadata = cast("dict[str, Any]", metadata_result["metadata"])

    assert acquisition["provider"] == "planetary_computer"
    assert acquisition["scene_id"] == "pc-scene-integration-1"
    assert download["size_bytes"] == 2048
    assert download["content_type"] == "image/tiff"
    assert metadata["processing_id"] == "integration-001"
    assert metadata["tenant_id"] == "tenant-int"


@pytest.mark.integration
@pytest.mark.parametrize("concurrent_count", [5, 20])
def test_concurrent_upload_stress(single_polygon_kml: Path, concurrent_count: int) -> None:
    """Stress test: process concurrent_count KML uploads simultaneously.

    Validates that the pipeline handles ≥20 concurrent uploads without
    degradation, race conditions, or data loss (NFR-2).

    Args:
        single_polygon_kml: Path to a sample KML file.
        concurrent_count: Number of concurrent pipelines to spawn.

    Asserts:
        All concurrent pipelines complete successfully.
        Each produces valid acquisition, poll, download, and metadata records.
        No race conditions or shared-state corruption.
    """

    def process_single_pipeline(index: int) -> dict:
        """Process a single KML through the full pipeline."""
        features = parse_kml_file(single_polygon_kml, source_filename=f"concurrent-{index}.kml")
        assert len(features) >= 1, f"Pipeline {index}: No features parsed"

        aoi = prepare_aoi(features[0])
        fake_provider = _FakeProvider()

        with (
            patch(
                "kml_satellite.activities.acquire_imagery.get_provider",
                return_value=fake_provider,
            ),
            patch(
                "kml_satellite.activities.poll_order.get_provider",
                return_value=fake_provider,
            ),
            patch(
                "kml_satellite.activities.download_imagery.get_provider",
                return_value=fake_provider,
            ),
            patch(
                "kml_satellite.activities.download_imagery._validate_raster_content",
                return_value=None,
            ),
        ):
            acquisition = acquire_imagery(aoi.to_dict(), provider_name="planetary_computer")
            poll = poll_order(
                {
                    "order_id": acquisition["order_id"],
                    "provider": acquisition["provider"],
                }
            )

            assert poll["state"] == "ready", f"Pipeline {index}: Poll state not ready"
            assert poll["is_terminal"] is True, f"Pipeline {index}: Poll not terminal"

            download = download_imagery(
                {
                    "order_id": acquisition["order_id"],
                    "scene_id": acquisition["scene_id"],
                    "provider": acquisition["provider"],
                    "aoi_feature_name": acquisition["aoi_feature_name"],
                    "state": "ready",
                },
                project_name="stress-test",
                timestamp="2026-03-02T12:00:00+00:00",
                max_retries=1,
            )

        metadata = write_metadata(
            aoi,
            processing_id=f"stress-{index}",
            timestamp="2026-03-02T12:00:00+00:00",
            tenant_id=f"tenant-stress-{index}",
        )

        return {
            "index": index,
            "acquisition": acquisition,
            "poll": poll,
            "download": download,
            "metadata": metadata,
        }

    # Run concurrent pipelines using ThreadPoolExecutor
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_count) as executor:
        futures = [executor.submit(process_single_pipeline, i) for i in range(concurrent_count)]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()  # Raises exception if pipeline failed
            results.append(result)

    # Validate all pipelines completed successfully
    assert len(results) == concurrent_count, (
        f"Expected {concurrent_count} results, got {len(results)}"
    )

    # Verify no data corruption or conflicts across concurrent pipelines
    processing_ids = set()
    tenant_ids = set()
    for result in results:
        assert result["acquisition"]["provider"] == "planetary_computer"
        assert result["acquisition"]["scene_id"] == "pc-scene-integration-1"
        assert result["download"]["size_bytes"] == 2048
        assert result["metadata"]["metadata"]["processing_id"]
        assert result["metadata"]["metadata"]["tenant_id"]

        # Verify uniqueness (no race condition corruption)
        processing_ids.add(result["metadata"]["metadata"]["processing_id"])
        tenant_ids.add(result["metadata"]["metadata"]["tenant_id"])

    assert len(processing_ids) == concurrent_count, (
        "Processing IDs not unique — possible race condition"
    )
    assert len(tenant_ids) == concurrent_count, "Tenant IDs not unique — possible race condition"


@pytest.mark.integration
def test_pipeline_integration_no_imagery_still_writes_metadata(single_polygon_kml: Path) -> None:
    """No search results should fail acquisition, while metadata remains schema-valid."""
    features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
    assert len(features) >= 1

    aoi = prepare_aoi(features[0])

    with (
        patch(
            "kml_satellite.activities.acquire_imagery.get_provider",
            return_value=_NoResultProvider(),
        ),
        pytest.raises(ImageryAcquisitionError) as exc,
    ):
        acquire_imagery(aoi.to_dict(), provider_name="planetary_computer")

    assert "No imagery found" in str(exc.value)
    metadata_result = write_metadata(aoi, processing_id="integration-no-imagery")
    metadata = cast("dict[str, Any]", metadata_result["metadata"])
    assert metadata["processing"]["status"] == "metadata_written"
    assert metadata["imagery"]["scene_id"] == ""
    assert metadata["imagery"]["provider"] == ""


@pytest.mark.integration
def test_exported_kml_metadata_contract_shape() -> None:
    """Exported UK KML should parse and produce metadata with stable schema keys."""
    from pathlib import Path

    sample = Path("tests/data/uk-newton-linford-bradgate-country-park.kml")
    features = parse_kml_file(sample, source_filename=sample.name)
    assert len(features) >= 1

    aoi = prepare_aoi(features[0])
    result = write_metadata(aoi, processing_id="integration-uk-kml")
    metadata = cast("dict[str, Any]", result["metadata"])

    assert metadata["$schema"] == "aoi-metadata-v2"
    assert metadata["kml_filename"] == sample.name
    assert "geometry" in metadata and "imagery" in metadata and "processing" in metadata
    assert len(metadata["geometry"]["coordinates"]) >= 1
    assert len(metadata["geometry"]["bounding_box"]) == 4
    assert metadata["processing"]["status"] == "metadata_written"
