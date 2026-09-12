"""Safety regressions promoted from the local reliability fault audit."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import ResourceNotFoundError

from blueprints.pipeline._aggregation import _aggregate_aoi_results
from scripts.local_capacity import verify_artifacts
from treesight.pipeline.orchestrator import build_pipeline_summary


def _summary(ingestion: dict, acquisition: dict, fulfilment: dict) -> dict:
    return build_pipeline_summary("reliability-audit", "audit.kml", "", ingestion, acquisition, fulfilment)


@pytest.mark.parametrize(
    ("fault", "expected_status"),
    [
        ("healthy", "completed"),
        ("explicit_acquisition_failure", "partial_imagery"),
        ("explicit_download_failure", "partial_imagery"),
        ("explicit_postprocess_failure", "partial_imagery"),
        ("missing_postprocess", "partial_imagery"),
        ("missing_metadata", "partial_imagery"),
        ("missing_parcel", "completed"),
        ("empty_child", "completed"),
        ("duplicate_parcel", "completed"),
    ],
)
def test_summary_fault_characterization(fault: str, expected_status: str) -> None:
    ingestion = {"feature_count": 2, "aoi_count": 2, "metadata_count": 2}
    ingestion["metadata_results"] = [{"metadata_path": f"meta-{index}.json"} for index in range(2)]
    references = [{"ref": f"claims/{name}", "key": name} for name in ("parcel-a", "parcel-b")]
    children = [
        {
            "aoi_name": name,
            "aoi_ref": {"ref": f"claims/{name}", "key": name},
            "acquisition": {
                "ready_count": 1,
                "failed_count": 0,
                "imagery_outcomes": [{"aoi_feature_name": name, "state": "ready"}],
            },
            "fulfilment": {
                "downloads_completed": 1,
                "downloads_succeeded": 1,
                "downloads_failed": 0,
                "download_results": [{"aoi_feature_name": name, "state": "completed", "blob_path": f"raw/{name}.tif"}],
                "pp_completed": 1,
                "pp_failed": 0,
                "post_process_results": [
                    {
                        "aoi_feature_name": name,
                        "clipped": True,
                        "source_blob_path": f"raw/{name}.tif",
                        "clipped_blob_path": f"clip/{name}.tif",
                    }
                ],
            },
        }
        for name in ("parcel-a", "parcel-b")
    ]
    if fault == "explicit_acquisition_failure":
        children[1]["acquisition"]["failed_count"] = 1
        children[1]["acquisition"]["imagery_outcomes"].append({"state": "failed"})
    elif fault == "explicit_download_failure":
        children[1]["fulfilment"]["downloads_failed"] = 1
    elif fault == "explicit_postprocess_failure":
        children[1]["fulfilment"]["pp_failed"] = 1
    elif fault == "missing_postprocess":
        children[1]["fulfilment"]["pp_completed"] = 0
        children[1]["fulfilment"]["post_process_results"] = []
    elif fault == "missing_metadata":
        ingestion["metadata_count"] = 1
    elif fault == "missing_parcel":
        children.pop()
    elif fault == "empty_child":
        children[1] = {}
    elif fault == "duplicate_parcel":
        children[1] = deepcopy(children[0])

    if fault in ("missing_parcel", "empty_child", "duplicate_parcel"):
        with pytest.raises(ValueError):
            _aggregate_aoi_results(children, expected_refs=references)
        return
    acquisition, fulfilment = _aggregate_aoi_results(children, expected_refs=references)
    summary = _summary(ingestion, acquisition, fulfilment)
    assert summary["status"] == expected_status


def test_completed_batch_work_does_not_require_serverless_postprocessing() -> None:
    summary = _summary(
        {"aoi_count": 1, "metadata_count": 1, "metadata_results": [{"metadata_path": "meta.json"}]},
        {"ready_count": 2, "imagery_outcomes": [{"state": "ready"}] * 2},
        {
            "downloads_succeeded": 2,
            "downloads_completed": 2,
            "batch_succeeded": 1,
            "pp_completed": 1,
            "download_results": [{"state": "completed", "blob_path": "raw.tif"}],
            "post_process_results": [
                {"state": "completed", "source_blob_path": "raw.tif", "clipped_blob_path": "clip.tif"}
            ],
        },
    )
    assert summary["status"] == "completed"


def test_child_exception_retains_original_failure_at_aggregation() -> None:
    original = RuntimeError("original child failure")
    with pytest.raises(ValueError, match="original cause retained") as caught:
        _aggregate_aoi_results([original], expected_refs=[{"ref": "claims/1", "key": "parcel-a"}])
    assert caught.value.__cause__ is original


@pytest.mark.parametrize("fault", ["missing", "empty", "corrupt_nonempty"])
def test_artifact_verifier_fault_characterization(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    from scripts import local_capacity

    service = MagicMock()
    blob = service.__enter__.return_value.get_container_client.return_value.get_blob_client.return_value
    blob.get_blob_properties.return_value = SimpleNamespace(size=0 if fault == "empty" else len(b"not a raster"))
    blob.download_blob.return_value.readall.return_value = b"not a raster"
    if fault == "missing":
        blob.get_blob_properties.side_effect = ResourceNotFoundError("missing audit artifact")
    monkeypatch.setattr(local_capacity.BlobServiceClient, "from_connection_string", lambda *args: service)
    result = {"output": {"artifacts": {"clippedImageryPaths": ["corrupt.tif"]}, "enrichmentManifest": "manifest.json"}}
    if fault == "missing":
        with pytest.raises(ResourceNotFoundError):
            verify_artifacts(result)
    elif fault == "empty":
        with pytest.raises(ValueError, match="empty artifact"):
            verify_artifacts(result)
    else:
        with pytest.raises(ValueError, match="artifact"):
            verify_artifacts(result)
        assert all(call.kwargs["offset"] == 0 for call in blob.download_blob.call_args_list)
