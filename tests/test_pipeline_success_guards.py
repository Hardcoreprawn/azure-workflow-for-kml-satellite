from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from blueprints.pipeline._aggregation import _aggregate_aoi_results


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


@pytest.mark.parametrize("fault", ["missing", "empty", "duplicate", "unexpected", "exception"])
def test_fan_in_rejects_unreconciled_child_results(fault: str) -> None:
    references = [{"ref": "claims/1", "key": "same name"}, {"ref": "claims/2", "key": "same name"}]
    results = [{"aoi_ref": ref, "aoi_name": ref["key"], "acquisition": {}, "fulfilment": {}} for ref in references]
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
    with pytest.raises(ValueError):
        _aggregate_aoi_results(results, expected_refs=references)


def test_fan_in_accepts_out_of_order_results_with_duplicate_display_names() -> None:
    from tests.test_pipeline import _make_aoi_result

    references = [{"ref": "claims/1", "key": "same name"}, {"ref": "claims/2", "key": "same name"}]
    results = [{**_make_aoi_result(ref["key"]), "aoi_ref": ref} for ref in reversed(references)]
    acquisition, _ = _aggregate_aoi_results(results, expected_refs=references)
    assert acquisition["ready_count"] == 2
