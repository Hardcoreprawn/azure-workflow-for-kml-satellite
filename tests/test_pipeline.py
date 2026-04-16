"""Tests for pipeline modules — orchestrator helpers (§3)."""

from __future__ import annotations

import contextlib
import json
from unittest.mock import MagicMock

from blueprints.pipeline._helpers import (
    _acq_payload,
    _aggregate_aoi_results,
    _download_payload,
    _poll_payload,
    _post_process_payload,
)
from blueprints.pipeline.history import _parse_history_limit, _parse_history_offset
from treesight.pipeline.orchestrator import (
    build_pipeline_summary,
    derive_project_context,
    get_batch_config,
)
from treesight.storage.offload import PayloadOffloader


class TestDeriveProjectContext:
    def test_extracts_stem(self):
        ctx = derive_project_context("uploads/my-farm.kml")
        assert ctx["project_name"] == "my-farm"

    def test_timestamp_format(self):
        ctx = derive_project_context("test.kml")
        assert "T" in ctx["timestamp"]
        assert ctx["timestamp"].endswith("Z")

    def test_nested_path(self):
        ctx = derive_project_context("a/b/c/orchard.kml")
        assert ctx["project_name"] == "orchard"


class TestGetBatchConfig:
    def test_defaults(self):
        cfg = get_batch_config({})
        assert cfg["poll_batch_size"] == 10
        assert cfg["download_batch_size"] == 10
        assert cfg["post_process_batch_size"] == 10

    def test_overrides(self):
        cfg = get_batch_config(
            {
                "poll_batch_size": 5,
                "download_batch_size": "20",
                "post_process_batch_size": 4.0,
            }
        )
        assert cfg["poll_batch_size"] == 5
        assert cfg["download_batch_size"] == 20
        assert cfg["post_process_batch_size"] == 4


class TestBuildPipelineSummary:
    def test_completed_summary(self):
        result = build_pipeline_summary(
            instance_id="inst-1",
            blob_name="test.kml",
            blob_url="https://storage/kml-input/test.kml",
            ingestion={
                "feature_count": 2,
                "aoi_count": 2,
                "metadata_count": 2,
                "metadata_results": [],
            },
            acquisition={"ready_count": 2, "failed_count": 0, "imagery_outcomes": []},
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [],
                "pp_completed": 2,
                "pp_clipped": 2,
                "pp_reprojected": 1,
                "pp_failed": 0,
                "post_process_results": [],
            },
        )
        assert result["status"] == "completed"
        assert result["feature_count"] == 2
        assert result["imagery_ready"] == 2

    def test_partial_summary(self):
        result = build_pipeline_summary(
            instance_id="inst-2",
            blob_name="test.kml",
            blob_url="",
            ingestion={
                "feature_count": 3,
                "aoi_count": 3,
                "metadata_count": 3,
                "metadata_results": [],
            },
            acquisition={"ready_count": 2, "failed_count": 1, "imagery_outcomes": []},
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [],
                "pp_completed": 2,
                "pp_clipped": 1,
                "pp_reprojected": 0,
                "pp_failed": 0,
                "post_process_results": [],
            },
        )
        assert result["status"] == "partial_imagery"


class TestParseHistoryLimit:
    def test_valid_limit(self):
        assert _parse_history_limit("5") == 5

    def test_empty_returns_default(self):
        assert _parse_history_limit("") == 8

    def test_clamps_to_max(self):
        assert _parse_history_limit("100") == 20

    def test_clamps_to_min(self):
        assert _parse_history_limit("0") == 1

    def test_non_numeric(self):
        assert _parse_history_limit("abc") == 8


class TestParseHistoryOffset:
    def test_valid_offset(self):
        assert _parse_history_offset("10") == 10

    def test_empty_returns_zero(self):
        assert _parse_history_offset("") == 0

    def test_negative_clamps_to_zero(self):
        assert _parse_history_offset("-5") == 0

    def test_clamps_to_max(self):
        assert _parse_history_offset("9999") == 200

    def test_non_numeric(self):
        assert _parse_history_offset("abc") == 0


# ---------------------------------------------------------------------------
# §3.1 — Claim Check Pattern
# ---------------------------------------------------------------------------


class TestPayloadOffloaderClaimCheck:
    """Tests for individual claim check operations on PayloadOffloader."""

    def _make_offloader(self):
        storage = MagicMock()
        return PayloadOffloader(storage), storage

    def test_store_claim_uploads_json(self):
        offloader, storage = self._make_offloader()
        data = {"feature_name": "farm_1", "bbox": [1.0, 2.0, 3.0, 4.0]}
        ref = offloader.store_claim("inst-1", "aoi_0", data)
        assert ref == "claims/inst-1/aoi_0.json"
        storage.upload_bytes.assert_called_once()
        call_args = storage.upload_bytes.call_args
        assert call_args[0][0] == "pipeline-payloads"
        assert call_args[0][1] == "claims/inst-1/aoi_0.json"
        payload = json.loads(call_args[0][2])
        assert payload["feature_name"] == "farm_1"

    def test_load_claim_returns_dict(self):
        offloader, storage = self._make_offloader()
        expected = {"feature_name": "farm_1", "bbox": [1.0, 2.0, 3.0, 4.0]}
        storage.download_bytes.return_value = json.dumps(expected).encode()
        result = offloader.load_claim("claims/inst-1/aoi_0.json")
        assert result == expected

    def test_store_claims_batch_returns_refs(self):
        offloader, storage = self._make_offloader()
        items = [
            {"feature_name": "aoi_a", "area_ha": 10.0},
            {"feature_name": "aoi_b", "area_ha": 20.0},
        ]
        refs = offloader.store_claims_batch("inst-2", items)
        assert len(refs) == 2
        assert refs[0]["key"] == "aoi_a"
        assert refs[1]["key"] == "aoi_b"
        assert "ref" in refs[0]
        assert "ref" in refs[1]
        assert storage.upload_bytes.call_count == 2

    def test_store_claims_batch_uses_key_field(self):
        offloader, _storage = self._make_offloader()
        items = [{"id": "x", "val": 1}]
        refs = offloader.store_claims_batch("inst-3", items, key_field="id")
        assert refs[0]["key"] == "x"
        assert "id_0_" in refs[0]["claim_id"]


class TestClaimCheckBulkRoundtrip:
    """Integration-style test verifying bulk claim store → load cycle."""

    def test_roundtrip(self):
        storage = MagicMock()
        _stored: dict[str, bytes] = {}

        def _upload(container, path, data, **kw):
            _stored[path] = data

        def _download(container, path):
            return _stored[path]

        storage.upload_bytes.side_effect = _upload
        storage.download_bytes.side_effect = _download

        offloader = PayloadOffloader(storage)
        aoi = {"feature_name": "orchard", "bbox": [10.0, 20.0, 10.1, 20.1], "area_ha": 5.0}
        ref = offloader.store_claim("inst-rt", "orchard_0", aoi)
        loaded = offloader.load_claim(ref)
        assert loaded == aoi


# ---------------------------------------------------------------------------
# §3.2 — Orchestrator Payload Builders
# ---------------------------------------------------------------------------


class TestAcqPayload:
    def test_composite_includes_temporal_count(self):
        ref = {"ref": "claims/inst/aoi_0.json", "key": "aoi_a"}
        inp = {"provider_name": "pc", "temporal_count": 4}
        p = _acq_payload(ref, inp, composite=True)
        assert p["aoi_ref"] == "claims/inst/aoi_0.json"
        assert p["temporal_count"] == 4

    def test_non_composite_omits_temporal_count(self):
        ref = {"ref": "claims/inst/aoi_0.json", "key": "aoi_a"}
        inp = {}
        p = _acq_payload(ref, inp, composite=False)
        assert "temporal_count" not in p
        assert p["provider_name"] == "planetary_computer"


class TestPollPayload:
    def test_builds_from_order(self):
        order = {"order_id": "o1", "scene_id": "s1", "aoi_feature_name": "farm"}
        inp = {"provider_name": "pc"}
        p = _poll_payload(order, inp)
        assert p["order_id"] == "o1"
        assert p["aoi_feature_name"] == "farm"
        assert p["overrides"] == inp


class TestDownloadPayload:
    def test_includes_aoi_ref(self):
        outcome = {"order_id": "o1", "aoi_feature_name": "farm"}
        inp = {}
        ctx = {"project_name": "proj", "timestamp": "20260402T000000Z"}
        asset_urls = {"o1": "https://example.com/img.tif"}
        order_meta = {"o1": {"role": "visual", "collection": "naip"}}
        aoi_ref_lookup = {"farm": "claims/inst/farm.json"}
        p = _download_payload(outcome, inp, ctx, asset_urls, order_meta, aoi_ref_lookup, "output")
        assert p["aoi_ref"] == "claims/inst/farm.json"
        assert p["asset_url"] == "https://example.com/img.tif"
        assert p["role"] == "visual"


class TestPostProcessPayload:
    def test_includes_aoi_ref_and_defaults(self):
        dl = {"aoi_feature_name": "farm"}
        inp = {}
        ctx = {"project_name": "proj", "timestamp": "20260402T000000Z"}
        aoi_ref_lookup = {"farm": "claims/inst/farm.json"}
        p = _post_process_payload(dl, inp, ctx, aoi_ref_lookup, "output")
        assert p["aoi_ref"] == "claims/inst/farm.json"
        assert p["enable_clipping"] is True
        assert p["square_frame"] is True


# ---------------------------------------------------------------------------
# §3.3 — Activity AOI Loading
# ---------------------------------------------------------------------------


class TestLoadAoi:
    def test_loads_from_claim_ref(self):
        from blueprints.pipeline.activities import _load_aoi

        aoi_data = {
            "feature_name": "farm",
            "exterior_coords": [[1.0, 2.0], [3.0, 4.0]],
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "buffered_bbox": [0.9, 1.9, 3.1, 4.1],
        }
        mock_storage = MagicMock()
        mock_storage.download_bytes.return_value = json.dumps(aoi_data).encode()

        result = _load_aoi({"aoi_ref": "claims/inst/farm.json"}, mock_storage)
        assert result.feature_name == "farm"
        assert result.bbox == [1.0, 2.0, 3.0, 4.0]

    def test_loads_from_inline_aoi(self):
        from blueprints.pipeline.activities import _load_aoi

        result = _load_aoi({"aoi": {"feature_name": "inline"}})
        assert result.feature_name == "inline"


# ---------------------------------------------------------------------------
# §3.4 — Constants
# ---------------------------------------------------------------------------


class TestAcquisitionBatchConstant:
    def test_default_acquisition_batch_size(self):
        from treesight.constants import DEFAULT_ACQUISITION_BATCH_SIZE

        assert DEFAULT_ACQUISITION_BATCH_SIZE == 25


# ---------------------------------------------------------------------------
# §11 — Bulk AOI (#311)
# ---------------------------------------------------------------------------


class TestMaxFeaturesConstant:
    def test_max_features_exists(self):
        from treesight.constants import MAX_FEATURES_PER_KML

        assert MAX_FEATURES_PER_KML == 500


class TestGroupPerAoi:
    def test_groups_by_feature_name(self):
        from treesight.pipeline.orchestrator import _group_per_aoi

        acquisition = {
            "imagery_outcomes": [
                {"aoi_feature_name": "farm_a", "state": "ready"},
                {"aoi_feature_name": "farm_a", "state": "ready"},
                {"aoi_feature_name": "farm_b", "state": "failed"},
            ]
        }
        fulfilment = {
            "download_results": [
                {"aoi_feature_name": "farm_a", "state": "completed"},
                {"aoi_feature_name": "farm_b", "state": "failed"},
            ],
            "post_process_results": [
                {"aoi_feature_name": "farm_a", "clipped_blob_path": "x.tif"},
            ],
        }

        result = _group_per_aoi(acquisition, fulfilment)
        assert len(result) == 2
        a = next(r for r in result if r["feature_name"] == "farm_a")
        b = next(r for r in result if r["feature_name"] == "farm_b")
        assert a["imagery_ready"] == 2
        assert a["downloads_succeeded"] == 1
        assert a["post_process_completed"] == 1
        assert b["imagery_failed"] == 1
        assert b["downloads_failed"] == 1

    def test_empty_inputs(self):
        from treesight.pipeline.orchestrator import _group_per_aoi

        result = _group_per_aoi({}, {})
        assert result == []


class TestAoiSummaryModel:
    def test_defaults(self):
        from treesight.models.outcomes import AoiSummary

        s = AoiSummary(feature_name="test")
        assert s.feature_name == "test"
        assert s.imagery_ready == 0

    def test_roundtrip(self):
        from treesight.models.outcomes import AoiSummary

        s = AoiSummary(feature_name="field", imagery_ready=3, downloads_succeeded=2)
        d = s.model_dump()
        assert d["feature_name"] == "field"
        assert d["imagery_ready"] == 3


class TestPipelineSummaryPerAoi:
    def test_includes_per_aoi(self):
        from treesight.pipeline.orchestrator import build_pipeline_summary

        result = build_pipeline_summary(
            instance_id="inst-1",
            blob_name="test.kml",
            blob_url="https://example.com/test.kml",
            ingestion={"feature_count": 2, "aoi_count": 2},
            acquisition={
                "ready_count": 2,
                "failed_count": 0,
                "imagery_outcomes": [
                    {"aoi_feature_name": "a", "state": "ready"},
                    {"aoi_feature_name": "b", "state": "ready"},
                ],
            },
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [
                    {"aoi_feature_name": "a", "state": "completed"},
                    {"aoi_feature_name": "b", "state": "completed"},
                ],
                "pp_completed": 2,
                "pp_clipped": 2,
                "pp_reprojected": 2,
                "pp_failed": 0,
                "post_process_results": [
                    {"aoi_feature_name": "a", "clipped_blob_path": "x.tif"},
                    {"aoi_feature_name": "b", "clipped_blob_path": "y.tif"},
                ],
            },
        )

        assert "per_aoi_summaries" in result
        assert len(result["per_aoi_summaries"]) == 2
        names = {s["feature_name"] for s in result["per_aoi_summaries"]}
        assert names == {"a", "b"}


# ---------------------------------------------------------------------------
# Orchestrator phase decomposition (§Q.1 — #452)
# ---------------------------------------------------------------------------


class TestOrchestratorPhaseFunctions:
    """Verify the orchestrator is decomposed into phase generator functions."""

    def test_phase_ingestion_exists(self):
        from blueprints.pipeline.orchestrator import _phase_ingestion

        assert callable(_phase_ingestion)

    def test_phase_acquisition_exists(self):
        from blueprints.pipeline.orchestrator import _phase_acquisition

        assert callable(_phase_acquisition)

    def test_phase_fulfilment_exists(self):
        from blueprints.pipeline.orchestrator import _phase_fulfilment

        assert callable(_phase_fulfilment)

    def test_phase_enrichment_exists(self):
        from blueprints.pipeline.orchestrator import _phase_enrichment

        assert callable(_phase_enrichment)

    def test_phase_ingestion_is_generator(self):
        import inspect

        from blueprints.pipeline.orchestrator import _phase_ingestion

        assert inspect.isgeneratorfunction(_phase_ingestion)

    def test_phase_acquisition_is_generator(self):
        import inspect

        from blueprints.pipeline.orchestrator import _phase_acquisition

        assert inspect.isgeneratorfunction(_phase_acquisition)

    def test_phase_fulfilment_is_generator(self):
        import inspect

        from blueprints.pipeline.orchestrator import _phase_fulfilment

        assert inspect.isgeneratorfunction(_phase_fulfilment)

    def test_phase_enrichment_is_generator(self):
        import inspect

        from blueprints.pipeline.orchestrator import _phase_enrichment

        assert inspect.isgeneratorfunction(_phase_enrichment)


class TestPhaseIngestionAoiLimitGate:
    """Verify _phase_ingestion enforces aoi_limit before fan-out."""

    def test_over_limit_raises_before_prepare_aoi(self):
        """Over-limit input fails before scheduling prepare_aoi tasks."""
        from unittest.mock import MagicMock

        import pytest

        from blueprints.pipeline.orchestrator import _phase_ingestion

        ctx = MagicMock()
        # parse_kml returns a list of features (inline, not offloaded)
        six_features = [{"geometry": {"type": "Point", "coordinates": [0, 0]}}] * 6
        ctx.call_activity.return_value = "parse_kml_sentinel"

        inp = {"blob_name": "test.kml", "tier": "free"}  # free allows 5
        gen = _phase_ingestion(ctx, inp, "inst-1", {"tid": "t1"})

        # First yield: call_activity("parse_kml", ...)
        gen.send(None)
        # Send back 6 features (exceeds free tier limit of 5)
        with pytest.raises(ValueError, match=r"6 AOIs.*Free.*allows 5"):
            gen.send(six_features)

    def test_within_limit_proceeds_to_fan_out(self):
        """Within-limit input reaches the prepare_aoi fan-out step."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_ingestion

        ctx = MagicMock()
        three_features = [{"geometry": {"type": "Point", "coordinates": [0, 0]}}] * 3
        ctx.call_activity.return_value = "activity_sentinel"
        ctx.task_all.return_value = "task_all_sentinel"

        inp = {"blob_name": "test.kml", "tier": "free"}  # free allows 5
        gen = _phase_ingestion(ctx, inp, "inst-1", {"tid": "t1"})

        # First yield: parse_kml
        gen.send(None)
        # Send back 3 features (within limit) — should proceed, not raise
        gen.send(three_features)
        # If we got here, enforce_aoi_limit passed and the generator continued
        # to the prepare_aoi fan-out step (task_all yield)
        ctx.set_custom_status.assert_any_call(
            {"phase": "ingestion", "step": "preparing_aois", "features": 3}
        )


class TestAcquisitionActivityRetry:
    """Verify _phase_acquisition uses call_activity_with_retry for search activities."""

    def test_acquisition_uses_call_activity_with_retry(self):
        """Acquisition search activities must use DF retry options."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_acquisition
        from treesight.constants import (
            ACTIVITY_RETRY_FIRST_INTERVAL_MS,
            ACTIVITY_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "acq_sentinel"
        ctx.task_all.return_value = [[]]  # single batch, composite returns list of lists

        inp = {"composite_search": True}
        aoi_refs = [{"ref": "blob://aoi/1", "key": "aoi-1"}]
        aoi_area_by_name = {"aoi-1": 10.0}

        gen = _phase_acquisition(ctx, inp, aoi_refs, aoi_area_by_name)
        # First yield: task_all for acquisition batch
        gen.send(None)

        # Verify call_activity_with_retry was used (not call_activity)
        ctx.call_activity_with_retry.assert_called()
        ctx.call_activity.assert_not_called()

        # Verify retry options were passed
        call_args = ctx.call_activity_with_retry.call_args
        retry_opts = call_args[0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == ACTIVITY_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == ACTIVITY_RETRY_MAX_ATTEMPTS

    def test_acquisition_retry_applies_to_non_composite(self):
        """Non-composite (single acquire_imagery) also uses retry."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_acquisition

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "acq_sentinel"
        ctx.task_all.return_value = [{"order_id": "o1"}]

        inp = {"composite_search": False}
        aoi_refs = [{"ref": "blob://aoi/1", "key": "aoi-1"}]
        aoi_area_by_name = {"aoi-1": 10.0}

        gen = _phase_acquisition(ctx, inp, aoi_refs, aoi_area_by_name)
        gen.send(None)

        activity_name = ctx.call_activity_with_retry.call_args[0][0]
        assert activity_name == "acquire_imagery"

    def test_poll_order_uses_retry(self):
        """poll_order should use transient retry (talks to external APIs)."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_acquisition
        from treesight.constants import (
            ACTIVITY_RETRY_FIRST_INTERVAL_MS,
            ACTIVITY_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "acq_sentinel"
        # First yield: acquisition batch. Second yield: poll batch.
        ctx.task_all.side_effect = [
            [{"order_id": "o1"}],  # acquisition
            [{"state": "ready", "order_id": "o1"}],  # polling
        ]

        inp = {"composite_search": False}
        aoi_refs = [{"ref": "blob://aoi/1", "key": "aoi-1"}]
        aoi_area_by_name = {"aoi-1": 10.0}

        gen = _phase_acquisition(ctx, inp, aoi_refs, aoi_area_by_name)
        gen.send(None)  # acquisition yield
        with contextlib.suppress(StopIteration):
            gen.send([{"order_id": "o1"}])  # poll yield

        # poll_order should be called with retry
        poll_calls = [
            c for c in ctx.call_activity_with_retry.call_args_list if c[0][0] == "poll_order"
        ]
        assert len(poll_calls) >= 1
        retry_opts = poll_calls[0][0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == ACTIVITY_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == ACTIVITY_RETRY_MAX_ATTEMPTS


class TestFulfilmentRetry:
    """Verify fulfilment activities use call_activity_with_retry."""

    def test_download_imagery_uses_transient_retry(self):
        """download_imagery should use transient retry options."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _fulfil_download
        from treesight.constants import (
            ACTIVITY_RETRY_FIRST_INTERVAL_MS,
            ACTIVITY_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "dl_sentinel"
        ctx.task_all.return_value = [{"state": "ok", "blob_path": "path"}]

        gen = _fulfil_download(
            ctx,
            serverless_ready=[{"order_id": "o1", "aoi_key": "aoi-1"}],
            inp={},
            ctx={"project_name": "p", "timestamp": "t"},
            asset_urls={"o1": "http://example.com"},
            order_meta={"o1": {"provider": "test"}},
            aoi_ref_lookup={"aoi-1": "blob://aoi/1"},
            output_container="out",
        )
        gen.send(None)

        ctx.call_activity_with_retry.assert_called()
        call_args = ctx.call_activity_with_retry.call_args
        assert call_args[0][0] == "download_imagery"
        retry_opts = call_args[0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == ACTIVITY_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == ACTIVITY_RETRY_MAX_ATTEMPTS

    def test_post_process_uses_long_retry(self):
        """post_process_imagery should use long-running retry options."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _fulfil_post_process
        from treesight.constants import (
            LONG_RETRY_FIRST_INTERVAL_MS,
            LONG_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "pp_sentinel"
        ctx.task_all.return_value = [{"state": "ok"}]

        gen = _fulfil_post_process(
            ctx,
            successful_downloads=[{"blob_path": "path", "aoi_key": "aoi-1"}],
            inp={},
            ctx={"project_name": "p", "timestamp": "t"},
            aoi_ref_lookup={"aoi-1": "blob://aoi/1"},
            output_container="out",
        )
        gen.send(None)

        ctx.call_activity_with_retry.assert_called()
        call_args = ctx.call_activity_with_retry.call_args
        assert call_args[0][0] == "post_process_imagery"
        retry_opts = call_args[0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == LONG_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == LONG_RETRY_MAX_ATTEMPTS

    def test_submit_batch_fulfilment_uses_long_retry(self):
        """submit_batch_fulfilment should use long-running retry options."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _fulfil_batch
        from treesight.constants import (
            LONG_RETRY_FIRST_INTERVAL_MS,
            LONG_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "submit_sentinel"
        ctx.task_all.return_value = [{"state": "completed", "job_id": "j1", "task_id": "t1"}]

        gen = _fulfil_batch(
            ctx,
            batch_ready=[{"order_id": "o1"}],
            asset_urls={"o1": "http://example.com"},
            output_container="out",
            ctx={"project_name": "p", "timestamp": "t"},
        )
        gen.send(None)

        submit_calls = [
            c
            for c in ctx.call_activity_with_retry.call_args_list
            if c[0][0] == "submit_batch_fulfilment"
        ]
        assert len(submit_calls) == 1
        retry_opts = submit_calls[0][0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == LONG_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == LONG_RETRY_MAX_ATTEMPTS


class TestEnrichmentParallelFanOut:
    """Verify enrichment phase uses parallel fan-out via task_all (#574)."""

    def test_data_sources_and_imagery_fan_out_in_parallel(self):
        """enrich_data_sources and enrich_imagery should execute via task_all."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_enrichment
        from treesight.constants import (
            LONG_RETRY_FIRST_INTERVAL_MS,
            LONG_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        task_all_sentinel = MagicMock()
        ctx.task_all.return_value = task_all_sentinel

        gen = _phase_enrichment(
            ctx,
            inp={"eudr_mode": False},
            ctx={"project_name": "p", "timestamp": "t"},
            all_coords=[[10.0, 20.0]],
            per_aoi_coords=[],
            output_container="out",
        )
        # First yield: task_all for data_sources + imagery
        yielded = gen.send(None)
        assert yielded is task_all_sentinel

        # Verify task_all was called with two activities
        ctx.task_all.assert_called_once()
        task_all_args = ctx.task_all.call_args[0][0]
        assert len(task_all_args) == 2

        # Verify both activities use long retry
        calls = ctx.call_activity_with_retry.call_args_list
        activity_names = [c[0][0] for c in calls]
        assert "enrich_data_sources" in activity_names
        assert "enrich_imagery" in activity_names
        for c in calls:
            retry_opts = c[0][1]
            assert retry_opts.first_retry_interval_in_milliseconds == LONG_RETRY_FIRST_INTERVAL_MS
            assert retry_opts.max_number_of_attempts == LONG_RETRY_MAX_ATTEMPTS

    def test_per_aoi_fan_out(self):
        """Per-AOI enrichment should fan-out one activity per AOI via task_all."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_enrichment

        ctx = MagicMock()
        # First task_all: data_sources + imagery
        parallel_sentinel = MagicMock()
        # Second task_all: per-AOI
        per_aoi_sentinel = MagicMock()
        # Third yield: enrich_finalize
        finalize_sentinel = MagicMock()

        ctx.task_all.side_effect = [parallel_sentinel, per_aoi_sentinel]
        ctx.call_activity_with_retry.return_value = finalize_sentinel

        aois = [
            {"name": "a", "coords": [[1, 2]]},
            {"name": "b", "coords": [[3, 4]]},
            {"name": "c", "coords": [[5, 6]]},
        ]

        gen = _phase_enrichment(
            ctx,
            inp={"eudr_mode": False},
            ctx={"project_name": "p", "timestamp": "t"},
            all_coords=[[10.0, 20.0]],
            per_aoi_coords=aois,
            output_container="out",
        )

        # Yield 1: parallel task_all (data_sources + imagery)
        gen.send(None)
        # Send back results for data_sources + imagery
        gen.send([{"frame_plan": []}, {"ndvi": {}}])
        # Yield 2: per-AOI task_all — verify 3 AOI activities
        assert ctx.task_all.call_count == 2
        aoi_tasks = ctx.task_all.call_args_list[1][0][0]
        assert len(aoi_tasks) == 3

    def test_enrichment_reports_substep_status(self):
        """Orchestrator should set customStatus with enrichment sub-steps."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_enrichment

        ctx = MagicMock()
        ctx.task_all.return_value = MagicMock()

        gen = _phase_enrichment(
            ctx,
            inp={},
            ctx={"project_name": "p", "timestamp": "t"},
            all_coords=[[10.0, 20.0]],
            per_aoi_coords=[],
            output_container="out",
        )
        gen.send(None)

        # Should have set customStatus with phase + step
        ctx.set_custom_status.assert_called()
        first_status = ctx.set_custom_status.call_args_list[0][0][0]
        assert first_status["phase"] == "enrichment"
        assert first_status["step"] == "data_sources_and_imagery"

    def test_enrichment_skipped_when_no_coords(self):
        """Enrichment should return empty dict when all_coords is empty."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _phase_enrichment

        ctx = MagicMock()

        gen = _phase_enrichment(
            ctx,
            inp={},
            ctx={"project_name": "p", "timestamp": "t"},
            all_coords=[],
            per_aoi_coords=[],
            output_container="out",
        )
        try:
            gen.send(None)
        except StopIteration as e:
            result = e.value
        else:
            result = None

        assert result == {}
        ctx.call_activity_with_retry.assert_not_called()


class TestSafeReleaseQuotaRetry:
    """Verify _safe_release_quota uses retry."""

    def test_release_quota_uses_transient_retry(self):
        """release_quota should use transient retry — it refunds credits."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _safe_release_quota
        from treesight.constants import (
            ACTIVITY_RETRY_FIRST_INTERVAL_MS,
            ACTIVITY_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = None

        gen = _safe_release_quota(ctx, user_id="u1", instance_id="i1")
        with contextlib.suppress(StopIteration):
            gen.send(None)

        ctx.call_activity_with_retry.assert_called_once()
        call_args = ctx.call_activity_with_retry.call_args
        assert call_args[0][0] == "release_quota"
        retry_opts = call_args[0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == ACTIVITY_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == ACTIVITY_RETRY_MAX_ATTEMPTS

    def test_release_quota_swallows_errors(self):
        """release_quota failure must not propagate (preserves original exception)."""
        from unittest.mock import MagicMock

        from blueprints.pipeline.orchestrator import _safe_release_quota

        ctx = MagicMock()
        ctx.call_activity_with_retry.side_effect = RuntimeError("quota service down")

        gen = _safe_release_quota(ctx, user_id="u1", instance_id="i1")
        with contextlib.suppress(StopIteration):
            gen.send(None)
        # If RuntimeError propagated, the above would raise instead of being suppressed.


class TestOrchestratorCoordinatorSize:
    """The main orchestrator should be a thin coordinator ≤40 lines."""

    def test_orchestrator_body_within_limit(self):
        import ast
        from pathlib import Path

        from blueprints.pipeline import orchestrator as orch_mod

        src_path = Path(orch_mod.__file__)
        src = src_path.read_text()
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "treesight_orchestrator":
                body_lines = node.end_lineno - node.lineno + 1  # type: ignore[operator]
                assert body_lines <= 40, f"Orchestrator has {body_lines} lines (max 40)"
                return

        raise AssertionError("treesight_orchestrator not found in source")


# ---------------------------------------------------------------------------
# Progressive delivery — sub-orchestrator per AOI (#585)
# ---------------------------------------------------------------------------


def _make_aoi_result(
    name: str,
    ready: int = 1,
    failed: int = 0,
    dl_succeeded: int = 1,
    dl_failed: int = 0,
    pp_completed: int = 1,
    pp_clipped: int = 0,
    pp_reprojected: int = 0,
    pp_failed: int = 0,
) -> dict:
    """Build a minimal per-AOI sub-orchestrator result for test helpers."""
    return {
        "aoi_name": name,
        "acquisition": {
            "imagery_outcomes": [{"aoi": name}] * (ready + failed),
            "ready_count": ready,
            "failed_count": failed,
        },
        "fulfilment": {
            "download_results": [{"aoi": name}] * (dl_succeeded + dl_failed),
            "downloads_completed": dl_succeeded + dl_failed,
            "downloads_succeeded": dl_succeeded,
            "downloads_failed": dl_failed,
            "batch_submitted": 0,
            "batch_succeeded": 0,
            "batch_failed": 0,
            "post_process_results": [{"aoi": name}] * pp_completed,
            "pp_completed": pp_completed,
            "pp_clipped": pp_clipped,
            "pp_reprojected": pp_reprojected,
            "pp_failed": pp_failed,
        },
    }


class TestAggregateAoiResults:
    """Verify _aggregate_aoi_results merges per-AOI sub-orchestrator results."""

    def test_sums_acquisition_ready_counts(self):
        results = [
            _make_aoi_result("A", ready=3, failed=1),
            _make_aoi_result("B", ready=2, failed=0),
        ]
        acq, _ful = _aggregate_aoi_results(results)
        assert acq["ready_count"] == 5
        assert acq["failed_count"] == 1
        assert len(acq["imagery_outcomes"]) == 6

    def test_sums_fulfilment_counts(self):
        results = [
            _make_aoi_result("A", dl_succeeded=3, dl_failed=1, pp_completed=3, pp_clipped=2),
            _make_aoi_result(
                "B",
                dl_succeeded=2,
                dl_failed=0,
                pp_completed=2,
                pp_clipped=1,
                pp_failed=1,
            ),
        ]
        _acq, ful = _aggregate_aoi_results(results)
        assert ful["downloads_succeeded"] == 5
        assert ful["downloads_failed"] == 1
        assert ful["downloads_completed"] == 6
        assert ful["pp_completed"] == 5
        assert ful["pp_clipped"] == 3
        assert ful["pp_failed"] == 1

    def test_handles_empty_results(self):
        acq, ful = _aggregate_aoi_results([])
        assert acq["ready_count"] == 0
        assert ful["downloads_completed"] == 0
        assert ful["pp_completed"] == 0

    def test_handles_missing_keys(self):
        acq, ful = _aggregate_aoi_results([{"aoi_name": "A"}])
        assert acq["ready_count"] == 0
        assert ful["downloads_completed"] == 0


class TestAoiPipelineSubOrchestrator:
    """Verify per-AOI sub-orchestrator exists and has correct structure."""

    def test_aoi_pipeline_module_imports(self):
        from blueprints.pipeline import aoi_orchestrator

        assert hasattr(aoi_orchestrator, "aoi_pipeline")

    def test_aoi_acquire_is_generator(self):
        import inspect

        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        assert inspect.isgeneratorfunction(_aoi_acquire)

    def test_aoi_fulfil_is_generator(self):
        import inspect

        from blueprints.pipeline.aoi_orchestrator import _aoi_fulfil

        assert inspect.isgeneratorfunction(_aoi_fulfil)

    def test_aoi_acquire_calls_composite_search(self):
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "acq_sentinel"
        ctx.task_all.return_value = [{"order_id": "o1", "state": "ready"}]

        pipeline_inp = {"composite_search": True}
        aoi_ref = {"ref": "blob://aoi/1", "key": "Farm A"}

        gen = _aoi_acquire(ctx, pipeline_inp, aoi_ref)
        gen.send(None)  # First yield: acquire activity

        ctx.call_activity_with_retry.assert_called()
        activity_name = ctx.call_activity_with_retry.call_args[0][0]
        assert activity_name == "acquire_composite"

    def test_aoi_acquire_uses_retry(self):
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire
        from treesight.constants import (
            ACTIVITY_RETRY_FIRST_INTERVAL_MS,
            ACTIVITY_RETRY_MAX_ATTEMPTS,
        )

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "acq_sentinel"
        ctx.task_all.return_value = []

        gen = _aoi_acquire(ctx, {"composite_search": True}, {"ref": "r", "key": "k"})
        gen.send(None)

        retry_opts = ctx.call_activity_with_retry.call_args[0][1]
        assert retry_opts.first_retry_interval_in_milliseconds == ACTIVITY_RETRY_FIRST_INTERVAL_MS
        assert retry_opts.max_number_of_attempts == ACTIVITY_RETRY_MAX_ATTEMPTS

    def test_aoi_acquire_non_composite(self):
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = "acq_sentinel"
        ctx.task_all.return_value = [{"order_id": "o1", "state": "ready"}]

        gen = _aoi_acquire(ctx, {"composite_search": False}, {"ref": "r", "key": "k"})
        gen.send(None)

        activity_name = ctx.call_activity_with_retry.call_args[0][0]
        assert activity_name == "acquire_imagery"


class TestProgressivePipeline:
    """Verify progressive pipeline fans out sub-orchestrators."""

    def test_progressive_pipeline_is_generator(self):
        import inspect

        from blueprints.pipeline.orchestrator import _progressive_pipeline

        assert inspect.isgeneratorfunction(_progressive_pipeline)

    def test_progressive_pipeline_calls_sub_orchestrator(self):
        from blueprints.pipeline.orchestrator import _progressive_pipeline

        ctx = MagicMock()
        task_a = MagicMock()
        task_a.result = _make_aoi_result("A")
        task_b = MagicMock()
        task_b.result = _make_aoi_result("B")
        ctx.call_sub_orchestrator.side_effect = [task_a, task_b]
        ctx.task_any.return_value = "any_sentinel"

        inp = {"composite_search": True}
        project_ctx = {"project_name": "test", "timestamp": "20260416T000000Z"}
        ing = {
            "aoi_refs": [{"ref": "blob://1", "key": "A"}, {"ref": "blob://2", "key": "B"}],
            "per_aoi_coords": [
                {"name": "A", "coords": [[0, 0]], "area_ha": 10, "cluster": 0},
                {"name": "B", "coords": [[1, 1]], "area_ha": 20, "cluster": 0},
            ],
            "aoi_area_by_name": {"A": 10.0, "B": 20.0},
        }

        gen = _progressive_pipeline(ctx, inp, project_ctx, ing, "test-inst")
        gen.send(None)  # First yield: task_any

        assert ctx.call_sub_orchestrator.call_count == 2

    def test_progressive_pipeline_passes_deterministic_instance_ids(self):
        from blueprints.pipeline.orchestrator import _progressive_pipeline

        ctx = MagicMock()
        task_a = MagicMock()
        task_a.result = _make_aoi_result("A")
        task_b = MagicMock()
        task_b.result = _make_aoi_result("B")
        ctx.call_sub_orchestrator.side_effect = [task_a, task_b]
        ctx.task_any.return_value = "any_sentinel"

        ing = {
            "aoi_refs": [{"ref": "blob://1", "key": "A"}, {"ref": "blob://2", "key": "B"}],
            "per_aoi_coords": [{"name": "A", "coords": [[0, 0]], "cluster": 0}],
            "aoi_area_by_name": {"A": 10.0, "B": 20.0},
        }

        gen = _progressive_pipeline(
            ctx,
            {},
            {"project_name": "t", "timestamp": "ts"},
            ing,
            "parent-id",
        )
        gen.send(None)

        calls = ctx.call_sub_orchestrator.call_args_list
        ids = [c[1]["instance_id"] for c in calls]
        assert ids == ["parent-id:aoi-0", "parent-id:aoi-1"]

    def test_progressive_pipeline_sets_custom_status(self):
        from blueprints.pipeline.orchestrator import _progressive_pipeline

        ctx = MagicMock()
        task_a = MagicMock()
        task_a.result = _make_aoi_result("A")
        ctx.call_sub_orchestrator.return_value = task_a
        ctx.task_any.return_value = "any_sentinel"

        ing = {
            "aoi_refs": [{"ref": "blob://1", "key": "A"}],
            "per_aoi_coords": [{"name": "A", "coords": [[0, 0]], "cluster": 0}],
            "aoi_area_by_name": {"A": 10.0},
        }

        gen = _progressive_pipeline(
            ctx,
            {},
            {"project_name": "t", "timestamp": "ts"},
            ing,
            "parent-id",
        )
        with contextlib.suppress(StopIteration):
            gen.send(None)  # first yield: task_any
            gen.send(task_a)  # winner is task_a, loop ends

        status_calls = ctx.set_custom_status.call_args_list
        assert any(c[0][0].get("phase") == "per_aoi_pipeline" for c in status_calls)
        # Should have status after completion
        assert any(c[0][0].get("completed_aois") == 1 for c in status_calls)

    def test_progressive_pipeline_omits_aoi_entry(self):
        """Sub-orchestrator payload must NOT include aoi_entry (claim-check, 48 KiB limit)."""
        from blueprints.pipeline.orchestrator import _progressive_pipeline

        ctx = MagicMock()
        task_a = MagicMock()
        task_a.result = _make_aoi_result("A")
        ctx.call_sub_orchestrator.return_value = task_a
        ctx.task_any.return_value = "any_sentinel"

        ing = {
            "aoi_refs": [{"ref": "blob://1", "key": "A"}],
            "per_aoi_coords": [{"name": "A", "coords": [[0, 0]], "cluster": 0}],
            "aoi_area_by_name": {"A": 10.0},
        }

        gen = _progressive_pipeline(ctx, {}, {"project_name": "t", "timestamp": "ts"}, ing, "p")
        gen.send(None)

        payload = ctx.call_sub_orchestrator.call_args[1]["input_"]
        assert "aoi_entry" not in payload


class TestAoiPollOrderRetry:
    """Verify poll_order uses call_activity_with_retry (DF-level retry)."""

    def test_poll_order_uses_call_activity_with_retry(self):
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = [{"order_id": "o1"}]
        ctx.task_all.return_value = [{"order_id": "o1", "state": "ready"}]

        gen = _aoi_acquire(ctx, {"composite_search": True}, {"ref": "r", "key": "k"})
        gen.send(None)  # first yield: acquire (with retry)

        with contextlib.suppress(StopIteration):
            gen.send([{"order_id": "o1"}])  # resume with acquire result

        # poll_order should use call_activity_with_retry
        retry_calls = [
            c for c in ctx.call_activity_with_retry.call_args_list if c[0][0] == "poll_order"
        ]
        assert len(retry_calls) >= 1
