"""Orchestrator phase 4 — enrichment, plus post-run finalization helpers.

Extracted from orchestrator.py (#1292). No behavior change from the extraction.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import logging
from collections.abc import Generator
from typing import Any, cast

import azure.durable_functions as df

from treesight.constants import (
    ACTIVITY_RETRY_FIRST_INTERVAL_MS,
    ACTIVITY_RETRY_MAX_ATTEMPTS,
    LONG_RETRY_FIRST_INTERVAL_MS,
    LONG_RETRY_MAX_ATTEMPTS,
)

logger = logging.getLogger(__name__)

_PhaseGen = Generator[Any, Any, dict[str, Any]]


def _phase_enrichment(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    ctx: dict[str, str],
    all_coords: list[list[float]],
    per_aoi_coords: list[dict[str, Any]],
    output_container: str,
) -> _PhaseGen:
    """Fetch weather, NDVI, mosaics, and build enrichment manifest.

    Fan-out structure (parallel where possible):

    1. ``enrich_data_sources`` ∥ ``enrich_imagery`` — independent I/O
    2. ``enrich_single_aoi`` × N — per-AOI fan-out (parallel)
    3. ``enrich_finalize`` — merge + manifest (sequential)
    """
    if not all_coords:
        return {}

    enrichment_retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=LONG_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=LONG_RETRY_MAX_ATTEMPTS,
    )

    enrichment_common = {
        "coords": all_coords,
        "eudr_mode": inp.get("eudr_mode", False),
        "date_start": inp.get("date_start"),
        "date_end": inp.get("date_end"),
        "cadence": inp.get("cadence", "maximum"),
        "max_history_years": inp.get("max_history_years"),
        "project_name": ctx["project_name"],
        "timestamp": ctx["timestamp"],
        "output_container": output_container,
    }

    # ── Step 1: data sources ∥ imagery (parallel fan-out) ─────
    context.set_custom_status({"phase": "enrichment", "step": "data_sources_and_imagery"})
    parallel_tasks = [
        context.call_activity_with_retry(
            "enrich_data_sources", enrichment_retry, enrichment_common
        ),
        context.call_activity_with_retry("enrich_imagery", enrichment_retry, enrichment_common),
    ]
    data_sources, imagery = cast(
        "list[dict[str, Any]]",
        (yield context.task_all(parallel_tasks)),
    )

    # ── Step 2: per-AOI enrichment (parallel fan-out, one per AOI) ──
    per_aoi_results: list[dict[str, Any]] = []
    if per_aoi_coords and len(per_aoi_coords) > 1:
        context.set_custom_status(
            {"phase": "enrichment", "step": "per_aoi", "aois": len(per_aoi_coords)}
        )
        aoi_tasks = [
            context.call_activity_with_retry(
                "enrich_single_aoi",
                enrichment_retry,
                {
                    "aoi_entry": entry,
                    **{k: v for k, v in enrichment_common.items() if k != "coords"},
                },
            )
            for entry in per_aoi_coords
        ]
        per_aoi_results = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(aoi_tasks)),
        )

    # ── Step 3: merge + manifest (sequential) ────────────────
    context.set_custom_status({"phase": "enrichment", "step": "finalizing"})
    enrichment = cast(
        "dict[str, Any]",
        (
            yield context.call_activity_with_retry(
                "enrich_finalize",
                enrichment_retry,
                {
                    "data_sources": data_sources,
                    "imagery": imagery,
                    "per_aoi_results": per_aoi_results,
                    "eudr_mode": inp.get("eudr_mode", False),
                    "date_start": inp.get("date_start"),
                    "project_name": ctx["project_name"],
                    "timestamp": ctx["timestamp"],
                    "output_container": output_container,
                },
            )
        ),
    )
    return enrichment


def _safe_finalize_run(
    context: df.DurableOrchestrationContext,
    org_id: str,
    instance_id: str,
    status: str,
) -> Generator[Any, Any, None]:
    """Finalize a run in org-pooled accounting (#814)."""
    retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=ACTIVITY_RETRY_MAX_ATTEMPTS,
    )
    activity_name = "finalize_run_completed" if status == "completed" else "finalize_run_failed"
    try:
        yield context.call_activity_with_retry(
            activity_name,
            retry,
            {"org_id": org_id, "instance_id": instance_id},
        )
    except Exception:
        logger.exception(
            "Failed to finalize run (%s) org=%s instance=%s", status, org_id, instance_id
        )


def _safe_write_pipeline_stats(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    ing: dict[str, Any],
    acq_s: dict[str, Any],
    ful_s: dict[str, Any],
    enrichment: dict[str, Any],
    instance_id: str,
    started_at: str | None = None,
) -> Generator[Any, Any, None]:
    """Write per-run telemetry to Cosmos — best-effort, never blocks the result (#400)."""
    retry = df.RetryOptions(
        first_retry_interval_in_milliseconds=ACTIVITY_RETRY_FIRST_INTERVAL_MS,
        max_number_of_attempts=2,  # one retry, as documented
    )
    payload: dict[str, Any] = {
        "instance_id": instance_id,
        "user_id": inp.get("user_id", ""),
        "tier": inp.get("tier", ""),
        "aoi_count": ing["ingestion"].get("aoi_count", 0),
        "aoi_area_by_name": ing.get("aoi_area_by_name", {}),
        "aoi_centroids": ing.get("aoi_centroids", []),
        "image_count": acq_s.get("ready_count", 0),
        "batch_used": bool(ful_s.get("batch_submitted", 0)),
        "enrichment": enrichment,
        "started_at": started_at,
        "status": "completed",
    }
    try:
        yield context.call_activity_with_retry("write_pipeline_stats", retry, payload)
    except Exception:
        logger.exception("Failed to write pipeline stats (non-fatal) instance=%s", instance_id)
