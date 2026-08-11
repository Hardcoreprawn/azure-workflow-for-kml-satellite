"""Orchestrator phase 2 — acquisition: search for imagery and poll until ready.

Extracted from orchestrator.py (#1292). No behavior change from the extraction.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from collections.abc import Generator
from datetime import timedelta
from typing import Any, cast

import azure.durable_functions as df

from treesight.config import config_get_int
from treesight.constants import (
    ACTIVITY_RETRY_FIRST_INTERVAL_MS,
    ACTIVITY_RETRY_MAX_ATTEMPTS,
    DEFAULT_ACQUISITION_BATCH_SIZE,
    DEFAULT_POLL_INTERVAL_SECONDS,
    MAX_POLL_ITERATIONS,
)

from ._payloads import _acq_payload, _build_order_lookups, _poll_payload, _split_batch_routing

_PhaseGen = Generator[Any, Any, dict[str, Any]]


def _monitor_orders(
    context: df.DurableOrchestrationContext,
    orders: list[dict[str, Any]],
    poll_retry: df.RetryOptions,
    poll_interval: int,
    inp: dict[str, Any],
) -> Generator[Any, Any, list[dict[str, Any]]]:
    """DF monitor-pattern poll loop for a batch of orders.

    Calls ``check_order_status`` (single-shot, no sleep) for all pending
    orders per round, waits ``poll_interval`` seconds via a durable timer
    between rounds, and caps at ``MAX_POLL_ITERATIONS`` rounds.  Orders
    that exceed the cap are marked ``acquisition_timeout``.

    Returns a flat list of completed order dicts (original order fields merged
    with the status returned by ``check_order_status``).
    """
    pending = [o for o in orders if o.get("order_id")]
    completed: dict[str, dict[str, Any]] = {}

    for _iteration in range(MAX_POLL_ITERATIONS):
        if not pending:
            break

        status_tasks = [
            context.call_activity_with_retry("check_order_status", poll_retry, _poll_payload(o, inp)) for o in pending
        ]
        statuses = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(status_tasks)),
        )

        still_pending: list[dict[str, Any]] = []
        for order, status in zip(pending, statuses, strict=True):
            if status.get("is_terminal"):
                completed[order["order_id"]] = {**order, **status}
            else:
                still_pending.append(order)
        pending = still_pending

        if pending:
            fire_at = context.current_utc_datetime + timedelta(seconds=poll_interval)
            yield context.create_timer(fire_at)

    for order in pending:
        completed[order["order_id"]] = {
            **order,
            "state": "acquisition_timeout",
            "is_terminal": True,
            "error": f"Exceeded {MAX_POLL_ITERATIONS} poll iterations",
        }

    return list(completed.values())


def _phase_acquisition(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    aoi_refs: list[dict[str, str]],
    aoi_area_by_name: dict[str, float],
) -> _PhaseGen:
    """Search for imagery and poll until orders are ready."""
    context.set_custom_status({"phase": "acquisition", "step": "searching", "aois": len(aoi_refs)})
    composite = bool(inp.get("composite_search", True))
    acq_batch_size = max(1, config_get_int(inp, "acquisition_batch_size", DEFAULT_ACQUISITION_BATCH_SIZE))

    # Retry options for transient provider failures (STAC API timeouts, 5xx).
    acq_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
    )

    orders: list[dict[str, Any]] = []
    for i in range(0, len(aoi_refs), acq_batch_size):
        batch_refs = aoi_refs[i : i + acq_batch_size]
        activity = "acquire_composite" if composite else "acquire_imagery"
        acq_tasks = [
            context.call_activity_with_retry(activity, acq_retry, _acq_payload(ref, inp, composite))
            for ref in batch_refs
        ]
        batch_results = cast(
            "list[Any]",
            (yield context.task_all(acq_tasks)),
        )
        if composite:
            for order_list in batch_results:
                orders.extend(order_list)
        else:
            orders.extend(batch_results)

    # Poll orders — DF monitor pattern: single-shot activity + durable timer.
    context.set_custom_status({"phase": "acquisition", "step": "polling", "orders": len(orders)})
    poll_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
    )
    poll_interval = config_get_int(inp, "poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)

    poll_results = cast(
        "list[dict[str, Any]]",
        (yield from _monitor_orders(context, orders, poll_retry, poll_interval, inp)),
    )

    ready = [r for r in poll_results if r.get("state") == "ready"]
    failed = [r for r in poll_results if r.get("state") != "ready"]
    asset_urls, order_meta = _build_order_lookups(orders)

    # Build AOI ref lookup for fulfilment (key → ref)
    aoi_ref_lookup: dict[str, str] = {}
    for r in aoi_refs:
        if r["key"] in aoi_ref_lookup:
            raise ValueError(f"Duplicate AOI key: {r['key']}")
        aoi_ref_lookup[r["key"]] = r["ref"]

    # Split ready imagery: oversized AOIs → Azure Batch, normal → serverless
    serverless_ready, batch_ready = _split_batch_routing(ready, aoi_area_by_name)

    return {
        "acquisition": {
            "imagery_outcomes": poll_results,
            "ready_count": len(ready),
            "failed_count": len(failed),
        },
        "ready": ready,
        "serverless_ready": serverless_ready,
        "batch_ready": batch_ready,
        "asset_urls": asset_urls,
        "order_meta": order_meta,
        "aoi_ref_lookup": aoi_ref_lookup,
    }
