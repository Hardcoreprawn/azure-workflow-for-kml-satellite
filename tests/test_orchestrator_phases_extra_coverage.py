"""Direct unit coverage for orchestrator phase generator functions.

_phase_ingestion / _phase_acquisition / _fulfil_batch / _fulfil_download /
_fulfil_post_process / _phase_fulfilment / _phase_enrichment /
_safe_finalize_run / _safe_write_pipeline_stats are pure Durable Functions
generators extracted from orchestrator.py (#1292). Existing orchestration
tests (tests/test_aoi_orchestrator_coverage.py) mock these functions
wholesale to test aoi_orchestrator.py's own glue logic, so their real
bodies were never directly exercised. Closes the gap exposed by the #1292
extraction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from blueprints.pipeline._phase_acquisition import _phase_acquisition
from blueprints.pipeline._phase_enrichment import (
    _phase_enrichment,
    _safe_finalize_run,
    _safe_write_pipeline_stats,
)
from blueprints.pipeline._phase_fulfilment import (
    _fulfil_batch,
    _fulfil_download,
    _fulfil_post_process,
    _phase_fulfilment,
)
from blueprints.pipeline._phase_ingestion import _phase_ingestion


def _drain(gen, responses):
    """Drive a Durable Functions generator to completion.

    ``responses`` supplies the value each pending ``yield`` resolves to, in
    order. The first ``.send(None)`` merely starts the generator.
    """
    responses_iter = iter(responses)
    send_value = None
    while True:
        try:
            gen.send(send_value)
        except StopIteration as exc:
            return exc.value
        send_value = next(responses_iter, None)


CTX = {"project_name": "proj", "timestamp": "2024-01-01T00-00-00"}


class TestPhaseIngestion:
    def test_offloaded_features_path(self):
        """When parse_kml returns a claim-check ref, load_offloaded_features is used."""
        context = MagicMock()

        # Yields: parse_kml, prepare_aoi (task_all), then write_metadata (task_all).
        responses = [
            {"feature_refs": ["claims/inst-1/feature_0.json"]},
            [
                {
                    "feature_name": "A",
                    "aoi_ref": "claims/aoi-0.json",
                    "aoi_claim_index": 0,
                    "area_ha": 1.0,
                    "bbox": [0.0, 0.0, 1.0, 1.0],
                    "centroid": [0.5, 0.5],
                }
            ],
            [{"status": "ok"}],  # write_metadata
        ]

        gen = _phase_ingestion(context, {"blob_name": "x.kml"}, "inst-1", CTX)
        result = _drain(gen, responses)

        assert result["ingestion"]["offloaded"] is True
        assert result["ingestion"]["feature_count"] == 1


class TestPhaseAcquisition:
    def test_composite_full_drain_returns_ready_and_routing(self):
        context = MagicMock()
        aoi_refs = [{"key": "A", "ref": "claims/aoi-0.json"}]
        # Yields: task_all(acq_tasks) then task_all(poll_tasks).
        responses = [
            [[{"order_id": "ord-1", "aoi_feature_name": "A"}]],
            [{"order_id": "ord-1", "state": "ready", "aoi_feature_name": "A", "is_terminal": True}],
        ]

        gen = _phase_acquisition(context, {"composite_search": True}, aoi_refs, {"A": 1.0})
        result = _drain(gen, responses)

        assert result["acquisition"]["ready_count"] == 1
        assert "serverless_ready" in result
        assert "batch_ready" in result


class TestFulfilBatch:
    def test_polls_until_all_complete(self):
        """Covers the pending -> create_timer -> re-poll -> resolved loop."""
        context = MagicMock()
        context.current_utc_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        submit_result = [{"job_id": "j1", "task_id": "t1", "state": "submitted"}]
        poll_still_pending = [{"job_id": "j1", "task_id": "t1", "state": "submitted"}]
        poll_resolved = [{"job_id": "j1", "task_id": "t1", "state": "completed"}]

        gen = _fulfil_batch(
            context,
            [{"order_id": "ord-1", "aoi_feature_name": "A"}],
            {"ord-1": "https://example.test/asset"},
            "output",
            CTX,
        )
        # Yields: submit_tasks, poll(1st), create_timer, poll(2nd)
        result = _drain(gen, [submit_result, poll_still_pending, None, poll_resolved])

        assert result["batch_tracking"][0]["state"] == "completed"
        context.create_timer.assert_called_once()


class TestFulfilDownloadAndPostProcess:
    def test_fulfil_download_returns_all_results(self):
        context = MagicMock()
        download_results = [{"state": "completed", "aoi_feature_name": "A"}]

        gen = _fulfil_download(
            context,
            [{"order_id": "ord-1", "aoi_feature_name": "A"}],
            {},
            CTX,
            {},
            {},
            {"A": "claims/aoi-0.json"},
            "output",
        )
        result = _drain(gen, [download_results])

        assert result["download_results"] == download_results

    def test_fulfil_post_process_returns_all_results(self):
        context = MagicMock()
        pp_results = [{"state": "completed", "clipped": True}]

        gen = _fulfil_post_process(
            context,
            [{"state": "completed", "aoi_feature_name": "A"}],
            {},
            CTX,
            {"A": "claims/aoi-0.json"},
            "output",
        )
        result = _drain(gen, [pp_results])

        assert result["pp_results"] == pp_results


class TestPhaseFulfilment:
    def test_batch_and_serverless_paths_combined(self):
        """Covers the batch_ready branch plus the download/post-process glue."""
        context = MagicMock()
        batch_submit_result = [{"job_id": "j1", "task_id": "t1", "state": "completed"}]
        download_results = [{"state": "completed", "aoi_feature_name": "B"}]
        pp_results = [{"state": "completed", "clipped": True}]

        acq_result = {
            "serverless_ready": [{"order_id": "ord-2", "aoi_feature_name": "B"}],
            "batch_ready": [{"order_id": "ord-1", "aoi_feature_name": "A"}],
            "asset_urls": {},
            "order_meta": {},
            "aoi_ref_lookup": {"A": "claims/0.json", "B": "claims/1.json"},
        }

        gen = _phase_fulfilment(context, {}, CTX, acq_result)
        result = _drain(gen, [batch_submit_result, download_results, pp_results])

        f = result["fulfilment"]
        assert f["batch_submitted"] == 1
        assert f["batch_succeeded"] == 1
        # 1 serverless download (B) + 1 completed batch item (A).
        assert f["downloads_succeeded"] == 2
        assert f["pp_clipped"] == 1


class TestPhaseEnrichment:
    def test_no_coords_short_circuits(self):
        context = MagicMock()

        gen = _phase_enrichment(context, {}, CTX, [], [], "output")
        result = _drain(gen, [])

        assert result == {}

    def test_full_drain_with_per_aoi_fanout(self):
        context = MagicMock()
        data_sources_and_imagery = [{"weather": {}}, {"imagery": []}]
        per_aoi_results = [{"aoi": "A"}, {"aoi": "B"}]
        per_aoi_refs = [
            {"name": "A", "aoi_ref": "claims/run/aoi-0.json", "aoi_claim_index": 0},
            {"name": "B", "aoi_ref": "claims/run/aoi-1.json", "aoi_claim_index": 1},
        ]
        enrichment_manifest = {"manifest": True}
        context.task_all.side_effect = [data_sources_and_imagery, per_aoi_results]

        gen = _phase_enrichment(
            context,
            {},
            CTX,
            [[0.0, 0.0]],
            per_aoi_refs,
            "output",
        )
        result = _drain(gen, [data_sources_and_imagery, per_aoi_results, enrichment_manifest])

        assert result == enrichment_manifest
        for activity_call in context.call_activity_with_retry.call_args_list[:2]:
            payload = activity_call.args[2]
            assert "coords" not in payload
            assert payload["per_aoi_coords"] == per_aoi_refs

    def test_finalize_payload_stays_below_durable_limit_at_max_aois(self):
        import json

        from treesight.constants import MAX_FEATURES_PER_KML, PAYLOAD_OFFLOAD_THRESHOLD_BYTES

        context = MagicMock()
        context.instance_id = "run-1"
        data_sources_and_imagery = [
            {"result_ref": "claims/run-1/data_sources.json"},
            {"result_ref": "claims/run-1/imagery.json"},
        ]
        per_aoi_refs = [
            {"aoi_ref": f"claims/run-1/aoi_{index}.json", "aoi_claim_index": index}
            for index in range(MAX_FEATURES_PER_KML)
        ]
        per_aoi_results = [
            {"result_ref": f"claims/run-1/enrichment_aoi_{index}.json"} for index in range(MAX_FEATURES_PER_KML)
        ]
        context.task_all.side_effect = [data_sources_and_imagery, per_aoi_results]

        gen = _phase_enrichment(context, {}, CTX, [[0.0, 0.0]], per_aoi_refs, "output")
        _drain(gen, [data_sources_and_imagery, per_aoi_results, {"manifest": True}])

        finalize_call = next(
            call for call in context.call_activity_with_retry.call_args_list if call.args[0] == "enrich_finalize"
        )
        finalizer_payload = finalize_call.args[2]
        assert len(json.dumps(finalizer_payload).encode("utf-8")) < PAYLOAD_OFFLOAD_THRESHOLD_BYTES
        assert finalizer_payload["instance_id"] == "run-1"
        assert finalizer_payload["per_aoi_claim_indexes"] == list(range(MAX_FEATURES_PER_KML))
        assert finalizer_payload["per_aoi_result_count"] == MAX_FEATURES_PER_KML
        assert "per_aoi_coords" not in finalizer_payload
        assert "per_aoi_results" not in finalizer_payload


class TestSafeFinalizeRun:
    def test_success(self):
        context = MagicMock()

        gen = _safe_finalize_run(context, "org-1", "inst-1", "completed")
        result = _drain(gen, [{"ok": True}])

        assert result is None
        call_args = context.call_activity_with_retry.call_args
        assert call_args.args[0] == "finalize_run_completed"

    def test_exception_is_swallowed(self):
        """Best-effort finalization must not propagate activity failures."""
        context = MagicMock()

        gen = _safe_finalize_run(context, "org-1", "inst-1", "failed")
        gen.send(None)
        with pytest.raises(StopIteration):
            gen.throw(RuntimeError("activity failed"))


class TestSafeWritePipelineStats:
    def test_success(self):
        context = MagicMock()
        context.call_activity_with_retry.return_value = {"ok": True}
        ing = {"ingestion": {"aoi_count": 1}}

        gen = _safe_write_pipeline_stats(context, {"user_id": "u1", "tier": "free"}, ing, {}, {}, {}, "inst-1")
        result = _drain(gen, [{"ok": True}])

        assert result is None
        call_args = context.call_activity_with_retry.call_args
        assert call_args.args[0] == "write_pipeline_stats"

    def test_exception_is_swallowed(self):
        """Best-effort telemetry write must not propagate activity failures."""
        context = MagicMock()
        ing = {"ingestion": {"aoi_count": 1}}

        gen = _safe_write_pipeline_stats(context, {}, ing, {}, {}, {}, "inst-1")
        gen.send(None)
        with pytest.raises(StopIteration):
            gen.throw(RuntimeError("cosmos write failed"))
