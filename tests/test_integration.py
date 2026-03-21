"""Integration tests that talk to a live Azurite container.

Requires Azurite running on localhost (``make dev-up``).

Run with:  uv run pytest tests/test_integration.py -v
Skip with: uv run pytest tests/ -v -m "not integration"
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _azurite import AZURITE_CONN_STR, CONTAINERS

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _azurite_reachable() -> bool:
    """Return ``True`` if Azurite is listening on the expected port."""
    try:
        from azure.storage.blob import BlobServiceClient

        client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
        client.get_account_information()
    except Exception:
        return False
    return True


skip_no_azurite = pytest.mark.skipif(
    not _azurite_reachable(),
    reason="Azurite not running (start with: make dev-up)",
)


@skip_no_azurite
class TestAzuriteContainers:
    """Verify that required storage containers can be created in Azurite."""

    def test_containers_can_be_created(self) -> None:
        """Each container in CONTAINERS is created if absent and then exists."""
        from azure.storage.blob import BlobServiceClient

        client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
        for name in CONTAINERS:
            cc = client.get_container_client(name)
            if not cc.exists():
                cc.create_container()
            assert cc.exists()

    def test_all_expected_containers_listed(self) -> None:
        """The shared CONTAINERS list includes the three pipeline containers."""
        assert "kml-input" in CONTAINERS
        assert "kml-output" in CONTAINERS
        assert "pipeline-payloads" in CONTAINERS


@skip_no_azurite
class TestBlobRoundTrip:
    """Upload → download round-trip smoke tests for ``BlobStorageClient``."""

    def test_upload_and_download_kml(self) -> None:
        """A KML file survives upload/download unchanged."""
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        kml_bytes = (FIXTURES_DIR / "sample.kml").read_bytes()

        storage.upload_bytes(
            "kml-input",
            "integration-test/sample.kml",
            kml_bytes,
            content_type="application/vnd.google-earth.kml+xml",
        )

        downloaded = storage.download_bytes("kml-input", "integration-test/sample.kml")
        assert downloaded == kml_bytes

    def test_upload_and_download_json(self) -> None:
        """A JSON dict survives upload/download with values intact."""
        from typing import Any

        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        payload: dict[str, Any] = {"feature_count": 2, "status": "ok", "items": [1, 2, 3]}

        storage.upload_json("kml-output", "integration-test/meta.json", payload)
        result = storage.download_json("kml-output", "integration-test/meta.json")

        assert isinstance(result, dict)
        assert result["feature_count"] == 2
        assert result["items"] == [1, 2, 3]

    def test_blob_exists(self) -> None:
        """``blob_exists`` returns True for present blobs, False for absent."""
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        storage.upload_bytes("kml-input", "integration-test/exists-check.txt", b"hello")

        assert storage.blob_exists("kml-input", "integration-test/exists-check.txt")
        assert not storage.blob_exists("kml-input", "integration-test/no-such-blob.txt")

    def test_blob_properties(self) -> None:
        """``get_blob_properties`` reports correct size and content type."""
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        data = b"test-content-for-props"
        storage.upload_bytes(
            "kml-output",
            "integration-test/props.bin",
            data,
            content_type="application/octet-stream",
        )

        props = storage.get_blob_properties("kml-output", "integration-test/props.bin")
        assert props["size"] == len(data)
        assert props["content_type"] == "application/octet-stream"


# ---------------------------------------------------------------------------
# E2E Ingestion — KML upload → parse → AOI → metadata in Azurite
# ---------------------------------------------------------------------------


@skip_no_azurite
class TestIngestionE2E:
    """Phase 1 end-to-end: real KML through ingestion pipeline against Azurite."""

    def test_parse_kml_from_azurite(self) -> None:
        """Upload KML to Azurite, parse it back via ``parse_kml_from_blob``."""
        from treesight.models.blob_event import BlobEvent
        from treesight.pipeline.ingestion import parse_kml_from_blob
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        kml_bytes = (FIXTURES_DIR / "sample.kml").read_bytes()
        storage.upload_bytes(
            "kml-input",
            "e2e/sample.kml",
            kml_bytes,
            content_type="application/vnd.google-earth.kml+xml",
        )

        event = BlobEvent(
            blob_url="http://127.0.0.1:10000/devstoreaccount1/kml-input/e2e/sample.kml",
            container_name="kml-input",
            blob_name="e2e/sample.kml",
            content_length=len(kml_bytes),
            content_type="application/vnd.google-earth.kml+xml",
            event_time="2026-03-18T12:00:00Z",
            correlation_id="e2e-test-001",
        )

        features = parse_kml_from_blob(event, storage)

        assert len(features) >= 1
        assert features[0].name
        assert len(features[0].exterior_coords) >= 3

    def test_full_ingestion_writes_metadata(self) -> None:
        """KML → parse → prepare AOI → write metadata → verify blob in Azurite."""
        from treesight.models.blob_event import BlobEvent
        from treesight.pipeline.ingestion import (
            parse_kml_from_blob,
            prepare_aois,
            write_metadata,
        )
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        kml_bytes = (FIXTURES_DIR / "sample.kml").read_bytes()
        storage.upload_bytes("kml-input", "e2e/farm.kml", kml_bytes)

        event = BlobEvent(
            blob_url="http://127.0.0.1:10000/devstoreaccount1/kml-input/e2e/farm.kml",
            container_name="kml-input",
            blob_name="e2e/farm.kml",
            content_length=len(kml_bytes),
            content_type="application/vnd.google-earth.kml+xml",
            event_time="2026-03-18T12:00:00Z",
            correlation_id="e2e-test-002",
        )

        # Phase 1, Step 1: Parse
        features = parse_kml_from_blob(event, storage)
        assert len(features) >= 1

        # Phase 1, Step 2: Prepare AOIs
        aois = prepare_aois(features)
        assert len(aois) == len(features)

        # Phase 1, Step 3: Write metadata for each AOI
        results = []
        for aoi in aois:
            result = write_metadata(
                aoi=aoi,
                processing_id="e2e-proc-001",
                timestamp="2026-03-18T12:00:00Z",
                tenant_id="",
                source_file="farm.kml",
                output_container="kml-output",
                storage=storage,
            )
            results.append(result)

        # Verify: metadata blob exists in Azurite and has correct schema
        assert len(results) >= 1
        for result in results:
            path = result["metadata_path"]
            assert storage.blob_exists("kml-output", path)

            doc = storage.download_json("kml-output", path)
            assert doc["$schema"] == "aoi-metadata-v2"
            assert doc["processing_id"] == "e2e-proc-001"
            assert "geometry" in doc
            assert doc["geometry"]["area_ha"] > 0


# ---------------------------------------------------------------------------
# E2E Fulfilment — download + post-process writing blobs to Azurite
# ---------------------------------------------------------------------------


@skip_no_azurite
class TestFulfilmentE2E:
    """Phase 3 end-to-end: stub provider download + post-process against Azurite."""

    def test_download_writes_blob_to_azurite(self) -> None:
        """``download_imagery`` writes a GeoTIFF placeholder to Azurite."""
        from treesight.pipeline.fulfilment import download_imagery
        from treesight.providers.planetary_computer import PlanetaryComputerProvider
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        provider = PlanetaryComputerProvider({"stub_mode": True})

        outcome = {
            "order_id": "pc-order-e2e-001",
            "scene_id": "S2B_E2E_TEST",
            "provider": "planetary_computer",
            "aoi_feature_name": "Block A",
            "state": "ready",
        }

        result = download_imagery(
            outcome=outcome,
            provider=provider,
            project_name="e2e-farm",
            timestamp="2026-03-18T12:00:00Z",
            output_container="kml-output",
            storage=storage,
        )

        assert result["blob_path"].endswith(".tif")
        assert result["container"] == "kml-output"
        assert storage.blob_exists("kml-output", result["blob_path"])

        props = storage.get_blob_properties("kml-output", result["blob_path"])
        assert props["content_type"] == "image/tiff"
        assert props["size"] > 0

    def test_post_process_writes_clipped_blob(self) -> None:
        """``post_process_imagery`` writes a clipped blob to Azurite."""
        from treesight.models.aoi import AOI
        from treesight.pipeline.fulfilment import _get_stub_geotiff, post_process_imagery
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        aoi = AOI(
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

        # Pre-upload a valid GeoTIFF so post_process can download_bytes it
        raw_path = "imagery/raw/e2e-farm/ts/Block_A/S2B_E2E_CLIP.tif"
        storage.upload_bytes("kml-output", raw_path, _get_stub_geotiff())

        download_result = {
            "order_id": "pc-order-e2e-002",
            "scene_id": "S2B_E2E_CLIP",
            "blob_path": raw_path,
            "container": "kml-output",
            "size_bytes": 1024,
        }

        result = post_process_imagery(
            download_result=download_result,
            aoi=aoi,
            project_name="e2e-farm",
            timestamp="2026-03-18T12:00:00Z",
            target_crs="EPSG:4326",
            enable_clipping=True,
            enable_reprojection=True,
            output_container="kml-output",
            storage=storage,
        )

        assert result["clipped"] is True
        assert result["clipped_blob_path"].endswith(".tif")
        assert storage.blob_exists("kml-output", result["clipped_blob_path"])

    def test_download_then_post_process_chain(self) -> None:
        """Full chain: download → post-process, both blobs land in Azurite."""
        from treesight.models.aoi import AOI
        from treesight.pipeline.fulfilment import download_imagery, post_process_imagery
        from treesight.providers.planetary_computer import PlanetaryComputerProvider
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        provider = PlanetaryComputerProvider({"stub_mode": True})
        aoi = AOI(
            feature_name="Block B",
            source_file="test.kml",
            feature_index=1,
            exterior_coords=[[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]],
            bbox=[36.8, -1.31, 36.81, -1.3],
            buffered_bbox=[36.79, -1.32, 36.82, -1.29],
            area_ha=12.0,
            centroid=[36.805, -1.305],
            buffer_m=100.0,
            crs="EPSG:4326",
        )

        outcome = {
            "order_id": "pc-order-chain-001",
            "scene_id": "S2B_CHAIN",
            "provider": "planetary_computer",
            "aoi_feature_name": "Block B",
            "state": "ready",
        }

        # Step 1: Download
        dl_result = download_imagery(
            outcome=outcome,
            provider=provider,
            project_name="chain-farm",
            timestamp="2026-03-18T12:00:00Z",
            output_container="kml-output",
            storage=storage,
        )
        assert storage.blob_exists("kml-output", dl_result["blob_path"])

        # Step 2: Post-process
        pp_result = post_process_imagery(
            download_result=dl_result,
            aoi=aoi,
            project_name="chain-farm",
            timestamp="2026-03-18T12:00:00Z",
            target_crs="EPSG:4326",
            enable_clipping=True,
            enable_reprojection=True,
            output_container="kml-output",
            storage=storage,
        )
        assert pp_result["clipped"] is True
        assert storage.blob_exists("kml-output", pp_result["clipped_blob_path"])


# ---------------------------------------------------------------------------
# Payload Offloader — offload / load round-trip against Azurite
# ---------------------------------------------------------------------------


@skip_no_azurite
class TestPayloadOffloaderE2E:
    """``PayloadOffloader`` round-trip against Azurite blob storage."""

    def test_offload_and_load_round_trip(self) -> None:
        """A list of dicts survives offload → load_all unchanged."""
        from typing import Any

        from treesight.storage.client import BlobStorageClient
        from treesight.storage.offload import PayloadOffloader

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        offloader = PayloadOffloader(storage=storage)

        data: list[dict[str, Any]] = [
            {"order_id": "o-1", "scene_id": "S-1", "state": "ready"},
            {"order_id": "o-2", "scene_id": "S-2", "state": "ready"},
        ]

        ref = offloader.offload("e2e-instance-001", data)
        assert "ref" in ref
        assert ref["count"] == 2

        loaded = offloader.load_all(ref["ref"])
        assert loaded == data

    def test_load_single_by_index(self) -> None:
        """``load_single`` retrieves a specific item from offloaded data."""
        from typing import Any

        from treesight.storage.client import BlobStorageClient
        from treesight.storage.offload import PayloadOffloader

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        offloader = PayloadOffloader(storage=storage)

        data: list[dict[str, Any]] = [
            {"idx": 0, "name": "first"},
            {"idx": 1, "name": "second"},
            {"idx": 2, "name": "third"},
        ]

        ref = offloader.offload("e2e-instance-002", data)
        item = offloader.load_single(ref["ref"], 1)

        assert item == {"idx": 1, "name": "second"}

    def test_should_offload_large_payload(self) -> None:
        """``should_offload`` returns True for payloads exceeding the threshold."""
        from treesight.storage.client import BlobStorageClient
        from treesight.storage.offload import PayloadOffloader

        storage = BlobStorageClient(connection_string=AZURITE_CONN_STR)
        offloader = PayloadOffloader(storage=storage)

        small = [{"x": 1}]
        large = [{"data": "x" * 10_000} for _ in range(10)]

        assert not offloader.should_offload(small)
        assert offloader.should_offload(large)
