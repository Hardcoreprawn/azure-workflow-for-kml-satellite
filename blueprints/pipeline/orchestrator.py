"""Durable orchestrator: four-phase sequential pipeline with fan-out parallelism.

Uses claim-check pattern to keep orchestrator history entries below 48 KiB
regardless of AOI count.  AOI geometry is stored in blob storage after
ingestion; subsequent phases receive only lightweight ``{ref, key}`` refs.

Each phase is a generator function that yields Durable Functions tasks
and returns a result dict.  Phase implementations live in sibling
``_phase_*`` modules (#1292); this module keeps the top-level coordinator
flow (``treesight_orchestrator``) and the progressive per-AOI dispatch.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import logging
from collections.abc import Generator
from typing import Any, cast

import azure.durable_functions as df

from treesight.constants import DEFAULT_OUTPUT_CONTAINER
from treesight.pipeline.orchestrator import build_pipeline_summary, derive_project_context

from . import bp
from ._aggregation import _aggregate_aoi_results
from ._phase_acquisition import _phase_acquisition
from ._phase_enrichment import _phase_enrichment, _safe_finalize_run, _safe_write_pipeline_stats

# _fulfil_batch/_fulfil_download/_fulfil_post_process aren't called directly in
# this module anymore, but aoi_orchestrator.py imports them from here — keep
# the re-export (`as` self-alias tells ruff this is intentional, not dead F401).
from ._phase_fulfilment import (
    _fulfil_batch as _fulfil_batch,
)
from ._phase_fulfilment import (
    _fulfil_download as _fulfil_download,
)
from ._phase_fulfilment import (
    _fulfil_post_process as _fulfil_post_process,
)
from ._phase_fulfilment import _phase_fulfilment
from ._phase_ingestion import _phase_ingestion

logger = logging.getLogger(__name__)

# Type alias for phase generator functions.  Each yields Durable tasks
# to the orchestrator runtime and returns a result dict.
_PhaseGen = Generator[Any, Any, dict[str, Any]]


# ---------------------------------------------------------------------------
# Progressive delivery — sub-orchestrator fan-out (#585)
# ---------------------------------------------------------------------------


def _progressive_pipeline(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    ctx: dict[str, str],
    ing: dict[str, Any],
    instance_id: str,
) -> _PhaseGen:
    """Fan out per-AOI sub-orchestrators for parallel acquisition + fulfilment.

    Each sub-orchestrator handles acquire → download → post-process for one
    AOI independently.  Returns a list of per-AOI result dicts.
    """
    aoi_refs: list[dict[str, str]] = ing["aoi_refs"]
    aoi_area_by_name: dict[str, float] = ing["aoi_area_by_name"]
    total = len(aoi_refs)

    context.set_custom_status(
        {
            "phase": "per_aoi_pipeline",
            "completed_aois": 0,
            "total_aois": total,
        }
    )

    sub_tasks = []
    for i, ref in enumerate(aoi_refs):
        task = context.call_sub_orchestrator(
            "aoi_pipeline",
            input_={
                "aoi_ref": ref,
                "aoi_area_ha": aoi_area_by_name.get(ref["key"], 0.0),
                "pipeline_input": inp,
                "project_context": ctx,
            },
            instance_id=f"{instance_id}:aoi-{i}",
        )
        sub_tasks.append(task)

    # Progressive: task_any loop updates status after each AOI completes
    pending = list(sub_tasks)
    all_results: list[dict[str, Any]] = []
    while pending:
        winner = yield context.task_any(pending)
        all_results.append(winner.result)
        pending.remove(winner)
        context.set_custom_status(
            {
                "phase": "per_aoi_pipeline",
                "completed_aois": len(all_results),
                "total_aois": total,
            }
        )

    return {"aoi_results": all_results}


def _dispatch_acq_ful(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    ctx: dict[str, str],
    ing: dict[str, Any],
    instance_id: str,
) -> Generator[Any, Any, tuple[dict[str, Any], dict[str, Any]]]:
    """Route acquisition + fulfilment: sub-orchestrators for multi-AOI, direct for single."""
    if len(ing["aoi_refs"]) > 1:
        prog = yield from _progressive_pipeline(context, inp, ctx, ing, instance_id)
        return _aggregate_aoi_results(prog["aoi_results"])
    acq = yield from _phase_acquisition(context, inp, ing["aoi_refs"], ing["aoi_area_by_name"])
    ful = yield from _phase_fulfilment(context, inp, ctx, acq)
    return acq["acquisition"], ful["fulfilment"]


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


def _apply_enrichment_to_summary(summary: dict[str, Any], enrichment: dict[str, Any]) -> None:
    """Copy enrichment outputs into the pipeline summary."""
    if enrichment.get("manifest_path"):
        summary["enrichment_manifest"] = enrichment["manifest_path"]
        summary["enrichment_duration"] = enrichment.get("enrichment_duration_seconds")
    for k in ("resource_usage", "estimated_cost_pence"):
        if enrichment.get(k) is not None:
            summary[k] = enrichment[k]


@bp.orchestration_trigger(context_name="context")
def treesight_orchestrator(context: df.DurableOrchestrationContext):  # type: ignore[return-type]
    """Orchestrator with per-AOI progressive delivery (#585).

    Single AOI: Ingestion → Acquisition → Fulfilment → Enrichment.
    Multi-AOI:  Ingestion → Per-AOI sub-orchestrators → Enrichment.
    """
    inp = cast("dict[str, Any]", context.get_input() or {})
    instance_id, ctx = context.instance_id, derive_project_context(inp.get("blob_name", ""))
    user_id, tier = inp.get("user_id", ""), inp.get("tier", "")
    output_container = inp.get("output_container", DEFAULT_OUTPUT_CONTAINER)
    started_at = context.current_utc_datetime.isoformat()
    try:
        ing = yield from _phase_ingestion(context, inp, instance_id, ctx)
        acq_s, ful_s = yield from _dispatch_acq_ful(context, inp, ctx, ing, instance_id)
        enrichment = yield from _phase_enrichment(
            context,
            inp,
            ctx,
            ing["all_coords"],
            ing["per_aoi_coords"],
            output_container,
        )
        summary = build_pipeline_summary(
            instance_id=instance_id,
            blob_name=inp.get("blob_name", ""),
            blob_url=inp.get("blob_url", ""),
            ingestion=ing["ingestion"],
            acquisition=acq_s,
            fulfilment=ful_s,
        )
        _apply_enrichment_to_summary(summary, enrichment)
        context.set_custom_status({"phase": "completed", "step": "done"})
        if user_id and tier != "demo" and inp.get("org_id"):
            yield from _safe_finalize_run(context, inp["org_id"], instance_id, "completed")
        yield from _safe_write_pipeline_stats(
            context, inp, ing, acq_s, ful_s, enrichment, instance_id, started_at
        )
        return summary
    except Exception:
        if user_id and tier != "demo" and inp.get("org_id"):
            yield from _safe_finalize_run(context, inp["org_id"], instance_id, "failed")
        raise
