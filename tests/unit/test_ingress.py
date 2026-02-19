"""Tests for the ingress boundary helpers (Issue #61).

Validates:
- ``deserialize_activity_input`` handles JSON strings, dicts, and bad types
- ``build_orchestrator_input`` constructs canonical payloads and rejects bad input
- ``get_blob_service_client`` fails fast when env var is missing
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from kml_satellite.core.exceptions import ContractError
from kml_satellite.core.ingress import (
    OrchestratorInput,
    build_orchestrator_input,
    deserialize_activity_input,
    get_blob_service_client,
)

# ---------------------------------------------------------------------------
# deserialize_activity_input
# ---------------------------------------------------------------------------


class TestDeserializeActivityInput:
    """Normalise raw Durable Functions input to a dict."""

    def test_json_string_parsed(self) -> None:
        raw = json.dumps({"container_name": "c", "blob_name": "b.kml"})
        result = deserialize_activity_input(raw)
        assert result == {"container_name": "c", "blob_name": "b.kml"}

    def test_dict_passthrough(self) -> None:
        payload = {"order_id": "123", "provider": "pc"}
        result = deserialize_activity_input(payload)
        assert result is payload

    def test_invalid_json_raises_contract_error(self) -> None:
        with pytest.raises(ContractError, match="not valid JSON") as exc_info:
            deserialize_activity_input("{not-json")
        assert exc_info.value.code == "INVALID_JSON"
        assert exc_info.value.stage == "ingress"

    def test_json_array_raises_contract_error(self) -> None:
        with pytest.raises(ContractError, match="must be an object") as exc_info:
            deserialize_activity_input("[1, 2, 3]")
        assert exc_info.value.code == "INVALID_INPUT_TYPE"

    def test_unexpected_type_raises_contract_error(self) -> None:
        with pytest.raises(ContractError, match="Unexpected activity input type") as exc_info:
            deserialize_activity_input(42)  # type: ignore[arg-type]
        assert exc_info.value.code == "INVALID_INPUT_TYPE"

    def test_empty_json_object(self) -> None:
        result = deserialize_activity_input("{}")
        assert result == {}

    def test_nested_objects_preserved(self) -> None:
        raw = json.dumps({"aoi": {"bbox": [1, 2, 3, 4]}, "provider_name": "pc"})
        result = deserialize_activity_input(raw)
        assert result["aoi"] == {"bbox": [1, 2, 3, 4]}


# ---------------------------------------------------------------------------
# build_orchestrator_input
# ---------------------------------------------------------------------------


class TestBuildOrchestratorInput:
    """Construct canonical orchestrator payload from Event Grid data."""

    @pytest.fixture()
    def valid_event_data(self) -> dict[str, object]:
        return {
            "url": "https://account.blob.core.windows.net/kml-input/test.kml",
            "contentLength": 1024,
            "contentType": "application/vnd.google-earth.kml+xml",
        }

    def test_valid_event_returns_orchestrator_input(
        self, valid_event_data: dict[str, object]
    ) -> None:
        result = build_orchestrator_input(
            valid_event_data,
            event_time="2025-01-01T00:00:00Z",
            event_id="evt-123",
        )
        assert result["container_name"] == "kml-input"
        assert result["blob_name"] == "test.kml"
        assert result["content_length"] == 1024
        assert result["correlation_id"] == "evt-123"
        assert result["event_time"] == "2025-01-01T00:00:00Z"

    def test_correlation_id_propagated(self, valid_event_data: dict[str, object]) -> None:
        result = build_orchestrator_input(valid_event_data, event_id="my-correlation-id")
        assert result["correlation_id"] == "my-correlation-id"

    def test_missing_url_raises_contract_error(self) -> None:
        with pytest.raises(ContractError, match="blob_url") as exc_info:
            build_orchestrator_input(
                {"contentLength": 0},
                event_id="evt-1",
            )
        assert exc_info.value.code == "MISSING_ORCHESTRATOR_FIELDS"

    def test_empty_url_raises_contract_error(self) -> None:
        with pytest.raises(ContractError, match="missing required field"):
            build_orchestrator_input(
                {"url": "", "contentLength": 0},
                event_id="evt-1",
            )

    def test_result_is_typed_dict_compatible(self, valid_event_data: dict[str, object]) -> None:
        result = build_orchestrator_input(valid_event_data, event_id="evt-1")
        # Verify it has all required OrchestratorInput keys
        required_keys = {
            "blob_url",
            "container_name",
            "blob_name",
            "content_length",
            "content_type",
            "event_time",
            "correlation_id",
        }
        assert required_keys.issubset(result.keys())

    def test_azurite_url_parsed(self) -> None:
        event_data = {
            "url": "http://127.0.0.1:10000/devstoreaccount1/kml-input/folder/file.kml",
            "contentLength": 512,
        }
        result = build_orchestrator_input(event_data, event_id="evt-az")
        assert result["container_name"] == "kml-input"
        assert result["blob_name"] == "folder/file.kml"


# ---------------------------------------------------------------------------
# get_blob_service_client
# ---------------------------------------------------------------------------


class TestGetBlobServiceClient:
    """Factory for BlobServiceClient from env var."""

    def test_missing_env_var_raises_contract_error(self) -> None:
        with patch.dict("os.environ", {"AzureWebJobsStorage": ""}, clear=False):
            with pytest.raises(ContractError, match="AzureWebJobsStorage") as exc_info:
                get_blob_service_client()
            assert exc_info.value.code == "MISSING_CONNECTION_STRING"
            assert exc_info.value.stage == "ingress"

    def test_empty_env_var_raises_contract_error(self) -> None:
        with (
            patch.dict("os.environ", {"AzureWebJobsStorage": ""}, clear=False),
            pytest.raises(ContractError, match="AzureWebJobsStorage"),
        ):
            get_blob_service_client()

    def test_valid_connection_string_returns_client(self) -> None:
        conn_str = (
            "DefaultEndpointsProtocol=https;"
            "AccountName=test;AccountKey=dGVzdA==;"
            "EndpointSuffix=core.windows.net"
        )
        with patch.dict("os.environ", {"AzureWebJobsStorage": conn_str}, clear=False):
            client = get_blob_service_client()
            assert client is not None


# ---------------------------------------------------------------------------
# OrchestratorInput TypedDict shape
# ---------------------------------------------------------------------------


class TestOrchestratorInputSchema:
    """The OrchestratorInput TypedDict has the expected required keys."""

    def test_required_annotations(self) -> None:
        # TypedDict annotations reflect the canonical schema
        annotations = OrchestratorInput.__annotations__
        assert "blob_url" in annotations
        assert "container_name" in annotations
        assert "blob_name" in annotations
        assert "content_length" in annotations
        assert "correlation_id" in annotations

    def test_optional_provider_fields(self) -> None:
        annotations = OrchestratorInput.__annotations__
        assert "provider_name" in annotations
        assert "provider_config" in annotations
        assert "imagery_filters" in annotations
