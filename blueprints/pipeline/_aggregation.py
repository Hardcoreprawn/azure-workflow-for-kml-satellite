"""Result aggregation for progressive per-AOI sub-orchestrator delivery (#585).

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from typing import Any


def _aggregate_aoi_results(
    aoi_results: list[dict[str, Any]],
    *,
    expected_refs: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge per-AOI sub-orchestrator results into acquisition and fulfilment summaries.

    Returns ``(acquisition_summary, fulfilment_summary)`` matching the shapes
    expected by ``build_pipeline_summary``.
    """
    _validate_aoi_results(aoi_results, expected_refs)
    acq: dict[str, Any] = {"imagery_outcomes": [], "ready_count": 0, "failed_count": 0}
    ful: dict[str, Any] = {
        "download_results": [],
        "downloads_completed": 0,
        "downloads_succeeded": 0,
        "downloads_failed": 0,
        "batch_submitted": 0,
        "batch_succeeded": 0,
        "batch_failed": 0,
        "post_process_results": [],
        "pp_completed": 0,
        "pp_clipped": 0,
        "pp_reprojected": 0,
        "pp_failed": 0,
    }

    for r in aoi_results:
        a = r.get("acquisition", {})
        acq["ready_count"] += a.get("ready_count", 0)
        acq["failed_count"] += a.get("failed_count", 0)
        acq["imagery_outcomes"].extend(a.get("imagery_outcomes", []))

        f = r.get("fulfilment", {})
        succeeded = f.get("downloads_succeeded", 0)
        failed = f.get("downloads_failed", 0)
        ful["download_results"].extend(f.get("download_results", []))
        ful["downloads_completed"] += f.get("downloads_completed", 0)
        ful["downloads_succeeded"] += succeeded
        ful["downloads_failed"] += failed
        ful["batch_submitted"] += f.get("batch_submitted", 0)
        ful["batch_succeeded"] += f.get("batch_succeeded", 0)
        ful["batch_failed"] += f.get("batch_failed", 0)
        ful["post_process_results"].extend(f.get("post_process_results", []))
        ful["pp_completed"] += f.get("pp_completed", 0)
        ful["pp_clipped"] += f.get("pp_clipped", 0)
        ful["pp_reprojected"] += f.get("pp_reprojected", 0)
        ful["pp_failed"] += f.get("pp_failed", 0)

    return acq, ful


def _validate_aoi_results(results: list[dict[str, Any]], expected_refs: list[dict[str, str]]) -> None:
    expected = {(ref["ref"], ref["key"]) for ref in expected_refs}
    if len(expected) != len(expected_refs) or len(results) != len(expected):
        raise ValueError("AOI result count or expected identity mismatch")
    observed = set()
    for result in results:
        if isinstance(result, Exception):
            raise ValueError("AOI child failed; original cause retained") from result
        if not isinstance(result, dict):
            raise ValueError("malformed AOI child result")
        ref = result.get("aoi_ref")
        if not isinstance(ref, dict) or not all(isinstance(ref.get(key), str) for key in ("ref", "key")):
            raise ValueError("missing AOI child reference")
        identity = (ref["ref"], ref["key"])
        if identity not in expected or identity in observed or result.get("aoi_name") != ref["key"]:
            raise ValueError("unexpected or duplicate AOI child identity")
        if not all(isinstance(result.get(key), dict) for key in ("acquisition", "fulfilment")):
            raise ValueError("missing AOI child phase results")
        _validate_phase_counts(result)
        observed.add(identity)


def _validate_phase_counts(result: dict[str, Any]) -> None:
    acquisition, fulfilment = result["acquisition"], result["fulfilment"]
    required = (
        (acquisition, ("ready_count", "failed_count"), "imagery_outcomes"),
        (fulfilment, ("downloads_completed", "downloads_succeeded", "downloads_failed"), "download_results"),
        (fulfilment, ("pp_completed", "pp_failed"), "post_process_results"),
    )
    for phase, counts, records in required:
        if not isinstance(phase.get(records), list) or not all(
            type(phase.get(key)) is int and phase[key] >= 0 for key in counts
        ):
            raise ValueError("missing or invalid AOI phase fields")
        if not all(isinstance(record, dict) for record in phase[records]):
            raise ValueError("invalid AOI phase record")
    if acquisition["ready_count"] + acquisition["failed_count"] != len(acquisition["imagery_outcomes"]):
        raise ValueError("AOI acquisition count does not match phase records")
    if fulfilment["downloads_completed"] != len(fulfilment["download_results"]) + fulfilment.get("batch_submitted", 0):
        raise ValueError("AOI download count does not match phase records")
    if fulfilment["pp_completed"] != len(fulfilment["post_process_results"]):
        raise ValueError("AOI postprocess count does not match phase records")
