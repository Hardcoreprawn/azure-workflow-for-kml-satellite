"""Contract drift detection tests.

These tests verify that serialised model keys match the canonical payload
contracts defined in ``kml_satellite.models.contracts``.  If a key is
added/removed from a model's ``to_dict()`` without updating the contract
TypedDict, these tests will fail — preventing silent key drift between
orchestrator and activities.

References:
    PID 7.4.5  (Explicit over Implicit — typed boundaries)
    Issue #51  (Canonical payload contract module)
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import get_type_hints
from unittest.mock import MagicMock, patch

from kml_satellite.activities.acquire_imagery import acquire_imagery
from kml_satellite.models.aoi import AOI
from kml_satellite.models.blob_event import BlobEvent
from kml_satellite.models.contracts import (
    AcquisitionResult,
    AOIPayload,
    DownloadImageryInput,
    DownloadResult,
    FeaturePayload,
    ImageryOutcome,
    MetadataResult,
    OrchestrationInput,
    OrchestrationResult,
    PollOrderInput,
    PollResult,
    PostProcessInput,
    PostProcessResult,
    WriteMetadataInput,
)
from kml_satellite.models.feature import Feature
from kml_satellite.models.imagery import OrderId, SearchResult


def _contract_keys(td: type) -> set[str]:
    """Extract the declared field names from a TypedDict class."""
    return set(get_type_hints(td).keys())


# ---------------------------------------------------------------------------
# Feature ↔ FeaturePayload
# ---------------------------------------------------------------------------


class TestFeatureContract(unittest.TestCase):
    """Feature.to_dict() keys must match FeaturePayload contract."""

    def test_keys_match(self) -> None:
        feature = Feature(name="test", exterior_coords=[(0, 0), (1, 0), (1, 1), (0, 0)])
        actual = set(feature.to_dict().keys())
        expected = _contract_keys(FeaturePayload)
        assert actual == expected, f"Drift detected: {actual.symmetric_difference(expected)}"


# ---------------------------------------------------------------------------
# AOI ↔ AOIPayload
# ---------------------------------------------------------------------------


class TestAOIContract(unittest.TestCase):
    """AOI.to_dict() keys must match AOIPayload contract."""

    def test_keys_match(self) -> None:
        aoi = AOI(feature_name="test")
        actual = set(aoi.to_dict().keys())
        expected = _contract_keys(AOIPayload)
        assert actual == expected, f"Drift detected: {actual.symmetric_difference(expected)}"


# ---------------------------------------------------------------------------
# BlobEvent ↔ OrchestrationInput
# ---------------------------------------------------------------------------


class TestBlobEventContract(unittest.TestCase):
    """BlobEvent.to_dict() keys must match OrchestrationInput contract."""

    def test_keys_match(self) -> None:
        event = BlobEvent(
            blob_url="https://example.blob.core.windows.net/c/b.kml",
            container_name="kml-input",
            blob_name="b.kml",
            content_length=100,
            content_type="application/vnd.google-earth.kml+xml",
            event_time=datetime.now(UTC).isoformat(),
            correlation_id="test-id",
        )
        actual = set(event.to_dict().keys())
        expected = _contract_keys(OrchestrationInput)
        assert actual == expected, f"Drift detected: {actual.symmetric_difference(expected)}"


# ---------------------------------------------------------------------------
# Activity output contract completeness
# ---------------------------------------------------------------------------


class TestContractCompleteness(unittest.TestCase):
    """Verify all contract TypedDicts have at least one key defined."""

    def test_all_contracts_non_empty(self) -> None:
        contracts = [
            OrchestrationInput,
            FeaturePayload,
            AOIPayload,
            AcquisitionResult,
            PollOrderInput,
            PollResult,
            ImageryOutcome,
            DownloadImageryInput,
            DownloadResult,
            PostProcessInput,
            PostProcessResult,
            WriteMetadataInput,
            MetadataResult,
            OrchestrationResult,
        ]
        for contract in contracts:
            keys = _contract_keys(contract)
            assert len(keys) > 0, f"{contract.__name__} has no fields"

    def test_acquisition_result_keys(self) -> None:
        """AcquisitionResult contract must contain the keys used by the orchestrator."""
        keys = _contract_keys(AcquisitionResult)
        orchestrator_reads = {"order_id", "scene_id", "provider", "aoi_feature_name"}
        assert orchestrator_reads.issubset(keys), f"Orchestrator needs {orchestrator_reads - keys}"

    def test_poll_result_keys(self) -> None:
        """PollResult must contain keys read by the polling loop."""
        keys = _contract_keys(PollResult)
        assert {"state", "is_terminal", "message"}.issubset(keys)

    def test_download_result_keys(self) -> None:
        """DownloadResult must contain keys used by post-processing."""
        keys = _contract_keys(DownloadResult)
        assert {"order_id", "blob_path", "size_bytes", "aoi_feature_name"}.issubset(keys)

    def test_imagery_outcome_keys(self) -> None:
        """ImageryOutcome must contain keys used for download dispatch."""
        keys = _contract_keys(ImageryOutcome)
        assert {"state", "order_id", "scene_id", "provider", "aoi_feature_name"}.issubset(keys)

    def test_orchestration_result_keys(self) -> None:
        """OrchestrationResult must contain all summary fields."""
        keys = _contract_keys(OrchestrationResult)
        required = {
            "status",
            "instance_id",
            "blob_name",
            "feature_count",
            "aoi_count",
            "imagery_ready",
            "imagery_failed",
            "downloads_completed",
            "message",
        }
        assert required.issubset(keys), f"Missing: {required - keys}"

    def test_write_metadata_result_keys(self) -> None:
        """MetadataResult must contain keys returned by write_metadata."""
        keys = _contract_keys(MetadataResult)
        assert {"metadata", "metadata_path", "kml_archive_path"} == keys

    def test_post_process_result_keys(self) -> None:
        """PostProcessResult must contain all expected output fields."""
        keys = _contract_keys(PostProcessResult)
        required = {
            "order_id",
            "source_blob_path",
            "clipped_blob_path",
            "clipped",
            "reprojected",
            "source_crs",
            "target_crs",
        }
        assert required.issubset(keys), f"Missing: {required - keys}"


class TestAcquireImageryRuntimeContract(unittest.TestCase):
    """Runtime payload from acquire_imagery must match AcquisitionResult TypedDict."""

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_keys_match_acquisition_result_contract(self, mock_get_provider: MagicMock) -> None:
        sample_aoi: dict[str, object] = {
            "feature_name": "Contract AOI",
            "source_file": "contract.kml",
            "feature_index": 0,
            "exterior_coords": [[-120.5, 46.5], [-120.0, 46.5], [-120.0, 46.0], [-120.5, 46.5]],
            "bbox": [-120.5, 46.0, -120.0, 46.5],
            "buffered_bbox": [-120.51, 45.99, -119.99, 46.51],
            "area_ha": 25.0,
            "centroid": [-120.25, 46.25],
        }

        mock_provider = MagicMock()
        mock_provider.search.return_value = [
            SearchResult(
                scene_id="SCENE_CONTRACT_1",
                provider="planetary_computer",
                acquisition_date=datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
                cloud_cover_pct=3.2,
                spatial_resolution_m=10.0,
                asset_url="https://example.test/scene.tif",
            )
        ]
        mock_provider.order.return_value = OrderId(
            provider="planetary_computer",
            order_id="pc-SCENE_CONTRACT_1",
            scene_id="SCENE_CONTRACT_1",
        )
        mock_get_provider.return_value = mock_provider

        actual = acquire_imagery(sample_aoi)
        expected = _contract_keys(AcquisitionResult)
        assert set(actual.keys()) == expected, (
            f"Drift detected: {set(actual.keys()).symmetric_difference(expected)}"
        )
