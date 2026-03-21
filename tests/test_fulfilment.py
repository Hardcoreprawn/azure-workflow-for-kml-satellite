"""Tests for Phase 3 — fulfilment logic (§3.3).

Covers ``download_imagery`` and ``post_process_imagery``
using a stub provider and mock ``BlobStorageClient``.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from treesight.models.aoi import AOI
from treesight.providers.base import (
    BlobReference,
    ImageryProvider,
    OrderStatus,
    ProviderConfig,
)

# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------


def _make_geotiff_bytes(
    width: int = 16,
    height: int = 16,
    crs: str = "EPSG:32637",
    bounds: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Generate a minimal in-memory GeoTIFF for testing.

    Default bounds cover the test AOI (~36.8E, 1.3S) projected into UTM 37N.
    """
    if bounds is None:
        # Transform the test AOI buffered_bbox [36.79, -1.32, 36.82, -1.29]
        # into EPSG:32637 (UTM zone 37N).
        from pyproj import Transformer

        t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x_min, y_min = t.transform(36.79, -1.32)
        x_max, y_max = t.transform(36.82, -1.29)
        bounds = (x_min, y_min, x_max, y_max)

    transform = from_bounds(*bounds, width, height)
    data = np.ones((3, height, width), dtype=np.uint8) * 128
    buf = io.BytesIO()
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="uint8",
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data)
    return buf.getvalue()


class _StubProvider(ImageryProvider):
    """Minimal provider returning canned download results."""

    def __init__(
        self,
        config: ProviderConfig | None = None,
        *,
        download_ref: BlobReference | None = None,
        download_error: Exception | None = None,
    ) -> None:
        super().__init__(config)
        self._download_ref = download_ref or BlobReference(
            container="kml-output",
            blob_path="imagery/raw/stub/order-1.tif",
            size_bytes=1024,
            content_type="image/tiff",
        )
        self._download_error = download_error

    @property
    def name(self) -> str:
        return "stub"

    def search(self, aoi: AOI, filters: Any) -> list[Any]:
        return []

    def order(self, scene_id: str) -> str:
        return f"stub-order-{scene_id}"

    def poll(self, order_id: str) -> OrderStatus:
        return OrderStatus(state="ready", is_terminal=True)

    def download(self, order_id: str) -> BlobReference:
        if self._download_error:
            raise self._download_error
        return self._download_ref


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def aoi() -> AOI:
    """Minimal AOI for fulfilment tests."""
    return AOI(
        feature_name="Block A",
        source_file="test.kml",
        feature_index=0,
        exterior_coords=[[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]],
        bbox=[36.8, -1.31, 36.81, -1.3],
        buffered_bbox=[36.79, -1.32, 36.82, -1.29],
        area_ha=12.0,
        centroid=[36.805, -1.305],
        buffer_m=100.0,
        crs="EPSG:4326",
    )


def _ready_outcome(
    order_id: str = "order-1",
    scene_id: str = "SCENE-001",
    aoi_name: str = "Block A",
) -> dict[str, Any]:
    """Simulate an acquisition outcome dict for a ready order."""
    return {
        "order_id": order_id,
        "scene_id": scene_id,
        "provider": "stub",
        "aoi_feature_name": aoi_name,
        "state": "ready",
    }


# ---------------------------------------------------------------------------
# download_imagery
# ---------------------------------------------------------------------------


class TestDownloadImagery:
    """Tests for ``download_imagery``."""

    def test_uploads_blob_to_expected_path(self) -> None:
        """Downloaded imagery is uploaded with the correct path pattern."""
        from treesight.pipeline.fulfilment import download_imagery

        storage = MagicMock()
        provider = _StubProvider()
        outcome = _ready_outcome()

        download_imagery(
            outcome=outcome,
            provider=provider,
            project_name="my-farm",
            timestamp="2026-03-18T12:00:00Z",
            output_container="kml-output",
            storage=storage,
        )

        storage.upload_bytes.assert_called_once()
        call_args = storage.upload_bytes.call_args[0]
        assert call_args[0] == "kml-output"  # container
        assert "imagery/raw/my-farm/" in call_args[1]  # path includes project
        assert call_args[1].endswith(".tif")

    def test_result_contains_download_fields(self) -> None:
        """The result dict includes order_id, blob_path, size_bytes."""
        from treesight.pipeline.fulfilment import download_imagery

        storage = MagicMock()
        provider = _StubProvider()

        result = download_imagery(
            outcome=_ready_outcome(),
            provider=provider,
            project_name="farm",
            timestamp="ts",
            output_container="kml-output",
            storage=storage,
        )

        assert result["order_id"] == "order-1"
        assert result["scene_id"] == "SCENE-001"
        assert result["blob_path"].endswith(".tif")
        assert result["container"] == "kml-output"
        assert result["size_bytes"] > 0  # valid stub GeoTIFF bytes

    def test_provider_error_returns_failed(self) -> None:
        """A provider download failure is captured gracefully."""
        from treesight.pipeline.fulfilment import download_imagery

        storage = MagicMock()
        provider = _StubProvider(download_error=RuntimeError("Network timeout"))

        result = download_imagery(
            outcome=_ready_outcome(),
            provider=provider,
            project_name="farm",
            timestamp="ts",
            output_container="kml-output",
            storage=storage,
        )

        assert result["state"] == "failed"
        assert "Network timeout" in result["error"]
        storage.upload_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# post_process_imagery
# ---------------------------------------------------------------------------


class TestPostProcessImagery:
    """Tests for ``post_process_imagery``."""

    def _download_result(
        self,
        blob_path: str = "imagery/raw/farm/ts/Block_A/SCENE.tif",
    ) -> dict[str, Any]:
        return {
            "order_id": "order-1",
            "scene_id": "SCENE-001",
            "blob_path": blob_path,
            "container": "kml-output",
            "size_bytes": 1024,
        }

    @staticmethod
    def _mock_storage() -> MagicMock:
        """Return a MagicMock storage whose ``download_bytes`` returns a valid GeoTIFF."""
        storage = MagicMock()
        storage.download_bytes.return_value = _make_geotiff_bytes()
        return storage

    def test_clipping_uploads_clipped_blob(self, aoi: AOI) -> None:
        """With clipping enabled, a clipped blob is uploaded."""
        from treesight.pipeline.fulfilment import post_process_imagery

        storage = self._mock_storage()
        result = post_process_imagery(
            download_result=self._download_result(),
            aoi=aoi,
            project_name="farm",
            timestamp="ts",
            target_crs="EPSG:32637",
            enable_clipping=True,
            enable_reprojection=False,
            output_container="kml-output",
            storage=storage,
        )

        assert result["clipped"] is True
        assert result["clipped_blob_path"].startswith("imagery/clipped/farm/")
        storage.upload_bytes.assert_called_once()

    def test_no_clipping_no_upload(self, aoi: AOI) -> None:
        """With clipping disabled, the raw bytes are still uploaded (passthrough)."""
        from treesight.pipeline.fulfilment import post_process_imagery

        storage = self._mock_storage()
        result = post_process_imagery(
            download_result=self._download_result(),
            aoi=aoi,
            project_name="farm",
            timestamp="ts",
            target_crs="EPSG:32637",
            enable_clipping=False,
            enable_reprojection=False,
            output_container="kml-output",
            storage=storage,
        )

        assert result["clipped"] is False
        # Passthrough still writes the output
        storage.upload_bytes.assert_called_once()

    def test_reprojection_flag(self, aoi: AOI) -> None:
        """Reprojection is flagged when source and target CRS differ."""
        from treesight.pipeline.fulfilment import post_process_imagery

        storage = self._mock_storage()
        result = post_process_imagery(
            download_result=self._download_result(),
            aoi=aoi,
            project_name="farm",
            timestamp="ts",
            target_crs="EPSG:4326",  # different from GeoTIFF's EPSG:32637
            enable_clipping=False,
            enable_reprojection=True,
            output_container="kml-output",
            storage=storage,
        )

        assert result["reprojected"] is True

    def test_same_crs_skips_reprojection(self, aoi: AOI) -> None:
        """No reprojection when source and target CRS match."""
        from treesight.pipeline.fulfilment import post_process_imagery

        storage = self._mock_storage()
        result = post_process_imagery(
            download_result=self._download_result(),
            aoi=aoi,
            project_name="farm",
            timestamp="ts",
            target_crs="EPSG:32637",  # same as GeoTIFF source CRS
            enable_clipping=False,
            enable_reprojection=True,
            output_container="kml-output",
            storage=storage,
        )

        assert result["reprojected"] is False

    def test_result_has_timing_info(self, aoi: AOI) -> None:
        """The result includes processing duration."""
        from treesight.pipeline.fulfilment import post_process_imagery

        storage = self._mock_storage()
        result = post_process_imagery(
            download_result=self._download_result(),
            aoi=aoi,
            project_name="farm",
            timestamp="ts",
            target_crs="EPSG:4326",
            enable_clipping=True,
            enable_reprojection=True,
            output_container="kml-output",
            storage=storage,
        )

        assert result["processing_duration_seconds"] >= 0
        assert result["order_id"] == "order-1"
