"""Tests for error helper functions.

Tests for contract-shaped error dict builders used in fulfillment phase.
These helpers ensure consistent error responses across download and post-process failures.
"""

from __future__ import annotations

from typing import Any


class TestDownloadErrorDict:
    """Tests for error dict builder for failed downloads."""

    def test_builds_contract_dict_with_defaults(self) -> None:
        """Must return a contract-shaped dict with all expected fields."""
        from kml_satellite.orchestrators.error_helpers import download_error_dict

        outcome = {
            "order_id": "order-123",
            "scene_id": "scene-456",
            "provider": "planetary_computer",
            "aoi_feature_name": "Field A",
        }

        result = download_error_dict(outcome, "Network timeout")

        # Verify all contract fields present
        assert result["state"] == "failed"
        assert result["order_id"] == "order-123"
        assert result["scene_id"] == "scene-456"
        assert result["provider"] == "planetary_computer"
        assert result["aoi_feature_name"] == "Field A"
        assert result["error"] == "Network timeout"
        assert result["blob_path"] == ""
        assert result["adapter_blob_path"] == ""
        assert result["container"] == ""
        assert result["size_bytes"] == 0
        assert result["content_type"] == ""
        assert result["download_duration_seconds"] == 0.0
        assert result["retry_count"] == 0

    def test_state_override(self) -> None:
        """State can be overridden (e.g., for non-terminal failures)."""
        from kml_satellite.orchestrators.error_helpers import download_error_dict

        outcome = {"order_id": "order-123"}
        result = download_error_dict(outcome, "Error", state="retrying")
        assert result["state"] == "retrying"

    def test_handles_missing_fields(self) -> None:
        """Missing outcome fields are coerced to empty strings/defaults."""
        from kml_satellite.orchestrators.error_helpers import download_error_dict

        outcome: dict[str, Any] = {}  # Empty
        result = download_error_dict(outcome, "Missing data")

        assert result["order_id"] == ""
        assert result["scene_id"] == ""
        assert result["provider"] == ""
        assert result["aoi_feature_name"] == ""
        assert result["error"] == "Missing data"

    def test_handles_non_string_fields(self) -> None:
        """Non-string outcome fields are coerced to strings."""
        from kml_satellite.orchestrators.error_helpers import download_error_dict

        outcome = {
            "order_id": 123,  # int instead of string
            "scene_id": None,  # None
            "provider": ["list"],  # list
        }

        result = download_error_dict(outcome, "Type error")
        assert isinstance(result["order_id"], str)
        assert isinstance(result["scene_id"], str)
        assert isinstance(result["provider"], str)


class TestPostProcessErrorDict:
    """Tests for error dict builder for failed post-process operations."""

    def test_builds_contract_dict_with_defaults(self) -> None:
        """Must return a contract-shaped dict with all expected fields."""
        from kml_satellite.orchestrators.error_helpers import post_process_error_dict

        dl_result = {
            "order_id": "order-123",
            "blob_path": "path/to/source.tif",
            "container": "output-container",
        }

        result = post_process_error_dict(dl_result, "Clip failed")

        # Verify all contract fields
        assert result["state"] == "failed"
        assert result["order_id"] == "order-123"
        assert result["source_blob_path"] == "path/to/source.tif"
        assert result["container"] == "output-container"
        assert result["clipped"] is False
        assert result["reprojected"] is False
        assert result["clipped_blob_path"] == ""
        assert result["source_crs"] == ""
        assert result["target_crs"] == ""
        assert result["source_size_bytes"] == 0
        assert result["output_size_bytes"] == 0
        assert result["processing_duration_seconds"] == 0.0
        assert result["clip_error"] == "Clip failed"
        assert result["error"] == "Clip failed"

    def test_state_override(self) -> None:
        """State can be overridden."""
        from kml_satellite.orchestrators.error_helpers import post_process_error_dict

        dl_result = {"order_id": "order-123"}
        result = post_process_error_dict(dl_result, "Error", state="partial")
        assert result["state"] == "partial"

    def test_handles_missing_fields(self) -> None:
        """Missing download result fields default to None/empty."""
        from kml_satellite.orchestrators.error_helpers import post_process_error_dict

        dl_result: dict[str, Any] = {}
        result = post_process_error_dict(dl_result, "Missing download data")

        assert result["order_id"] is None or result["order_id"] == ""
        assert result["source_blob_path"] == ""
        assert result["container"] == ""
        assert result["error"] == "Missing download data"

    def test_preserves_download_metadata(self) -> None:
        """Fields from download result are preserved in error response."""
        from kml_satellite.orchestrators.error_helpers import post_process_error_dict

        dl_result = {
            "order_id": "order-999",
            "blob_path": "imagery/scene123.tif",
            "container": "large-bucket",
        }

        result = post_process_error_dict(dl_result, "Reproject failed")

        # Download metadata preserved
        assert result["order_id"] == "order-999"
        assert result["source_blob_path"] == "imagery/scene123.tif"
        assert result["container"] == "large-bucket"

    def test_different_error_messages(self) -> None:
        """Error message is captured correctly."""
        from kml_satellite.orchestrators.error_helpers import post_process_error_dict

        errors = [
            "GDAL error: invalid band",
            "Insufficient memory",
            "Timeout after 300 seconds",
        ]

        for error_msg in errors:
            result = post_process_error_dict({}, error_msg)
            assert result["error"] == error_msg
            assert result["clip_error"] == error_msg
