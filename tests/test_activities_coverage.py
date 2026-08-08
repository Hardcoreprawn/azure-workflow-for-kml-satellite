"""Coverage-hardening tests for blueprints/pipeline/activities.py.

Phase 1 of issue #886.  Uses mocks to exercise the activity functions
without real Azure storage, Cosmos, or Azure Batch connections.

All activities use lazy imports inside function bodies, so we patch the
source modules (e.g. treesight.storage.client.BlobStorageClient) rather
than the activities module itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# parse_kml
# ---------------------------------------------------------------------------


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
        many_features = [mock_feature] * 2

        with (
            patch("treesight.models.blob_event.BlobEvent") as mock_blob_event,
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.pipeline.ingestion.parse_kml_from_blob",
                return_value=many_features,
            ),
            patch("treesight.storage.offload.PayloadOffloader"),
            patch("treesight.constants.MAX_FEATURES_PER_KML", 1),
        ):
            blob_evt = MagicMock()
            blob_evt.correlation_id = "cid-1"
            mock_blob_event.model_validate.return_value = blob_evt

            with pytest.raises(ValueError, match="exceeding the limit"):
                parse_kml({"container": "c", "blob_name": "b.kml", "correlation_id": "cid-1"})

    def test_returns_offloaded_ref_when_large(self):
        from blueprints.pipeline.activities import parse_kml

        mock_feature = MagicMock()
        mock_feature.model_dump.return_value = {"feature_name": "x"}
        features = [mock_feature]

        with (
            patch("treesight.models.blob_event.BlobEvent") as mock_blob_event,
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.pipeline.ingestion.parse_kml_from_blob",
                return_value=features,
            ),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
            patch("treesight.constants.MAX_FEATURES_PER_KML", 100),
        ):
            blob_evt = MagicMock()
            blob_evt.correlation_id = "cid-1"
            mock_blob_event.model_validate.return_value = blob_evt
            offloader_inst = mock_offloader.return_value
            offloader_inst.should_offload.return_value = True
            offloader_inst.offload.return_value = {"ref": "blob://..."}

            result = parse_kml({"container": "c", "blob_name": "b.kml", "correlation_id": "cid-1"})

        assert result == {"ref": "blob://..."}

    def test_returns_feature_list_when_small(self):
        from blueprints.pipeline.activities import parse_kml

        mock_feature = MagicMock()
        mock_feature.model_dump.return_value = {"feature_name": "Block A"}
        features = [mock_feature]

        with (
            patch("treesight.models.blob_event.BlobEvent") as mock_blob_event,
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.pipeline.ingestion.parse_kml_from_blob",
                return_value=features,
            ),
            patch("treesight.storage.offload.PayloadOffloader") as mock_offloader,
            patch("treesight.constants.MAX_FEATURES_PER_KML", 100),
        ):
            blob_evt = MagicMock()
            blob_evt.correlation_id = "cid-1"
            mock_blob_event.model_validate.return_value = blob_evt
            offloader_inst = mock_offloader.return_value
            offloader_inst.should_offload.return_value = False

            result = parse_kml({"container": "c", "blob_name": "b.kml", "correlation_id": "cid-1"})

        assert result == [{"feature_name": "Block A"}]


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

        feature_dict = {
            "name": "Field",
            "feature_name": "Field",
            "feature_index": 0,
            "source_file": "test.kml",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[36.79, -1.31], [36.81, -1.31], [36.81, -1.29], [36.79, -1.29], [36.79, -1.31]]
                ],
            },
            "metadata": {},
        }

        with (
            patch("treesight.models.feature.Feature") as mock_feature,
            patch("treesight.geo.prepare_aoi", return_value=aoi_mock),
        ):
            mock_feature.model_validate.return_value = MagicMock()
            result = prepare_aoi({"feature": feature_dict})

        assert result["feature_name"] == "Field"


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
            result = write_metadata({
                "aoi": _make_aoi_dict(),
                "processing_id": "proc-1",
                "timestamp": "2024-06-01T00:00:00Z",
                "source_file": "test.kml",
                "output_container": "output",
                "input_container": "",
            })

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

            result = write_metadata({
                "aoi": _make_aoi_dict(),
                "processing_id": "proc-1",
                "timestamp": "2024-06-01T00:00:00Z",
                "source_file": "test.kml",
                "output_container": "output",
                "input_container": "kml-input",
            })

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
            result = store_aoi_claims({
                "instance_id": "inst-1",
                "aois": [_make_aoi_dict()],
            })

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

            result = acquire_imagery({
                "aoi": _make_aoi_dict(),
                "imagery_filters": {"max_cloud_cover_pct": 10.0},
            })

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
            result = acquire_composite({
                "aoi": _make_aoi_dict(),
                "temporal_count": 3,
            })

        assert result == mock_result


# ---------------------------------------------------------------------------
# poll_order
# ---------------------------------------------------------------------------


class TestPollOrder:
    def test_poll_returns_outcome_dict(self):
        from blueprints.pipeline.activities import poll_order

        outcome_mock = MagicMock()
        outcome_mock.model_dump.return_value = {"state": "ready", "message": "ok"}

        with (
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch("treesight.pipeline.acquisition.poll_order", return_value=outcome_mock),
        ):
            mock_get_prov.return_value = MagicMock()
            result = poll_order({
                "order_id": "ord-1",
                "scene_id": "sc-1",
                "aoi_feature_name": "Block A",
            })

        assert result["state"] == "ready"

    def test_poll_passes_override_params(self):
        from blueprints.pipeline.activities import poll_order

        outcome_mock = MagicMock()
        outcome_mock.model_dump.return_value = {"state": "ready"}

        with (
            patch("treesight.providers.registry.get_provider") as mock_get_prov,
            patch(
                "treesight.pipeline.acquisition.poll_order", return_value=outcome_mock
            ) as mock_poll,
        ):
            mock_get_prov.return_value = MagicMock()
            poll_order({
                "order_id": "ord-2",
                "overrides": {"poll_interval_seconds": 10, "poll_timeout_seconds": 600},
            })

        call_kwargs = mock_poll.call_args.kwargs
        assert call_kwargs["poll_interval"] == 10
        assert call_kwargs["poll_timeout"] == 600


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
            result = download_imagery({
                "outcome": {"order_id": "ord-1"},
                "aoi_bbox": [36.78, -1.32, 36.82, -1.28],
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
                "output_container": "output",
            })

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
            result = download_imagery({
                "outcome": {"order_id": "ord-1"},
                "aoi_ref": "claims/inst/0.json",
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
                "output_container": "output",
            })

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
            result = post_process_imagery({
                "aoi": _make_aoi_dict(),
                "download_result": {"blob_path": "imagery/raw/ord.tif"},
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
                "output_container": "output",
            })

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
            result = run_enrichment({
                "coords": [[36.8, -1.3]],
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
            })

        assert result == expected


# ---------------------------------------------------------------------------
# enrich_data_sources
# ---------------------------------------------------------------------------


class TestEnrichDataSources:
    def test_safe_mode_skips_external_sources(self):
        from blueprints.pipeline.activities import enrich_data_sources

        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_data_sources({"coords": [[36.8, -1.3]]})

        assert result["safe_mode"] is True
        assert "weather" in result["skipped"]

    def test_normal_mode_calls_enrich_ds(self):
        from blueprints.pipeline.activities import enrich_data_sources

        with (
            patch("treesight.config.SAFE_MODE", False),
            patch(
                "treesight.pipeline.enrichment.enrich_data_sources",
                return_value={"weather": {}},
            ) as mock_ds,
        ):
            result = enrich_data_sources({
                "coords": [[36.8, -1.3]],
                "eudr_mode": False,
            })

        mock_ds.assert_called_once()
        assert "weather" in result


# ---------------------------------------------------------------------------
# enrich_imagery
# ---------------------------------------------------------------------------


class TestEnrichImagery:
    def test_delegates_to_enrich_img(self):
        from blueprints.pipeline.activities import enrich_imagery

        expected = {"mosaic": "registered"}
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.pipeline.enrichment.enrich_imagery", return_value=expected),
        ):
            result = enrich_imagery({
                "coords": [[36.8, -1.3]],
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
            })

        assert result == expected


# ---------------------------------------------------------------------------
# enrich_single_aoi
# ---------------------------------------------------------------------------


class TestEnrichSingleAoi:
    def test_delegates_to_enrich_aoi(self):
        from blueprints.pipeline.activities import enrich_single_aoi

        expected = {"ndvi_mean": 0.7}
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch(
                "treesight.pipeline.enrichment.enrich_single_aoi_step",
                return_value=expected,
            ),
        ):
            result = enrich_single_aoi({
                "aoi_entry": {"name": "Block A", "coords": [[36.8, -1.3]]},
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
            })

        assert result == expected


# ---------------------------------------------------------------------------
# enrich_finalize
# ---------------------------------------------------------------------------


class TestEnrichFinalize:
    def test_delegates_to_finalize(self):
        from blueprints.pipeline.activities import enrich_finalize

        expected = {"manifest_path": "output/manifest.json"}
        with (
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.pipeline.enrichment.enrich_finalize", return_value=expected),
        ):
            result = enrich_finalize({
                "data_sources": {},
                "imagery": {},
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
            })

        assert result == expected


# ---------------------------------------------------------------------------
# submit_batch_fulfilment / poll_batch_fulfilment
# ---------------------------------------------------------------------------


class TestBatchActivities:
    def test_submit_batch_delegates(self):
        from blueprints.pipeline.activities import submit_batch_fulfilment

        expected = {"job_id": "job-1", "task_id": "task-1"}
        with patch("treesight.pipeline.batch.submit_batch_job", return_value=expected):
            result = submit_batch_fulfilment({
                "outcome": {"order_id": "ord-1", "aoi_feature_name": "Block A"},
                "asset_url": "https://storage/img.tif",
                "output_container": "output",
                "project_name": "farm",
                "timestamp": "2024-06-01T00:00:00Z",
            })

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

        with patch(
            "treesight.security.billing_ledger.complete_run_billing"
        ) as mock_fn:
            result = complete_billing({"user_id": "u1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with("u1", "inst-1")
        assert result == {"completed": True}

    def test_fail_billing_default_reason(self):
        from blueprints.pipeline.activities import fail_billing

        with patch(
            "treesight.security.billing_ledger.fail_run_billing"
        ) as mock_fn:
            result = fail_billing({"user_id": "u1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with("u1", "inst-1", reason="pipeline_failure")
        assert result == {"refunded": True}

    def test_fail_billing_custom_reason(self):
        from blueprints.pipeline.activities import fail_billing

        with patch(
            "treesight.security.billing_ledger.fail_run_billing"
        ) as mock_fn:
            result = fail_billing({
                "user_id": "u1",
                "instance_id": "inst-1",
                "reason": "timeout",
            })

        mock_fn.assert_called_once_with("u1", "inst-1", reason="timeout")
        assert result == {"refunded": True}


# ---------------------------------------------------------------------------
# finalize_run_completed / finalize_run_failed
# ---------------------------------------------------------------------------


class TestFinalizeRun:
    def test_finalize_completed_success(self):
        from blueprints.pipeline.activities import finalize_run_completed

        with patch("treesight.billing.accounting.finalize_run") as mock_fn:
            result = finalize_run_completed({"org_id": "org-1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with(org_id="org-1", instance_id="inst-1", status="completed")
        assert result == {"finalized": True, "status": "completed"}

    def test_finalize_completed_raises_on_error(self):
        from blueprints.pipeline.activities import finalize_run_completed

        with patch(
            "treesight.billing.accounting.finalize_run",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                finalize_run_completed({"org_id": "org-1", "instance_id": "inst-1"})

    def test_finalize_failed_success(self):
        from blueprints.pipeline.activities import finalize_run_failed

        with patch("treesight.billing.accounting.finalize_run") as mock_fn:
            result = finalize_run_failed({"org_id": "org-1", "instance_id": "inst-1"})

        mock_fn.assert_called_once_with(org_id="org-1", instance_id="inst-1", status="failed")
        assert result == {"finalized": True, "status": "failed"}

    def test_finalize_failed_raises_on_error(self):
        from blueprints.pipeline.activities import finalize_run_failed

        with patch(
            "treesight.billing.accounting.finalize_run",
            side_effect=ValueError("db error"),
        ):
            with pytest.raises(ValueError, match="db error"):
                finalize_run_failed({"org_id": "org-1", "instance_id": "inst-1"})


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
            result = write_pipeline_stats({
                "instance_id": "inst-1",
                "aoi_count": 2,
                "user_id": "u1",
                "tier": "pro",
                "aoi_area_by_name": {},
                "aoi_centroids": [],
            })

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
