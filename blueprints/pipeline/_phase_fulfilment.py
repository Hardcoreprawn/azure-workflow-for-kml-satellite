"""Orchestrator phase 3 — fulfilment: download, post-process, Azure Batch routing.

Extracted from orchestrator.py (#1292). No behavior change from the extraction.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import logging
from collections.abc import Generator
from typing import Any, cast

import azure.durable_functions as df

from treesight.config import config_get_int
from treesight.constants import (
    ACTIVITY_RETRY_FIRST_INTERVAL_MS,
    ACTIVITY_RETRY_MAX_ATTEMPTS,
    BATCH_POLL_INTERVAL_SECONDS,
    DEFAULT_DOWNLOAD_BATCH_SIZE,
    DEFAULT_OUTPUT_CONTAINER,
    DEFAULT_POST_PROCESS_BATCH_SIZE,
    LONG_RETRY_FIRST_INTERVAL_MS,
    LONG_RETRY_MAX_ATTEMPTS,
    MAX_POLL_ITERATIONS,
)

from ._payloads import _download_payload, _post_process_payload

logger = logging.getLogger(__name__)

_PhaseGen = Generator[Any, Any, dict[str, Any]]


def _fulfil_batch(
    context: df.DurableOrchestrationContext,
    batch_ready: list[dict[str, Any]],
    asset_urls: dict[str, str],
    output_container: str,
    ctx: dict[str, str],
) -> _PhaseGen:
    """Submit oversized AOIs to Azure Batch and poll until complete."""
    context.set_custom_status(
        {"phase": "fulfilment", "step": "batch_submit", "count": len(batch_ready)}
    )
    batch_submit_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=LONG_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=LONG_RETRY_MAX_ATTEMPTS,
    )
    submit_tasks = [
        context.call_activity_with_retry(
            "submit_batch_fulfilment",
            batch_submit_retry,
            {
                "outcome": outcome,
                "asset_url": asset_urls.get(outcome.get("order_id", ""), ""),
                "output_container": output_container,
                "project_name": ctx["project_name"],
                "timestamp": ctx["timestamp"],
            },
        )
        for outcome in batch_ready
    ]
    batch_tracking = cast(
        "list[dict[str, Any]]",
        (yield context.task_all(submit_tasks)),
    )

    # Poll Batch tasks until all complete (or fail)
    pending = [t for t in batch_tracking if t.get("state") == "submitted"]
    poll_iteration = 0
    while pending:
        poll_iteration += 1
        if poll_iteration > MAX_POLL_ITERATIONS:
            logger.warning("batch poll exceeded %d iterations — aborting", MAX_POLL_ITERATIONS)
            break
        context.set_custom_status(
            {"phase": "fulfilment", "step": "batch_polling", "pending": len(pending)}
        )
        batch_poll_retry = df.RetryOptions(
            first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
            max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
        )
        poll_batch_tasks = [
            context.call_activity_with_retry(
                "poll_batch_fulfilment",
                batch_poll_retry,
                {"job_id": t["job_id"], "task_id": t["task_id"]},
            )
            for t in pending
        ]
        poll_batch_results = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(poll_batch_tasks)),
        )
        state_map = {(r["job_id"], r["task_id"]): r["state"] for r in poll_batch_results}
        for t in batch_tracking:
            key = (t["job_id"], t["task_id"])
            if key in state_map:
                t["state"] = state_map[key]

        pending = [t for t in batch_tracking if t.get("state") not in ("completed", "failed")]
        if pending:
            import datetime as _dt

            fire_at = context.current_utc_datetime + _dt.timedelta(
                seconds=BATCH_POLL_INTERVAL_SECONDS
            )
            yield context.create_timer(fire_at)

    return {"batch_tracking": batch_tracking}


def _fulfil_download(
    context: df.DurableOrchestrationContext,
    serverless_ready: list[dict[str, Any]],
    inp: dict[str, Any],
    ctx: dict[str, str],
    asset_urls: dict[str, str],
    order_meta: dict[str, dict[str, str]],
    aoi_ref_lookup: dict[str, str],
    output_container: str,
) -> _PhaseGen:
    """Download serverless-tier imagery in batches."""
    batch_size = config_get_int(inp, "download_batch_size", DEFAULT_DOWNLOAD_BATCH_SIZE)
    download_results: list[dict[str, Any]] = []

    dl_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
    )

    for i in range(0, len(serverless_ready), batch_size):
        batch = serverless_ready[i : i + batch_size]
        dl_tasks = [
            context.call_activity_with_retry(
                "download_imagery",
                dl_retry,
                _download_payload(
                    outcome, inp, ctx, asset_urls, order_meta, aoi_ref_lookup, output_container
                ),
            )
            for outcome in batch
        ]
        batch_results = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(dl_tasks)),
        )
        download_results.extend(batch_results)

    return {"download_results": download_results}


def _fulfil_post_process(
    context: df.DurableOrchestrationContext,
    successful_downloads: list[dict[str, Any]],
    inp: dict[str, Any],
    ctx: dict[str, str],
    aoi_ref_lookup: dict[str, str],
    output_container: str,
) -> _PhaseGen:
    """Post-process downloaded imagery in batches."""
    context.set_custom_status(
        {"phase": "fulfilment", "step": "post_processing", "downloads": len(successful_downloads)}
    )
    pp_batch_size = config_get_int(inp, "post_process_batch_size", DEFAULT_POST_PROCESS_BATCH_SIZE)
    pp_results: list[dict[str, Any]] = []

    pp_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=LONG_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=LONG_RETRY_MAX_ATTEMPTS,
    )

    for i in range(0, len(successful_downloads), pp_batch_size):
        batch = successful_downloads[i : i + pp_batch_size]
        pp_tasks = [
            context.call_activity_with_retry(
                "post_process_imagery",
                pp_retry,
                _post_process_payload(dl, inp, ctx, aoi_ref_lookup, output_container),
            )
            for dl in batch
        ]
        batch_pp = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(pp_tasks)),
        )
        pp_results.extend(batch_pp)

    return {"pp_results": pp_results}


def _phase_fulfilment(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    ctx: dict[str, str],
    acq_result: dict[str, Any],
) -> _PhaseGen:
    """Download, post-process, and route oversized AOIs to Azure Batch."""
    output_container = inp.get("output_container", DEFAULT_OUTPUT_CONTAINER)
    serverless_ready = acq_result["serverless_ready"]
    batch_ready = acq_result["batch_ready"]
    asset_urls = acq_result["asset_urls"]
    order_meta = acq_result["order_meta"]
    aoi_ref_lookup = acq_result["aoi_ref_lookup"]

    context.set_custom_status(
        {
            "phase": "fulfilment",
            "step": "downloading",
            "ready": len(serverless_ready) + len(batch_ready),
        }
    )

    # Azure Batch path for oversized AOIs
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
        inp,
        ctx,
        asset_urls,
        order_meta,
        aoi_ref_lookup,
        output_container,
    )
    download_results = dl_result["download_results"]

    successful_downloads = [d for d in download_results if d.get("state") != "failed"]
    failed_downloads = [d for d in download_results if d.get("state") == "failed"]

    # Post-process
    pp_result = yield from _fulfil_post_process(
        context, successful_downloads, inp, ctx, aoi_ref_lookup, output_container
    )
    pp_results = pp_result["pp_results"]

    batch_succeeded = [t for t in batch_tracking if t.get("state") == "completed"]
    batch_failed_items = [t for t in batch_tracking if t.get("state") == "failed"]

    return {
        "fulfilment": {
            "download_results": download_results,
            "downloads_completed": len(download_results) + len(batch_tracking),
            "downloads_succeeded": len(successful_downloads) + len(batch_succeeded),
            "downloads_failed": len(failed_downloads) + len(batch_failed_items),
            "batch_submitted": len(batch_tracking),
            "batch_succeeded": len(batch_succeeded),
            "batch_failed": len(batch_failed_items),
            "post_process_results": pp_results,
            "pp_completed": len(pp_results),
            "pp_clipped": sum(1 for p in pp_results if p.get("clipped")),
            "pp_reprojected": sum(1 for p in pp_results if p.get("reprojected")),
            "pp_failed": sum(1 for p in pp_results if p.get("state") == "failed"),
        }
    }
