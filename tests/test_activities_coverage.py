"""Coverage-hardening tests for blueprints/pipeline/activities.py.

Phase 1 of issue #886. Uses mocks to exercise activities without real Azure
storage, Cosmos, or Azure Batch connections.

All activities use lazy imports inside function bodies, so we patch source
modules such as treesight.storage.client.BlobStorageClient.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_aoi_dict(**kwargs) -> dict:
    base = {
        "feature_name": "Block A",
        "source_file": "test.kml",
        "centroid": [36.8, -1.3],
        "bbox": [36.79, -1.31, 36.81, -1.29],
        "buffered_bbox": [36.78, -1.32, 36.82, -1.28],
        "area_ha": 10.0,
        "perimeter_km": 1.2,
        "exterior_coords": [[36.79, -1.31], [36.81, -1.31], [36.81, -1.29], [36.79, -1.29]],
    }
    base.update(kwargs)
    return base


class TestParseKml:
    def test_rejects_non_dict_payload(self):
        from blueprints.pipeline.activities import parse_kml

        with pytest.raises(TypeError, match="parse_kml expects dict payload"):
            parse_kml("not-a-dict")

    def test_rejects_list_payload(self):
        from blueprints.pipeline.activities import parse_kml

        with pytest.raises(TypeError, match="parse_kml expects dict payload"):
            parse_kml(["list"])

    def test_raises_on_too_many_features(self):
        from blueprints.pipeline.activities import parse_kml

        mock_feature = MagicMock()
        mock_feature.model_dump.return_value = {"feature_name": "x"}
        with (
            patch("treesight.models.blob_event.BlobEvent") as mock_blob_event,
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.pipeline.ingestion.parse_kml_from_blob", return_value=[mock_feature] * 2),
            patch("treesight.storage.offload.PayloadOffloader"),
            patch("treesight.constants.MAX_FEATURES_PER_KML", 1),
        ):
            blob_event = MagicMock()
            blob_event.correlation_id = "cid-1"
            mock_blob_event.model_validate.return_value = blob_event
            with pytest.raises(ValueError, match="exceeding the limit"):
                parse_kml({"container": "c", "blob_name": "b.kml", "correlation_id": "cid-1"})

    def test_enforces_tier_limit_before_storing_feature_claims(self):
        from blueprints.pipeline.activities import parse_kml

        feature = MagicMock()
        with (
            patch("treesight.models.blob_event.BlobEvent") as mock_blob_event,
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.pipeline.ingestion.parse_kml_from_blob", return_value=[feature, feature]),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
            patch("treesight.pipeline.ingestion.enforce_aoi_limit", side_effect=ValueError("tier limit")) as gate,
        ):
            blob_event = MagicMock()
            blob_event.correlation_id = "cid-1"
            mock_blob_event.model_validate.return_value = blob_event
            with pytest.raises(ValueError, match="tier limit"):
                parse_kml({"container": "c", "blob_name": "b.kml", "correlation_id": "cid-1", "tier": "free"})

        gate.assert_called_once_with(feature_count=2, tier="free")
        mock_offloader.return_value.store_claim.assert_not_called()

    def test_stores_features_individually_and_returns_bounded_refs(self):
        import json

        from blueprints.pipeline.activities import parse_kml
        from treesight.constants import MAX_FEATURES_PER_KML, PAYLOAD_OFFLOAD_THRESHOLD_BYTES

        feature = MagicMock()
        feature.model_dump.return_value = {"feature_name": "Block A"}
        feature_refs = [f"claims/cid-1/feature_{index}.json" for index in range(MAX_FEATURES_PER_KML)]
        with (
            patch("treesight.models.blob_event.BlobEvent") as mock_blob_event,
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.pipeline.ingestion.parse_kml_from_blob",
                return_value=[feature] * MAX_FEATURES_PER_KML,
            ),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
            patch("treesight.pipeline.ingestion.enforce_aoi_limit"),
        ):
            blob_event = MagicMock()
            blob_event.correlation_id = "cid-1"
            mock_blob_event.model_validate.return_value = blob_event
            offloader = mock_offloader.return_value
            offloader.store_claim.side_effect = feature_refs
            result = parse_kml({"container": "c", "blob_name": "b.kml", "correlation_id": "cid-1"})

        assert result == {"feature_refs": feature_refs}
        assert len(json.dumps(result).encode("utf-8")) < PAYLOAD_OFFLOAD_THRESHOLD_BYTES
        assert offloader.store_claim.call_count == MAX_FEATURES_PER_KML
        offloader.offload.assert_not_called()


# ---------------------------------------------------------------------------
# load_offloaded_features
# ---------------------------------------------------------------------------


class TestLoadOffloadedFeatures:
    def test_loads_from_blob(self):
        from blueprints.pipeline.activities import load_offloaded_features

        expected = [{"feature_name": "x"}]
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
        ):
            offloader_inst = mock_offloader.return_value
            offloader_inst.load_all.return_value = expected
            result = load_offloaded_features({"ref": "blob://ref/path.json"})

        assert result == expected
        offloader_inst.load_all.assert_called_once_with("blob://ref/path.json")


# ---------------------------------------------------------------------------
# prepare_aoi
# ---------------------------------------------------------------------------


class TestPrepareAoi:
    def test_returns_aoi_dict(self):
        from blueprints.pipeline.activities import prepare_aoi

        aoi_mock = MagicMock()
        aoi_mock.model_dump.return_value = {"feature_name": "Field", "area_ha": 10.0}
        aoi_mock.feature_name = "Field"
        aoi_mock.feature_index = 0

        feature_dict = {
            "name": "Field",
            "feature_name": "Field",
            "feature_index": 0,
            "source_file": "test.kml",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[36.79, -1.31], [36.81, -1.31], [36.81, -1.29], [36.79, -1.29], [36.79, -1.31]]],
            },
            "metadata": {},
        }

        with (
            patch("treesight.models.feature.Feature") as mock_feature,
            patch("treesight.geo.prepare_aoi", return_value=aoi_mock),
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/aoi_0.json",
            ),
        ):
            mock_feature.model_validate.return_value = MagicMock()
            result = prepare_aoi({"instance_id": "run", "feature": feature_dict})

        assert result["feature_name"] == "Field"
        assert result["aoi_ref"] == "claims/run/aoi_0.json"
        assert "exterior_coords" not in result

    def test_claim_checks_prepared_geometry_before_returning(self):
        from blueprints.pipeline.activities import prepare_aoi
        from treesight.models.aoi import AOI

        exterior = [[float(index), 0.0] for index in range(10_000)]
        aoi = AOI(feature_name="Field", exterior_coords=exterior, metadata={"supplier_note": "large" * 100_000})
        feature_dict = {"name": "Field", "feature_index": 0, "source_file": "test.kml"}
        with (
            patch("treesight.models.feature.Feature") as mock_feature,
            patch("treesight.geo.prepare_aoi", return_value=aoi),
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/aoi_0.json",
            ) as store_claim,
        ):
            mock_feature.model_validate.return_value = MagicMock()
            result = prepare_aoi({"instance_id": "run", "feature": feature_dict})

        assert result["aoi_ref"] == "claims/run/aoi_0.json"
        assert "exterior_coords" not in result
        assert "metadata" not in result
        store_claim.assert_called_once_with("run", "aoi_0", aoi.model_dump())

    def test_loads_one_feature_from_offloaded_kml_ref(self):
        from blueprints.pipeline.activities import prepare_aoi

        feature_dict = {"name": "Field", "feature_name": "Field", "feature_index": 0}
        aoi = MagicMock()
        aoi.model_dump.return_value = {"feature_name": "Field", "bbox": [0, 0, 1, 1]}
        aoi.feature_index = 0
        with (
            patch("treesight.models.feature.Feature") as mock_feature,
            patch("treesight.geo.prepare_aoi", return_value=aoi),
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.storage.offload.PayloadOffloader.load_claim", return_value=feature_dict) as load_claim,
            patch("treesight.storage.offload.PayloadOffloader.store_claim", return_value="claims/run/aoi_0.json"),
        ):
            mock_feature.model_validate.return_value = MagicMock()
            result = prepare_aoi({"instance_id": "run", "feature_ref": "claims/run/feature_0.json"})

        load_claim.assert_called_once_with("claims/run/feature_0.json")
        assert result["aoi_ref"] == "claims/run/aoi_0.json"


# ---------------------------------------------------------------------------
# write_metadata
# ---------------------------------------------------------------------------


class TestWriteMetadata:
    def test_skips_kml_download_when_no_container(self):
        from blueprints.pipeline.activities import write_metadata

        expected = {"metadata_path": "output/meta.json"}
        aoi_mock = MagicMock()

        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("blueprints.pipeline.activities._load_aoi", return_value=aoi_mock),
            patch("treesight.pipeline.ingestion.write_metadata", return_value=expected),
        ):
            result = write_metadata(
                {
                    "aoi": _make_aoi_dict(),
                    "processing_id": "proc-1",
                    "timestamp": "2024-06-01T00:00:00Z",
                    "source_file": "test.kml",
                    "output_container": "output",
                    "input_container": "",
                }
            )

        assert result == expected

    def test_kml_download_failure_is_tolerated(self):
        from blueprints.pipeline.activities import write_metadata

        aoi_mock = MagicMock()

        with (
            patch("treesight.storage.client.BlobStorageClient") as mock_storage,
            patch("blueprints.pipeline.activities._load_aoi", return_value=aoi_mock),
            patch("treesight.pipeline.ingestion.write_metadata", return_value={"ok": True}),
        ):
            storage_inst = mock_storage.return_value
            storage_inst.download_bytes.side_effect = RuntimeError("Network error")

            result = write_metadata(
                {
                    "aoi": _make_aoi_dict(),
                    "processing_id": "proc-1",
                    "timestamp": "2024-06-01T00:00:00Z",
                    "source_file": "test.kml",
                    "output_container": "output",
                    "input_container": "kml-input",
                }
            )

        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# store_aoi_claims / load_aoi_claim
# ---------------------------------------------------------------------------


class TestStoreAoiClaims:
    def test_stores_and_returns_refs(self):
        from blueprints.pipeline.activities import store_aoi_claims

        expected = [{"ref": "claims/inst/0.json", "key": "Block A"}]
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
        ):
            mock_offloader.return_value.store_claims_batch.return_value = expected
            result = store_aoi_claims(
                {
                    "instance_id": "inst-1",
                    "aois": [_make_aoi_dict()],
                }
            )

        assert result == expected


class TestLoadAoiClaim:
    def test_loads_by_aoi_ref(self):
        from blueprints.pipeline.activities import load_aoi_claim

        expected = _make_aoi_dict()
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
        ):
            mock_offloader.return_value.load_claim.return_value = expected
            result = load_aoi_claim({"aoi_ref": "claims/inst/0.json"})

        assert result == expected

    def test_loads_by_ref_when_no_aoi_ref(self):
        from blueprints.pipeline.activities import load_aoi_claim

        expected = _make_aoi_dict()
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
        ):
            mock_offloader.return_value.load_claim.return_value = expected
            result = load_aoi_claim({"ref": "claims/inst/0.json"})

        assert result == expected


# ---------------------------------------------------------------------------
# acquire_imagery / acquire_composite
# ---------------------------------------------------------------------------


class TestAcquireImagery:
    def test_acquires_with_default_provider(self):
        from blueprints.pipeline.activities import acquire_imagery

        mock_result = {"order_id": "ord-1", "scene_id": "sc-1"}

        with (
            patch("blueprints.pipeline.activities._load_aoi") as mock_load,
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch("treesight.pipeline.acquisition.acquire_imagery", return_value=mock_result),
        ):
            mock_load.return_value = MagicMock()
            mock_get_prov.return_value = MagicMock()
            result = acquire_imagery({"aoi": _make_aoi_dict()})

        assert result == mock_result

    def test_acquires_with_custom_imagery_filters(self):
        from blueprints.pipeline.activities import acquire_imagery

        mock_result = {"order_id": "ord-2", "scene_id": "sc-2"}

        with (
            patch("blueprints.pipeline.activities._load_aoi") as mock_load,
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch("treesight.pipeline.acquisition.acquire_imagery", return_value=mock_result),
        ):
            mock_load.return_value = MagicMock()
            mock_get_prov.return_value = MagicMock()

            result = acquire_imagery(
                {
                    "aoi": _make_aoi_dict(),
                    "imagery_filters": {"max_cloud_cover_pct": 10.0},
                }
            )

        assert result == mock_result


class TestAcquireComposite:
    def test_composite_with_temporal_count(self):
        from blueprints.pipeline.activities import acquire_composite

        mock_result = [{"order_id": "ord-1"}]

        with (
            patch("blueprints.pipeline.activities._load_aoi") as mock_load,
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch("treesight.pipeline.acquisition.acquire_composite", return_value=mock_result),
        ):
            mock_load.return_value = MagicMock()
            mock_get_prov.return_value = MagicMock()
            result = acquire_composite(
                {
                    "aoi": _make_aoi_dict(),
                    "temporal_count": 3,
                }
            )

        assert result == mock_result


# ---------------------------------------------------------------------------
# check_order_status
# ---------------------------------------------------------------------------


class TestCheckOrderStatus:
    def test_check_returns_status_dict(self):
        from blueprints.pipeline.activities import check_order_status

        with (
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch(
                "treesight.pipeline.acquisition.check_order_status",
                return_value={
                    "state": "ready",
                    "is_terminal": True,
                    "order_id": "ord-1",
                    "provider": "stub",
                    "error": None,
                },
            ),
        ):
            mock_get_prov.return_value = MagicMock()
            result = check_order_status(
                {
                    "order_id": "ord-1",
                    "scene_id": "sc-1",
                    "aoi_feature_name": "Block A",
                }
            )

        assert result["state"] == "ready"
        assert result["is_terminal"] is True
        assert result["scene_id"] == "sc-1"
        assert result["aoi_feature_name"] == "Block A"

    def test_check_propagates_order_id(self):
        from blueprints.pipeline.activities import check_order_status

        with (
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch(
                "treesight.pipeline.acquisition.check_order_status",
                return_value={
                    "state": "pending",
                    "is_terminal": False,
                    "order_id": "ord-2",
                    "provider": "stub",
                    "error": None,
                },
            ) as mock_check,
        ):
            mock_get_prov.return_value = MagicMock()
            check_order_status({"order_id": "ord-2"})

        assert mock_check.call_args.args[0] == "ord-2"


# ---------------------------------------------------------------------------
# download_imagery
# ---------------------------------------------------------------------------


class TestDownloadImagery:
    def test_download_with_inline_aoi_bbox(self):
        from blueprints.pipeline.activities import download_imagery

        with (
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.pipeline.fulfilment.download_imagery",
                return_value={"state": "completed"},
            ),
        ):
            mock_get_prov.return_value = MagicMock()
            result = download_imagery(
                {
                    "outcome": {"order_id": "ord-1"},
                    "aoi_bbox": [36.78, -1.32, 36.82, -1.28],
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                    "output_container": "output",
                }
            )

        assert result["state"] == "completed"

    def test_download_resolves_aoi_bbox_from_claim(self):
        from blueprints.pipeline.activities import download_imagery

        aoi_mock = MagicMock()
        aoi_mock.buffered_bbox = [36.78, -1.32, 36.82, -1.28]

        with (
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch("treesight.storage.client.BlobStorageClient"),
            patch("blueprints.pipeline.activities._load_aoi", return_value=aoi_mock),
            patch(
                "treesight.pipeline.fulfilment.download_imagery",
                return_value={"state": "completed"},
            ),
        ):
            mock_get_prov.return_value = MagicMock()
            result = download_imagery(
                {
                    "outcome": {"order_id": "ord-1"},
                    "aoi_ref": "claims/inst/0.json",
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                    "output_container": "output",
                }
            )

        assert result["state"] == "completed"


# ---------------------------------------------------------------------------
# post_process_imagery
# ---------------------------------------------------------------------------


class TestPostProcessImagery:
    def test_delegates_to_post_process(self):
        from blueprints.pipeline.activities import post_process_imagery

        expected = {"state": "completed", "clipped": True}
        aoi_mock = MagicMock()

        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("blueprints.pipeline.activities._load_aoi", return_value=aoi_mock),
            patch(
                "treesight.pipeline.fulfilment.post_process_imagery",
                return_value=expected,
            ),
        ):
            result = post_process_imagery(
                {
                    "aoi": _make_aoi_dict(),
                    "download_result": {"blob_path": "imagery/raw/ord.tif"},
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                    "output_container": "output",
                }
            )

        assert result["clipped"] is True


# ---------------------------------------------------------------------------
# run_enrichment
# ---------------------------------------------------------------------------


class TestRunEnrichment:
    def test_delegates_to_enrich(self):
        from blueprints.pipeline.activities import run_enrichment

        expected = {"ndvi": 0.6}
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.pipeline.enrichment.run_enrichment", return_value=expected),
        ):
            result = run_enrichment(
                {
                    "coords": [[36.8, -1.3]],
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == expected


# ---------------------------------------------------------------------------
# enrich_data_sources
# ---------------------------------------------------------------------------


class TestEnrichDataSources:
    def test_safe_mode_skips_external_sources(self):
        from blueprints.pipeline.activities import enrich_data_sources

        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_data_sources({"per_aoi_coords": [{"aoi_ref": "claims/run/aoi-0.json"}]})

        assert result["safe_mode"] is True
        assert "weather" in result["skipped"]

    def test_normal_mode_calls_enrich_ds(self):
        from blueprints.pipeline.activities import enrich_data_sources

        per_aoi_refs = [{"aoi_ref": "claims/run/aoi-0.json"}]
        hydrated = [{"coords": [[36.8, -1.3]], "interior_coords": []}]
        with (
            patch("treesight.config.SAFE_MODE", False),
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "blueprints.pipeline._payloads._hydrate_per_aoi_enrichment_coords",
                return_value=hydrated,
            ),
            patch(
                "treesight.pipeline.enrichment.enrich_data_sources",
                return_value={"weather": {}},
            ) as mock_ds,
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/enrichment_data_sources.json",
            ) as store_claim,
        ):
            result = enrich_data_sources(
                {
                    "per_aoi_coords": per_aoi_refs,
                    "instance_id": "run",
                    "eudr_mode": False,
                }
            )

        mock_ds.assert_called_once()
        assert mock_ds.call_args.args[0] == [[36.8, -1.3]]
        assert mock_ds.call_args.kwargs["per_aoi_coords"] == hydrated
        assert result == {"result_ref": "claims/run/enrichment_data_sources.json"}
        store_claim.assert_called_once_with("run", "enrichment_data_sources", {"weather": {}})

    def test_activity_result_omits_large_run_coordinates(self):
        from blueprints.pipeline.activities import enrich_data_sources

        coords = [[float(index), 0.0] for index in range(10_000)]
        with (
            patch("treesight.config.SAFE_MODE", False),
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "blueprints.pipeline._payloads._hydrate_per_aoi_enrichment_coords",
                return_value=[{"coords": coords, "interior_coords": []}],
            ),
            patch(
                "treesight.pipeline.enrichment.enrich_data_sources",
                return_value={"coords": coords, "bbox": [0, 0, 1, 1]},
            ),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/enrichment_data_sources.json",
            ) as store_claim,
        ):
            result = enrich_data_sources(
                {"instance_id": "run", "per_aoi_coords": [{"aoi_ref": "claims/run/aoi-0.json"}]}
            )

        assert result == {"result_ref": "claims/run/enrichment_data_sources.json"}
        stored = store_claim.call_args.args[2]
        assert "coords" not in stored
        assert stored["bbox"] == [0, 0, 1, 1]


# ---------------------------------------------------------------------------
# enrich_imagery
# ---------------------------------------------------------------------------


class TestEnrichImagery:
    def test_delegates_to_enrich_img(self):
        from blueprints.pipeline.activities import enrich_imagery

        expected = {"mosaic": "registered"}
        hydrated = [{"coords": [[36.8, -1.3]], "interior_coords": []}]
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "blueprints.pipeline._payloads._hydrate_per_aoi_enrichment_coords",
                return_value=hydrated,
            ),
            patch("treesight.pipeline.enrichment.enrich_imagery", return_value=expected),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/enrichment_imagery.json",
            ),
        ):
            result = enrich_imagery(
                {
                    "per_aoi_coords": [{"aoi_ref": "claims/run/aoi-0.json"}],
                    "instance_id": "run",
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == {"result_ref": "claims/run/enrichment_imagery.json"}


# ---------------------------------------------------------------------------
# enrich_single_aoi


class TestEnrichSingleAoi:
    def test_delegates_to_enrich_aoi(self):
        from blueprints.pipeline.activities import enrich_single_aoi
        from treesight.models.aoi import AOI

        expected = {"ndvi_mean": 0.7}
        aoi_entry = {"name": "Block A", "aoi_ref": "claims/run/aoi-0.json"}
        loaded_aoi = AOI(
            feature_name="Block A",
            area_ha=15.2,
            exterior_coords=[[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]],
            interior_coords=[[[36.805, -1.305], [36.806, -1.305], [36.805, -1.305]]],
            metadata={"source_geometry_type": "Polygon", "plot_area_ha": "14.8"},
        )
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("blueprints.pipeline.activities._load_aoi", return_value=loaded_aoi),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/enrichment-aoi-0.json",
            ),
            patch(
                "treesight.pipeline.enrichment.enrich_single_aoi_step",
                return_value=expected,
            ) as enrich_step,
        ):
            result = enrich_single_aoi(
                {
                    "aoi_entry": aoi_entry,
                    "instance_id": "run",
                    "aoi_index": 0,
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == {"result_ref": "claims/run/enrichment-aoi-0.json"}
        hydrated_entry = enrich_step.call_args.args[0]
        assert hydrated_entry["name"] == "Block A"
        assert hydrated_entry["area_ha"] == 15.2
        assert hydrated_entry["source_geometry_type"] == "Polygon"
        assert hydrated_entry["plot_area_ha"] == 14.8

    def test_stores_large_activity_result_by_claim_ref(self):
        from blueprints.pipeline.activities import enrich_single_aoi
        from treesight.models.aoi import AOI

        enrichment = {"frame_plan": [{"start": "2021-01-01"}] * 500, "ndvi_stats": [{"mean": 0.5}] * 500}
        loaded_aoi = AOI(feature_name="Block A", exterior_coords=[[0, 0], [1, 0], [1, 1], [0, 0]])
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("blueprints.pipeline.activities._load_aoi", return_value=loaded_aoi),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/enrichment-aoi-3.json",
            ) as store_claim,
            patch("treesight.pipeline.enrichment.enrich_single_aoi_step", return_value=enrichment),
        ):
            result = enrich_single_aoi(
                {
                    "aoi_entry": {"name": "Block A", "aoi_ref": "claims/run/aoi-3.json"},
                    "instance_id": "run",
                    "aoi_index": 3,
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == {"result_ref": "claims/run/enrichment-aoi-3.json"}
        store_claim.assert_called_once_with("run", "enrichment_aoi_3", enrichment)

    def test_bbox_only_claim_preserves_fallback_coords_without_geometry(self):
        from blueprints.pipeline.activities import enrich_single_aoi
        from treesight.models.aoi import AOI

        fallback_coords = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        loaded_aoi = AOI(feature_name="Box", exterior_coords=[])
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("blueprints.pipeline.activities._load_aoi", return_value=loaded_aoi),
            patch(
                "treesight.storage.offload.PayloadOffloader.store_claim",
                return_value="claims/run/enrichment-aoi-0.json",
            ),
            patch("treesight.pipeline.enrichment.enrich_single_aoi_step", return_value={}) as enrich,
        ):
            enrich_single_aoi(
                {
                    "aoi_entry": {
                        "name": "Box",
                        "aoi_ref": "claims/run/aoi-0.json",
                        "coords": fallback_coords,
                    },
                    "instance_id": "run",
                    "aoi_index": 0,
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        hydrated_entry = enrich.call_args.args[0]
        assert hydrated_entry["coords"] == fallback_coords
        assert hydrated_entry["interior_coords"] is None


# ---------------------------------------------------------------------------
# enrich_finalize
# ---------------------------------------------------------------------------


class TestEnrichFinalize:
    def test_delegates_to_finalize(self):
        from blueprints.pipeline.activities import enrich_finalize

        expected = {"manifest_path": "output/manifest.json"}
        per_aoi_refs = [{"name": "Solo", "aoi_ref": "claims/run/aoi-0.json", "area_ha": 1}]
        hydrated = [{"name": "Solo", "coords": [[1, 2]], "interior_coords": [], "area_ha": 1}]
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "blueprints.pipeline._payloads._hydrate_per_aoi_enrichment_coords",
                return_value=hydrated,
            ),
            patch("treesight.pipeline.enrichment.enrich_finalize", return_value=expected) as finalize,
        ):
            result = enrich_finalize(
                {
                    "data_sources": {},
                    "imagery": {},
                    "per_aoi_coords": per_aoi_refs,
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == expected
        assert finalize.call_args.kwargs["per_aoi_coords"] == hydrated

    def test_returns_compact_summary_instead_of_manifest_geometry(self):
        from blueprints.pipeline.activities import enrich_finalize

        manifest = {
            "manifest_path": "output/manifest.json",
            "resource_usage": {"api_calls": 2},
            "estimated_cost_pence": 3,
            "enrichment_duration_seconds": 4.0,
            "ndvi_stats": [{"mean": 0.5}],
            "weather_daily": {"dates": ["2024-01-01"]},
            "per_aoi_enrichment": [{"geometry": {"coordinates": [[[0, 0], [1, 1]]]}}],
        }
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.pipeline.enrichment.enrich_finalize", return_value=manifest),
        ):
            result = enrich_finalize(
                {
                    "data_sources": {},
                    "imagery": {},
                    "per_aoi_coords": [],
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == {
            "manifest_path": "output/manifest.json",
            "resource_usage": {"api_calls": 2},
            "estimated_cost_pence": 3,
            "enrichment_duration_seconds": 4.0,
            "ndvi_stats": True,
            "weather_daily": True,
        }


# ---------------------------------------------------------------------------
# submit_batch_fulfilment / poll_batch_fulfilment
# ---------------------------------------------------------------------------


class TestBatchActivities:
    def test_submit_batch_delegates(self):
        from blueprints.pipeline.activities import submit_batch_fulfilment

        expected = {"job_id": "job-1", "task_id": "task-1"}
        with patch("treesight.pipeline.batch.submit_batch_job", return_value=expected):
            result = submit_batch_fulfilment(
                {
                    "outcome": {"order_id": "ord-1", "aoi_feature_name": "Block A"},
                    "asset_url": "https://storage/img.tif",
                    "output_container": "output",
                    "project_name": "farm",
                    "timestamp": "2024-06-01T00:00:00Z",
                }
            )

        assert result == expected

    def test_poll_batch_delegates(self):
        from blueprints.pipeline.activities import poll_batch_fulfilment

        expected = {"state": "completed"}
        with patch("treesight.pipeline.batch.poll_batch_task", return_value=expected):
            result = poll_batch_fulfilment({"job_id": "job-1", "task_id": "task-1"})

        assert result == expected


# ---------------------------------------------------------------------------
# complete_billing / fail_billing
# ---------------------------------------------------------------------------


class TestBillingActivities:
    def test_complete_billing(self):
        from blueprints.pipeline.activities import complete_billing

        with patch("treesight.security.billing_ledger.complete_run_billing") as mock_fn:
            result = complete_billing({"user_id": "u1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with("u1", "inst-1")
        assert result == {"completed": True}

    def test_fail_billing_default_reason(self):
        from blueprints.pipeline.activities import fail_billing

        with patch("treesight.security.billing_ledger.fail_run_billing") as mock_fn:
            result = fail_billing({"user_id": "u1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with("u1", "inst-1", reason="pipeline_failure")
        assert result == {"refunded": True}

    def test_fail_billing_custom_reason(self):
        from blueprints.pipeline.activities import fail_billing

        with patch("treesight.security.billing_ledger.fail_run_billing") as mock_fn:
            result = fail_billing(
                {
                    "user_id": "u1",
                    "instance_id": "inst-1",
                    "reason": "timeout",
                }
            )

        mock_fn.assert_called_once_with("u1", "inst-1", reason="timeout")
        assert result == {"refunded": True}


# ---------------------------------------------------------------------------
# finalize_run_completed / finalize_run_failed
# ---------------------------------------------------------------------------


class TestFinalizeRun:
    def test_finalize_completed_success(self):
        from blueprints.pipeline.activities import finalize_run_completed

        with (
            patch("treesight.billing.accounting.finalize_run") as mock_fn,
            patch("treesight.pipeline.concurrency.release_admission_slot") as release_mock,
        ):
            result = finalize_run_completed({"org_id": "org-1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with(org_id="org-1", instance_id="inst-1", status="completed")
        release_mock.assert_called_once_with("inst-1")
        assert result == {"finalized": True, "status": "completed"}

    def test_finalize_completed_raises_on_error(self):
        from blueprints.pipeline.activities import finalize_run_completed

        with (
            patch(
                "treesight.billing.accounting.finalize_run",
                side_effect=RuntimeError("boom"),
            ),
            patch("treesight.pipeline.concurrency.release_admission_slot") as release_mock,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                finalize_run_completed({"org_id": "org-1", "instance_id": "inst-1"})
        release_mock.assert_called_once_with("inst-1")

    def test_finalize_failed_success(self):
        from blueprints.pipeline.activities import finalize_run_failed

        with (
            patch("treesight.billing.accounting.finalize_run") as mock_fn,
            patch("treesight.pipeline.concurrency.release_admission_slot") as release_mock,
        ):
            result = finalize_run_failed({"org_id": "org-1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with(org_id="org-1", instance_id="inst-1", status="failed")
        release_mock.assert_called_once_with("inst-1")
        assert result == {"finalized": True, "status": "failed"}

    def test_finalize_failed_raises_on_error(self):
        from blueprints.pipeline.activities import finalize_run_failed

        with (
            patch(
                "treesight.billing.accounting.finalize_run",
                side_effect=ValueError("db error"),
            ),
            patch("treesight.pipeline.concurrency.release_admission_slot") as release_mock,
        ):
            with pytest.raises(ValueError, match="db error"):
                finalize_run_failed({"org_id": "org-1", "instance_id": "inst-1"})
        release_mock.assert_called_once_with("inst-1")


# ---------------------------------------------------------------------------
# write_pipeline_stats
# ---------------------------------------------------------------------------


class TestWritePipelineStats:
    def test_returns_not_written_when_cosmos_unavailable(self):
        from blueprints.pipeline.activities import write_pipeline_stats

        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            result = write_pipeline_stats({"instance_id": "inst-1"})

        assert result == {"written": False, "reason": "cosmos_unavailable"}

    def test_returns_written_on_success(self):
        from blueprints.pipeline.activities import write_pipeline_stats

        doc = {"instance_id": "inst-1", "aoi_count": 2}
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.pipeline.telemetry.build_stats_document", return_value=doc),
            patch("treesight.storage.cosmos.upsert_item"),
        ):
            result = write_pipeline_stats(
                {
                    "instance_id": "inst-1",
                    "aoi_count": 2,
                    "user_id": "u1",
                    "tier": "pro",
                    "aoi_area_by_name": {},
                    "aoi_centroids": [],
                }
            )

        assert result == {"written": True, "instance_id": "inst-1"}

    def test_returns_not_written_on_exception(self):
        from blueprints.pipeline.activities import write_pipeline_stats

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.pipeline.telemetry.build_stats_document",
                side_effect=RuntimeError("Cosmos down"),
            ),
        ):
            result = write_pipeline_stats({"instance_id": "inst-1"})

        assert result == {"written": False, "reason": "error"}
