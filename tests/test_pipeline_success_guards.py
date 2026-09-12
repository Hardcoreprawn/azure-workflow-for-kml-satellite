from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from blueprints.pipeline._aggregation import _aggregate_aoi_results


@pytest.mark.parametrize(
    "fault", ["none", "duplicate-download", "wrong-source", "missing-output", "aliased-output", "no-imagery"]
)
def test_summary_reconciles_output_identity_and_retains_partial_evidence(fault: str) -> None:
    from treesight.models.outcomes import PipelineSummary

    summary = PipelineSummary.model_validate(
        {
            "aoi_count": 2,
            "metadata_count": 2,
            "imagery_ready": 2,
            "downloads_completed": 2,
            "downloads_succeeded": 2,
            "post_process_completed": 2,
            "metadata_results": [{"metadata_path": f"meta/{index}.json"} for index in range(2)],
            "imagery_outcomes": [{"state": "ready"}] * 2,
            "download_results": [{"blob_path": f"raw/{index}.tif"} for index in range(2)],
            "post_process_results": [
                {"source_blob_path": f"raw/{index}.tif", "clipped_blob_path": f"clip/{index}.tif"} for index in range(2)
            ],
        }
    )
    if fault == "duplicate-download":
        summary.download_results[1].blob_path = summary.download_results[0].blob_path
    elif fault == "wrong-source":
        summary.post_process_results[1].source_blob_path = "other-run.tif"
    elif fault == "missing-output":
        summary.post_process_results[1].clipped_blob_path = ""
    elif fault == "aliased-output":
        summary.post_process_results[1].clipped_blob_path = summary.download_results[1].blob_path
    elif fault == "no-imagery":
        summary.imagery_ready = 0
        summary.imagery_outcomes = []
        summary.downloads_succeeded = summary.downloads_completed = summary.post_process_completed = 0
        summary.download_results = []
        summary.post_process_results = []
    summary.compute_status()
    assert summary.status == ("completed" if fault == "none" else "partial_imagery")
    assert len(summary.artifacts["metadataPaths"]) == 2


@pytest.mark.parametrize("fault", ["none", "swapped", "missing", "unexpected", "exception"])
def test_dispatch_validates_out_of_order_winners_against_their_tasks(fault: str) -> None:
    from blueprints.pipeline.orchestrator import _dispatch_acq_ful
    from tests.test_pipeline import _make_aoi_result

    refs = [{"ref": "claims/first", "key": "same"}, {"ref": "claims/second", "key": "same"}]
    tasks = [MagicMock(result={**_make_aoi_result("same"), "aoi_ref": ref}) for ref in refs]
    if fault == "swapped":
        tasks[0].result["aoi_ref"], tasks[1].result["aoi_ref"] = refs[1], refs[0]
    elif fault == "missing":
        tasks[1].result.pop("aoi_ref")
    elif fault == "unexpected":
        tasks[1].result["aoi_ref"] = {"ref": "claims/other", "key": "same"}
    elif fault == "exception":
        tasks[1].result = RuntimeError("original child cause")
    context = MagicMock()
    context.call_sub_orchestrator.side_effect = tasks
    generator = _dispatch_acq_ful(context, {}, {}, {"aoi_refs": refs, "aoi_area_by_name": {}}, "run")
    next(generator)
    if fault != "none":
        with pytest.raises(ValueError):
            generator.send(tasks[1])
        return
    generator.send(tasks[1])
    with pytest.raises(StopIteration) as completed:
        generator.send(tasks[0])
    assert completed.value.value[0]["ready_count"] == 2


@pytest.mark.parametrize("fault", ["empty", "claimed_counts", "failed_record"])
def test_summary_cannot_complete_without_successful_records(fault: str) -> None:
    from treesight.models.outcomes import PipelineSummary

    data = (
        {}
        if fault == "empty"
        else {
            "aoi_count": 1,
            "metadata_count": 1,
            "imagery_ready": 1,
            "downloads_completed": 1,
            "downloads_succeeded": 1,
            "post_process_completed": 1,
        }
    )
    if fault == "failed_record":
        data.update(
            metadata_results=[{"metadata_path": "meta.json"}],
            imagery_outcomes=[{"state": "failed"}],
            download_results=[{"state": "completed", "blob_path": "raw.tif"}],
            post_process_results=[{"state": "completed", "clipped_blob_path": "clip.tif"}],
        )
    summary = PipelineSummary.model_validate(data)
    summary.compute_status()
    assert summary.status == "partial_imagery"


def test_project_context_uses_recorded_time_for_replay() -> None:
    from treesight.pipeline.orchestrator import derive_project_context

    recorded = datetime(2026, 9, 11, 1, 2, 3, tzinfo=UTC)
    assert derive_project_context("fixture.kml", recorded)["timestamp"] == "20260911T010203Z"


def test_identified_child_cannot_omit_phase_fields() -> None:
    ref = {"ref": "claims/1", "key": "A"}
    with pytest.raises(ValueError, match="phase"):
        _aggregate_aoi_results(
            [{"aoi_ref": ref, "aoi_name": "A", "acquisition": {}, "fulfilment": {}}], expected_refs=[ref]
        )


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("missing", "count or expected identity mismatch"),
        ("empty", "missing AOI child reference"),
        ("duplicate", "unexpected or duplicate AOI child identity"),
        ("unexpected", "unexpected or duplicate AOI child identity"),
        ("exception", "original cause retained"),
    ],
)
def test_fan_in_rejects_unreconciled_child_results(fault: str, message: str) -> None:
    from tests.test_pipeline import _make_aoi_result

    references = [{"ref": "claims/1", "key": "same name"}, {"ref": "claims/2", "key": "same name"}]
    results = [{**_make_aoi_result(ref["key"]), "aoi_ref": ref} for ref in references]
    if fault == "missing":
        results.pop()
    elif fault == "empty":
        results[1] = {}
    elif fault == "duplicate":
        results[1] = deepcopy(results[0])
    elif fault == "unexpected":
        results[1]["aoi_ref"] = {"ref": "claims/other", "key": "same name"}
    elif fault == "exception":
        results[1] = RuntimeError("original child failure")
    with pytest.raises(ValueError, match=message) as caught:
        _aggregate_aoi_results(results, expected_refs=references)
    if fault == "exception":
        assert caught.value.__cause__ is results[1]


def test_fan_in_accepts_out_of_order_results_with_duplicate_display_names() -> None:
    from tests.test_pipeline import _make_aoi_result

    references = [{"ref": "claims/1", "key": "same name"}, {"ref": "claims/2", "key": "same name"}]
    results = [{**_make_aoi_result(ref["key"]), "aoi_ref": ref} for ref in reversed(references)]
    acquisition, _ = _aggregate_aoi_results(results, expected_refs=references)
    assert acquisition["ready_count"] == 2
