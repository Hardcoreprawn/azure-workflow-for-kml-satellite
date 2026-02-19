"""Tests for activity payload schemas and runtime validation (Issue #43).

Validates:
- ``validate_payload`` raises ``ContractError`` for missing required keys
- ``validate_payload`` passes for valid payloads
- Every activity schema's required keys are documented
- Error messages include the activity name and missing key names
"""

from __future__ import annotations

import pytest

from kml_satellite.core.exceptions import ContractError
from kml_satellite.models.payloads import (
    AcquireImageryInput,
    DownloadImageryInput,
    ParseKmlInput,
    PollOrderInput,
    PostProcessImageryInput,
    WriteMetadataInput,
    validate_payload,
)


class TestValidatePayloadRejectsMissingKeys:
    """validate_payload raises ContractError for missing required keys."""

    def test_parse_kml_missing_container_name(self) -> None:
        with pytest.raises(ContractError, match="container_name"):
            validate_payload({"blob_name": "a.kml"}, ParseKmlInput, activity="parse_kml")

    def test_parse_kml_missing_blob_name(self) -> None:
        with pytest.raises(ContractError, match="blob_name"):
            validate_payload({"container_name": "c"}, ParseKmlInput, activity="parse_kml")

    def test_parse_kml_missing_both(self) -> None:
        with pytest.raises(ContractError, match="missing required payload key"):
            validate_payload({}, ParseKmlInput, activity="parse_kml")

    def test_write_metadata_missing_aoi(self) -> None:
        with pytest.raises(ContractError, match="aoi"):
            validate_payload(
                {"processing_id": "x", "timestamp": "t"},
                WriteMetadataInput,
                activity="write_metadata",
            )

    def test_acquire_imagery_missing_aoi(self) -> None:
        with pytest.raises(ContractError, match="aoi"):
            validate_payload(
                {"provider_name": "pc"},
                AcquireImageryInput,
                activity="acquire_imagery",
            )

    def test_poll_order_missing_order_id(self) -> None:
        with pytest.raises(ContractError, match="order_id"):
            validate_payload({"provider": "pc"}, PollOrderInput, activity="poll_order")

    def test_poll_order_missing_provider(self) -> None:
        with pytest.raises(ContractError, match="provider"):
            validate_payload({"order_id": "123"}, PollOrderInput, activity="poll_order")

    def test_download_imagery_missing_imagery_outcome(self) -> None:
        with pytest.raises(ContractError, match="imagery_outcome"):
            validate_payload({}, DownloadImageryInput, activity="download_imagery")

    def test_post_process_missing_download_result(self) -> None:
        with pytest.raises(ContractError, match="download_result"):
            validate_payload(
                {"aoi": {}},
                PostProcessImageryInput,
                activity="post_process_imagery",
            )

    def test_post_process_missing_aoi(self) -> None:
        with pytest.raises(ContractError, match="aoi"):
            validate_payload(
                {"download_result": {}},
                PostProcessImageryInput,
                activity="post_process_imagery",
            )


class TestValidatePayloadAcceptsValid:
    """validate_payload does not raise for valid payloads."""

    def test_parse_kml_valid(self) -> None:
        validate_payload(
            {"container_name": "c", "blob_name": "b.kml"},
            ParseKmlInput,
            activity="parse_kml",
        )

    def test_parse_kml_with_optional_correlation_id(self) -> None:
        validate_payload(
            {"container_name": "c", "blob_name": "b.kml", "correlation_id": "x"},
            ParseKmlInput,
            activity="parse_kml",
        )

    def test_write_metadata_valid(self) -> None:
        validate_payload(
            {"aoi": {}, "processing_id": "id", "timestamp": "t"},
            WriteMetadataInput,
            activity="write_metadata",
        )

    def test_acquire_imagery_valid(self) -> None:
        validate_payload(
            {"aoi": {}},
            AcquireImageryInput,
            activity="acquire_imagery",
        )

    def test_poll_order_valid(self) -> None:
        validate_payload(
            {"order_id": "123", "provider": "pc"},
            PollOrderInput,
            activity="poll_order",
        )

    def test_download_imagery_valid(self) -> None:
        validate_payload(
            {"imagery_outcome": {}},
            DownloadImageryInput,
            activity="download_imagery",
        )

    def test_post_process_valid(self) -> None:
        validate_payload(
            {"download_result": {}, "aoi": {}},
            PostProcessImageryInput,
            activity="post_process_imagery",
        )


class TestContractErrorAttributes:
    """ContractError raised by validate_payload carries structured attributes."""

    def test_stage_matches_activity(self) -> None:
        with pytest.raises(ContractError) as exc_info:
            validate_payload({}, ParseKmlInput, activity="parse_kml")
        err = exc_info.value
        assert err.stage == "parse_kml"
        assert err.code == "PAYLOAD_MISSING_KEYS"
        assert err.retryable is False

    def test_error_dict_includes_missing_keys_in_message(self) -> None:
        with pytest.raises(ContractError) as exc_info:
            validate_payload({}, PollOrderInput, activity="poll_order")
        d = exc_info.value.to_error_dict()
        msg = str(d["message"])
        assert "order_id" in msg
        assert "provider" in msg
        assert d["stage"] == "poll_order"
