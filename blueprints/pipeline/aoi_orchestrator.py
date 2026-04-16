"""Per-AOI sub-orchestrator: acquire → fulfil for a single AOI (#585).

Runs independently per AOI so multi-polygon submissions process in
parallel instead of phase-by-phase.  The main orchestrator fans out
one sub-orchestrator per AOI and aggregates results.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from collections.abc import Generator
from typing import Any, cast

import azure.durable_functions as df

from treesight.constants import (
    ACTIVITY_RETRY_FIRST_INTERVAL_MS,
    ACTIVITY_RETRY_MAX_ATTEMPTS,
    DEFAULT_OUTPUT_CONTAINER,
)

from . import bp
from ._helpers import (
    _acq_payload,
    _build_order_lookups,
    _poll_payload,
    _split_batch_routing,
)
from .orchestrator import _fulfil_batch, _fulfil_download, _fulfil_post_process

_PhaseGen = Generator[Any, Any, dict[str, Any]]


# ---------------------------------------------------------------------------
# Step 1 — Acquire imagery for one AOI
# ---------------------------------------------------------------------------


def _aoi_acquire(
    context: df.DurableOrchestrationContext,
    pipeline_inp: dict[str, Any],
    aoi_ref: dict[str, str],
) -> _PhaseGen:
    """Search for imagery and poll orders for a single AOI."""
    composite = bool(pipeline_inp.get("composite_search", True))
    activity = "acquire_composite" if composite else "acquire_imagery"

    acq_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
    )

    acq_result = cast(
        "Any",
        (
            yield context.call_activity_with_retry(
                activity, acq_retry, _acq_payload(aoi_ref, pipeline_inp, composite)
            )
        ),
    )

    # Normalize: composite returns list of orders, non-composite returns one
    orders: list[dict[str, Any]] = acq_result if composite else [acq_result]

    # Poll orders — use DF-level retry for resilience against transient failures.
    poll_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
    )
    poll_tasks = [
        context.call_activity_with_retry("poll_order", poll_retry, _poll_payload(o, pipeline_inp))
        for o in orders
        if o.get("order_id")
    ]
    poll_results = cast(
        "list[dict[str, Any]]",
        (yield context.task_all(poll_tasks)) if poll_tasks else [],
    )

    ready = [r for r in poll_results if r.get("state") == "ready"]
    asset_urls, order_meta = _build_order_lookups(orders)

    return {
        "ready": ready,
        "asset_urls": asset_urls,
        "order_meta": order_meta,
        "acquisition": {
            "imagery_outcomes": poll_results,
            "ready_count": len(ready),
            "failed_count": len(poll_results) - len(ready),
        },
    }


# ---------------------------------------------------------------------------
# Step 2 — Download + post-process for one AOI
# ---------------------------------------------------------------------------


def _aoi_fulfil(
    context: df.DurableOrchestrationContext,
    pipeline_inp: dict[str, Any],
    ctx: dict[str, str],
    acq: dict[str, Any],
    aoi_ref: dict[str, str],
    aoi_area_ha: float,
    output_container: str,
) -> _PhaseGen:
    """Download and post-process imagery for a single AOI."""
    aoi_name = aoi_ref["key"]
    aoi_ref_lookup = {aoi_name: aoi_ref["ref"]}
    ready = acq["ready"]
    asset_urls = acq["asset_urls"]
    order_meta = acq["order_meta"]

    serverless_ready, batch_ready = _split_batch_routing(ready, {aoi_name: aoi_area_ha})

    # Batch path (oversized AOI)
    batch_tracking: list[dict[str, Any]] = []
    if batch_ready:
        batch_result = yield from _fulfil_batch(
            context, batch_ready, asset_urls, output_container, ctx
        )
        batch_tracking = batch_result["batch_tracking"]

    # Serverless download path
    dl_result = yield from _fulfil_download(
        context,
        serverless_ready,
        pipeline_inp,
        ctx,
        asset_urls,
        order_meta,
        aoi_ref_lookup,
        output_container,
    )
    download_results = dl_result["download_results"]
    successful = [d for d in download_results if d.get("state") != "failed"]
    failed_dl = [d for d in download_results if d.get("state") == "failed"]

    # Post-process
    pp_result = yield from _fulfil_post_process(
        context, successful, pipeline_inp, ctx, aoi_ref_lookup, output_container
    )
    pp_results = pp_result["pp_results"]

    batch_ok = [t for t in batch_tracking if t.get("state") == "completed"]
    batch_bad = [t for t in batch_tracking if t.get("state") == "failed"]

    return {
        "fulfilment": {
            "download_results": download_results,
            "downloads_completed": len(download_results) + len(batch_tracking),
            "downloads_succeeded": len(successful) + len(batch_ok),
            "downloads_failed": len(failed_dl) + len(batch_bad),
            "batch_submitted": len(batch_tracking),
            "batch_succeeded": len(batch_ok),
            "batch_failed": len(batch_bad),
            "post_process_results": pp_results,
            "pp_completed": len(pp_results),
            "pp_clipped": sum(1 for p in pp_results if p.get("clipped")),
            "pp_reprojected": sum(1 for p in pp_results if p.get("reprojected")),
            "pp_failed": sum(1 for p in pp_results if p.get("state") == "failed"),
        },
    }


# ---------------------------------------------------------------------------
# Sub-orchestrator entry point
# ---------------------------------------------------------------------------


@bp.orchestration_trigger(context_name="context")
def aoi_pipeline(context: df.DurableOrchestrationContext):  # type: ignore[return-type]
    """Per-AOI sub-orchestrator: acquire → fulfil for a single AOI.

    Called by the main orchestrator via ``call_sub_orchestrator``.
    Returns acquisition + fulfilment results for aggregation.
    """
    inp = cast("dict[str, Any]", context.get_input() or {})
    aoi_ref: dict[str, str] = inp["aoi_ref"]
    pipeline_inp: dict[str, Any] = inp["pipeline_input"]
    ctx: dict[str, str] = inp["project_context"]
    aoi_area_ha: float = inp.get("aoi_area_ha", 0.0)
    aoi_name: str = aoi_ref["key"]
    output_container: str = pipeline_inp.get("output_container", DEFAULT_OUTPUT_CONTAINER)

    context.set_custom_status({"aoi": aoi_name, "step": "acquiring"})
    acq = yield from _aoi_acquire(context, pipeline_inp, aoi_ref)

    context.set_custom_status({"aoi": aoi_name, "step": "downloading"})
    ful = yield from _aoi_fulfil(
        context, pipeline_inp, ctx, acq, aoi_ref, aoi_area_ha, output_container
    )

    context.set_custom_status({"aoi": aoi_name, "step": "completed"})

    return {
        "aoi_name": aoi_name,
        "acquisition": acq["acquisition"],
        "fulfilment": ful["fulfilment"],
    }
