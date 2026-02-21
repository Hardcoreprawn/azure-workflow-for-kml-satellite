"""Tests for large-payload offloading helpers (Issue #62).

Validates:
- ``is_offloaded`` detects offloaded references and rejects non-references
- ``offload_if_large`` passes through small payloads and offloads large ones
- ``build_ref_input`` constructs per-item activity inputs
- ``resolve_ref_input`` hydrates items from blob and passes through direct dicts
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from kml_satellite.core.payload_offload import (
    INDEX_KEY,
    OFFLOAD_SENTINEL,
    OFFLOAD_THRESHOLD_BYTES,
    PAYLOAD_CONTAINER,
    REF_KEY,
    build_ref_input,
    is_offloaded,
    offload_if_large,
    resolve_ref_input,
)

# ---------------------------------------------------------------------------
# is_offloaded
# ---------------------------------------------------------------------------


class TestIsOffloaded:
    """Detect offloaded payload references."""

    def test_offloaded_reference_detected(self) -> None:
        ref = {OFFLOAD_SENTINEL: True, "container": "c", "blob_path": "p", "count": 5}
        assert is_offloaded(ref) is True

    def test_plain_dict_not_offloaded(self) -> None:
        assert is_offloaded({"name": "polygon-1"}) is False

    def test_list_not_offloaded(self) -> None:
        assert is_offloaded([{"name": "p1"}, {"name": "p2"}]) is False

    def test_none_not_offloaded(self) -> None:
        assert is_offloaded(None) is False

    def test_string_not_offloaded(self) -> None:
        assert is_offloaded("some string") is False

    def test_sentinel_false_not_offloaded(self) -> None:
        assert is_offloaded({OFFLOAD_SENTINEL: False}) is False


# ---------------------------------------------------------------------------
# offload_if_large
# ---------------------------------------------------------------------------


def _make_blob_service_mock() -> MagicMock:
    """Create a mock BlobServiceClient that captures uploads."""
    blob_service = MagicMock()
    container_client = MagicMock()
    blob_client = MagicMock()
    blob_service.get_container_client.return_value = container_client
    blob_service.get_blob_client.return_value = blob_client
    return blob_service


class TestOffloadIfLarge:
    """Offload payload to blob when over threshold."""

    def test_small_payload_passthrough(self) -> None:
        payload = [{"name": "p1", "index": 0}]
        blob_service = _make_blob_service_mock()
        result = offload_if_large(
            payload,
            blob_path="test/features.json",
            blob_service_client=blob_service,
        )
        assert result is payload
        blob_service.get_blob_client.assert_not_called()

    def test_large_payload_offloaded(self) -> None:
        # Create a payload that exceeds the threshold
        payload = [{"name": f"feature-{i}", "data": "x" * 500} for i in range(200)]
        blob_service = _make_blob_service_mock()

        result = offload_if_large(
            payload,
            blob_path="payloads/test/features.json",
            blob_service_client=blob_service,
        )

        assert is_offloaded(result)
        assert isinstance(result, dict)
        assert result["count"] == 200
        assert result["container"] == PAYLOAD_CONTAINER
        assert result["blob_path"] == "payloads/test/features.json"
        assert result["item_blob_stem"] == "payloads/test/features"
        assert result["size_bytes"] > 0

        # Verify main blob + per-item blobs were uploaded
        # 1 call for the main blob + 200 calls for per-item blobs
        assert blob_service.get_blob_client.call_count == 201

    def test_custom_threshold(self) -> None:
        payload = [{"name": "small"}]
        blob_service = _make_blob_service_mock()

        # With threshold of 1 byte, even a tiny payload triggers offload
        result = offload_if_large(
            payload,
            blob_path="test.json",
            blob_service_client=blob_service,
            threshold_bytes=1,
        )
        assert is_offloaded(result)

    def test_custom_container(self) -> None:
        payload = [{"x": "y" * 1000}]
        blob_service = _make_blob_service_mock()

        result = offload_if_large(
            payload,
            blob_path="f.json",
            blob_service_client=blob_service,
            container="custom-container",
            threshold_bytes=1,
        )
        assert isinstance(result, dict)
        assert result["container"] == "custom-container"

    def test_exact_threshold_not_offloaded(self) -> None:
        payload = [{"k": "v"}]
        serialized_size = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        blob_service = _make_blob_service_mock()

        result = offload_if_large(
            payload,
            blob_path="f.json",
            blob_service_client=blob_service,
            threshold_bytes=serialized_size,
        )
        # Exactly at threshold → not offloaded
        assert result is payload

    def test_default_threshold_constant(self) -> None:
        assert OFFLOAD_THRESHOLD_BYTES == 48 * 1024


# ---------------------------------------------------------------------------
# build_ref_input
# ---------------------------------------------------------------------------


class TestBuildRefInput:
    """Construct per-item activity input from offloaded reference."""

    def test_ref_input_structure(self) -> None:
        ref = {
            OFFLOAD_SENTINEL: True,
            "container": "pipeline-payloads",
            "blob_path": "payloads/id/features.json",
            "item_blob_stem": "payloads/id/features",
            "count": 10,
            "size_bytes": 50000,
        }
        result = build_ref_input(ref, 3)

        assert REF_KEY in result
        assert result[INDEX_KEY] == 3
        assert result[REF_KEY]["container"] == "pipeline-payloads"
        assert result[REF_KEY]["blob_path"] == "payloads/id/features.json"
        assert result[REF_KEY]["item_blob_stem"] == "payloads/id/features"
        assert result[REF_KEY]["count"] == 10

    def test_ref_input_index_zero(self) -> None:
        ref = {
            OFFLOAD_SENTINEL: True,
            "container": "c",
            "blob_path": "p",
            "item_blob_stem": "p",
            "count": 1,
        }
        result = build_ref_input(ref, 0)
        assert result[INDEX_KEY] == 0


# ---------------------------------------------------------------------------
# resolve_ref_input
# ---------------------------------------------------------------------------


class TestResolveRefInput:
    """Resolve blob references in activity inputs."""

    def test_direct_payload_passthrough(self) -> None:
        payload = {"name": "polygon-1", "geometry": {}}
        blob_service = _make_blob_service_mock()
        result = resolve_ref_input(payload, blob_service_client=blob_service)
        assert result is payload
        blob_service.get_blob_client.assert_not_called()

    def test_ref_resolved_from_blob(self) -> None:
        features = [{"name": "f0"}, {"name": "f1"}, {"name": "f2"}]
        blob_data = json.dumps(features).encode("utf-8")

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.return_value.readall.return_value = blob_data

        payload = {
            REF_KEY: {
                "container": "pipeline-payloads",
                "blob_path": "payloads/id/features.json",
                "count": 3,
            },
            INDEX_KEY: 1,
        }

        result = resolve_ref_input(payload, blob_service_client=blob_service)
        assert result == {"name": "f1"}

    def test_ref_index_zero(self) -> None:
        features = [{"name": "first"}]
        blob_data = json.dumps(features).encode("utf-8")

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.return_value.readall.return_value = blob_data

        payload = {
            REF_KEY: {"container": "c", "blob_path": "p.json", "count": 1},
            INDEX_KEY: 0,
        }

        result = resolve_ref_input(payload, blob_service_client=blob_service)
        assert result == {"name": "first"}

    def test_ref_index_out_of_range(self) -> None:
        features = [{"name": "only"}]
        blob_data = json.dumps(features).encode("utf-8")

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.return_value.readall.return_value = blob_data

        payload = {
            REF_KEY: {"container": "c", "blob_path": "p.json", "count": 1},
            INDEX_KEY: 5,
        }

        with pytest.raises(IndexError, match="out of range"):
            resolve_ref_input(payload, blob_service_client=blob_service)

    def test_ref_key_none_treated_as_direct(self) -> None:
        payload = {REF_KEY: None, "name": "direct"}
        blob_service = _make_blob_service_mock()
        result = resolve_ref_input(payload, blob_service_client=blob_service)
        assert result is payload

    def test_blob_client_called_with_correct_params(self) -> None:
        features = [{"name": "f0"}]
        blob_data = json.dumps(features).encode("utf-8")

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.return_value.readall.return_value = blob_data

        payload = {
            REF_KEY: {"container": "my-container", "blob_path": "my/path.json", "count": 1},
            INDEX_KEY: 0,
        }

        resolve_ref_input(payload, blob_service_client=blob_service)
        blob_service.get_blob_client.assert_called_once_with(
            container="my-container",
            blob="my/path.json",
        )

    def test_per_item_blob_resolution(self) -> None:
        """When item_blob_stem is present, resolve reads single-item blob."""
        item = {"name": "feature-2"}
        blob_data = json.dumps(item).encode("utf-8")

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.return_value.readall.return_value = blob_data

        payload = {
            REF_KEY: {
                "container": "pipeline-payloads",
                "blob_path": "payloads/id/features.json",
                "item_blob_stem": "payloads/id/features",
                "count": 5,
            },
            INDEX_KEY: 2,
        }

        result = resolve_ref_input(payload, blob_service_client=blob_service)
        assert result == {"name": "feature-2"}
        blob_service.get_blob_client.assert_called_once_with(
            container="pipeline-payloads",
            blob="payloads/id/features/2.json",
        )

    def test_blob_download_error_raises_contract_error(self) -> None:
        """Azure SDK errors are wrapped in ContractError."""
        from kml_satellite.core.exceptions import ContractError

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.side_effect = RuntimeError("connection lost")

        payload = {
            REF_KEY: {"container": "c", "blob_path": "p.json", "count": 1},
            INDEX_KEY: 0,
        }

        with pytest.raises(ContractError, match="Failed to download"):
            resolve_ref_input(payload, blob_service_client=blob_service)

    def test_json_decode_error_raises_contract_error(self) -> None:
        """Invalid JSON in blob raises ContractError."""
        from kml_satellite.core.exceptions import ContractError

        blob_service = _make_blob_service_mock()
        blob_client = blob_service.get_blob_client.return_value
        blob_client.download_blob.return_value.readall.return_value = b"not json"

        payload = {
            REF_KEY: {"container": "c", "blob_path": "p.json", "count": 1},
            INDEX_KEY: 0,
        }

        with pytest.raises(ContractError, match="Failed to decode"):
            resolve_ref_input(payload, blob_service_client=blob_service)
