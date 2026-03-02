"""Integration test: end-to-end happy-path pipeline flow.

Validates a representative local flow from KML parsing through imagery
acquisition lifecycle and metadata generation, while mocking provider and
external storage boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from kml_satellite.activities.acquire_imagery import acquire_imagery
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

    metadata = write_metadata(
        aoi,
        processing_id="integration-001",
        timestamp="2026-03-02T12:00:00+00:00",
        tenant_id="tenant-int",
    )

    assert acquisition["provider"] == "planetary_computer"
    assert acquisition["scene_id"] == "pc-scene-integration-1"
    assert download["size_bytes"] == 2048
    assert download["content_type"] == "image/tiff"
    assert metadata["metadata"]["processing_id"] == "integration-001"
    assert metadata["metadata"]["tenant_id"] == "tenant-int"
