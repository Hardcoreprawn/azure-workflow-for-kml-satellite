"""Result aggregation for progressive per-AOI sub-orchestrator delivery (#585).

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from typing import Any


def _aggregate_aoi_results(
    aoi_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge per-AOI sub-orchestrator results into acquisition and fulfilment summaries.

    Returns ``(acquisition_summary, fulfilment_summary)`` matching the shapes
    expected by ``build_pipeline_summary``.
    """
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
