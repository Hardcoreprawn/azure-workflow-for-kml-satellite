"""Tests for the download_imagery activity.

Verifies download, retry logic, validation, and blob path generation
with mocked provider adapters.  All provider interactions are mocked
to avoid real network calls.

References:
    PID FR-3.10  (download imagery upon job completion)
    PID FR-4.2   (store raw imagery under ``/imagery/raw/``)
    PID FR-6.5   (dead-letter after max retries)
    PID Section 7.4.7 (Unit test tier)
    PID Section 10.1  (Container & Path Layout)
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from kml_satellite.activities.download_imagery import (
    DEFAULT_MAX_DOWNLOAD_RETRIES,
    DownloadError,
    _validate_download,
    _validate_raster_content,
    download_imagery,
)
from kml_satellite.models.imagery import BlobReference
from kml_satellite.providers.base import ProviderDownloadError, ProviderError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_OUTCOME: dict[str, object] = {
    "order_id": "pc-SCENE_A",
    "scene_id": "SCENE_A",
    "provider": "planetary_computer",
    "aoi_feature_name": "Block A",
    "state": "ready",
}


def _make_blob_ref(
    size_bytes: int = 1024,
    content_type: str = "image/tiff",
) -> BlobReference:
    return BlobReference(
        container="kml-output",
        blob_path="imagery/raw/SCENE_A.tif",
        size_bytes=size_bytes,
        content_type=content_type,
    )


# ---------------------------------------------------------------------------
# Tests — download_imagery function
# ---------------------------------------------------------------------------


class TestDownloadImagery(unittest.TestCase):
    """download_imagery function with mocked provider."""

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_returns_download_result(self, mock_get_provider: MagicMock) -> None:
        """Happy path: download succeeds on first attempt."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref(size_bytes=2048)
        mock_get_provider.return_value = mock_provider

        result = download_imagery(
            _SAMPLE_OUTCOME,
            orchard_name="Test Orchard",
            timestamp="2026-03-15T12:00:00+00:00",
        )

        assert result["order_id"] == "pc-SCENE_A"
        assert result["scene_id"] == "SCENE_A"
        assert result["provider"] == "planetary_computer"
        assert result["aoi_feature_name"] == "Block A"
        assert result["size_bytes"] == 2048
        assert result["content_type"] == "image/tiff"
        assert result["container"] == "kml-output"
        assert result["retry_count"] == 0
        assert result["download_duration_seconds"] >= 0

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_blob_path_follows_pid_layout(self, mock_get_provider: MagicMock) -> None:
        """Blob path matches PID Section 10.1: imagery/raw/{YYYY}/{MM}/{orchard}/{feature}.tif."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref()
        mock_get_provider.return_value = mock_provider

        result = download_imagery(
            _SAMPLE_OUTCOME,
            orchard_name="Alpha Orchard",
            timestamp="2026-03-15T12:00:00+00:00",
        )

        assert result["blob_path"] == "imagery/raw/2026/03/alpha-orchard/block-a.tif"

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_missing_order_id_raises(self, _mock_get_provider: MagicMock) -> None:
        """Missing order_id → DownloadError (not retryable)."""
        with self.assertRaises(DownloadError) as ctx:
            download_imagery({"scene_id": "S"})
        assert ctx.exception.retryable is False
        assert "order_id" in ctx.exception.message

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_empty_download_rejected(self, mock_get_provider: MagicMock) -> None:
        """Downloaded file with 0 bytes → DownloadError (retryable)."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref(size_bytes=0)
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(DownloadError) as ctx:
            download_imagery(_SAMPLE_OUTCOME)
        assert ctx.exception.retryable is True
        assert "empty" in ctx.exception.message.lower()

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_retry_on_transient_error(self, mock_get_provider: MagicMock) -> None:
        """Transient ProviderDownloadError → retry → success."""
        mock_provider = MagicMock()
        mock_provider.download.side_effect = [
            ProviderDownloadError("pc", "timeout", retryable=True),
            _make_blob_ref(size_bytes=4096),
        ]
        mock_get_provider.return_value = mock_provider

        result = download_imagery(_SAMPLE_OUTCOME)

        assert result["size_bytes"] == 4096
        assert result["retry_count"] == 1
        assert mock_provider.download.call_count == 2

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_retries_exhausted_raises(self, mock_get_provider: MagicMock) -> None:
        """All retries exhausted → DownloadError (not retryable)."""
        mock_provider = MagicMock()
        mock_provider.download.side_effect = ProviderDownloadError(
            "pc", "persistent failure", retryable=True
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(DownloadError) as ctx:
            download_imagery(_SAMPLE_OUTCOME, max_retries=2)
        assert ctx.exception.retryable is False
        assert "3 attempts" in ctx.exception.message
        # 1 initial + 2 retries = 3 total attempts
        assert mock_provider.download.call_count == 3

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_non_retryable_error_no_retry(self, mock_get_provider: MagicMock) -> None:
        """Non-retryable ProviderDownloadError → immediate failure."""
        mock_provider = MagicMock()
        mock_provider.download.side_effect = ProviderDownloadError(
            "pc", "order not found", retryable=False
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(DownloadError) as ctx:
            download_imagery(_SAMPLE_OUTCOME)
        assert ctx.exception.retryable is False
        assert mock_provider.download.call_count == 1

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_unknown_provider_raises(self, mock_get_provider: MagicMock) -> None:
        """Unknown provider → DownloadError (not retryable)."""
        mock_get_provider.side_effect = ProviderError("bad", "Unknown provider")

        with self.assertRaises(DownloadError) as ctx:
            download_imagery(_SAMPLE_OUTCOME, provider_name="bad")
        assert ctx.exception.retryable is False

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_default_orchard_name(self, mock_get_provider: MagicMock) -> None:
        """Missing orchard_name defaults to 'unknown' in blob path."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref()
        mock_get_provider.return_value = mock_provider

        result = download_imagery(
            _SAMPLE_OUTCOME,
            timestamp="2026-01-10T00:00:00+00:00",
        )

        assert "/unknown/" in result["blob_path"]

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_uses_scene_id_when_no_feature_name(self, mock_get_provider: MagicMock) -> None:
        """When aoi_feature_name is empty, scene_id is used for the path."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref()
        mock_get_provider.return_value = mock_provider

        outcome = dict(_SAMPLE_OUTCOME)
        outcome["aoi_feature_name"] = ""

        result = download_imagery(
            outcome,
            orchard_name="orchard",
            timestamp="2026-06-01T00:00:00+00:00",
        )

        # scene_id "SCENE_A" → slug "scenea" (underscore stripped)
        assert "scenea.tif" in result["blob_path"]

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_custom_max_retries(self, mock_get_provider: MagicMock) -> None:
        """max_retries parameter controls retry count."""
        mock_provider = MagicMock()
        mock_provider.download.side_effect = ProviderDownloadError("pc", "fail", retryable=True)
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(DownloadError):
            download_imagery(_SAMPLE_OUTCOME, max_retries=1)
        # 1 initial + 1 retry = 2 attempts
        assert mock_provider.download.call_count == 2

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_provider_name_from_outcome(self, mock_get_provider: MagicMock) -> None:
        """Provider name is taken from imagery_outcome if present."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref()
        mock_get_provider.return_value = mock_provider

        result = download_imagery(_SAMPLE_OUTCOME)
        assert result["provider"] == "planetary_computer"

    @patch("kml_satellite.activities.download_imagery.get_provider")
    def test_result_includes_adapter_blob_path(self, mock_get_provider: MagicMock) -> None:
        """Result contains adapter_blob_path for staging path traceability (Issue #46)."""
        mock_provider = MagicMock()
        mock_provider.download.return_value = _make_blob_ref(size_bytes=2048)
        mock_get_provider.return_value = mock_provider

        result = download_imagery(
            _SAMPLE_OUTCOME,
            orchard_name="Test Orchard",
            timestamp="2026-03-15T12:00:00+00:00",
        )

        # adapter_blob_path should be the path from the BlobReference
        assert result["adapter_blob_path"] == "imagery/raw/SCENE_A.tif"
        # blob_path should be the canonical PID-compliant path
        assert result["blob_path"] == "imagery/raw/2026/03/test-orchard/block-a.tif"


# ---------------------------------------------------------------------------
# Tests — _validate_download
# ---------------------------------------------------------------------------


class TestValidateDownload(unittest.TestCase):
    """_validate_download helper."""

    def test_valid_blob_ref_passes(self) -> None:
        """Non-empty GeoTIFF passes validation."""
        blob_ref = _make_blob_ref(size_bytes=1024, content_type="image/tiff")
        _validate_download(blob_ref, "order-1")  # Should not raise

    def test_empty_file_raises(self) -> None:
        """Zero-byte file → DownloadError (retryable)."""
        blob_ref = _make_blob_ref(size_bytes=0)
        with self.assertRaises(DownloadError) as ctx:
            _validate_download(blob_ref, "order-1")
        assert ctx.exception.retryable is True

    def test_negative_size_raises(self) -> None:
        """Negative size → DownloadError (retryable)."""
        blob_ref = BlobReference(
            container="c",
            blob_path="p.tif",
            size_bytes=-1,
            content_type="image/tiff",
        )
        with self.assertRaises(DownloadError):
            _validate_download(blob_ref, "order-1")

    def test_unexpected_content_type_warns(self) -> None:
        """Unexpected content type logs a warning but does not raise."""
        blob_ref = _make_blob_ref(size_bytes=100, content_type="application/octet-stream")
        # Should not raise — just logs a warning
        _validate_download(blob_ref, "order-1")


# ---------------------------------------------------------------------------
# Tests — defaults
# ---------------------------------------------------------------------------


class TestDownloadDefaults(unittest.TestCase):
    """Verify exported default constants."""

    def test_default_max_retries(self) -> None:
        assert DEFAULT_MAX_DOWNLOAD_RETRIES == 3


# ---------------------------------------------------------------------------
# Tests — _validate_raster_content (Issue #46)
# ---------------------------------------------------------------------------


class TestValidateRasterContent(unittest.TestCase):
    """_validate_raster_content rasterio-based validation."""

    def test_skips_when_no_connection_string(self) -> None:
        """No AzureWebJobsStorage → validation is skipped (no error)."""
        blob_ref = _make_blob_ref(size_bytes=1024)
        with patch.dict("os.environ", {}, clear=True):
            _validate_raster_content(blob_ref, "order-1")  # Should not raise

    @patch("azure.storage.blob.BlobServiceClient")
    def test_skips_when_blob_not_persisted(self, mock_bsc_cls: MagicMock) -> None:
        """Blob not yet persisted → validation is skipped."""
        blob_ref = _make_blob_ref(size_bytes=1024)
        mock_blob_client = MagicMock()
        mock_blob_client.exists.return_value = False
        mock_blob_service = MagicMock()
        mock_blob_service.get_blob_client.return_value = mock_blob_client
        mock_bsc_cls.from_connection_string.return_value = mock_blob_service

        with patch.dict("os.environ", {"AzureWebJobsStorage": "conn_str"}):
            _validate_raster_content(blob_ref, "order-1")  # Should not raise
