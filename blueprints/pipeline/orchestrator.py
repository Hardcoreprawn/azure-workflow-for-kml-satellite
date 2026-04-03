"""Durable orchestrator: four-phase sequential pipeline with fan-out parallelism.

Uses claim-check pattern to keep orchestrator history entries below 48 KiB
regardless of AOI count.  AOI geometry is stored in blob storage after
ingestion; subsequent phases receive only lightweight ``{ref, key}`` refs.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from typing import Any, cast

import azure.durable_functions as df

from treesight.config import config_get_int
from treesight.constants import (
    BATCH_POLL_INTERVAL_SECONDS,
    DEFAULT_ACQUISITION_BATCH_SIZE,
    DEFAULT_DOWNLOAD_BATCH_SIZE,
    DEFAULT_INPUT_CONTAINER,
    DEFAULT_OUTPUT_CONTAINER,
    DEFAULT_POST_PROCESS_BATCH_SIZE,
)
from treesight.pipeline.orchestrator import build_pipeline_summary, derive_project_context

from . import bp
from ._helpers import (
    _acq_payload,
    _build_order_lookups,
    _collect_enrichment_coords,
    _download_payload,
    _poll_payload,
    _post_process_payload,
    _split_batch_routing,
)


@bp.orchestration_trigger(context_name="context")
def treesight_orchestrator(context: df.DurableOrchestrationContext):  # type: ignore[return-type]
    """Four-phase sequential orchestrator with fan-out parallelism.

    Phases: Ingestion, Acquisition, Fulfilment, Enrichment.

    Claim-check: AOIs are stored in blob storage after ingestion.
    All subsequent phases receive lightweight refs instead of full AOI dicts,
    keeping orchestrator history under the 48 KiB limit for 200+ AOIs.
    """
    inp = cast("dict[str, Any]", context.get_input() or {})
    instance_id: str = context.instance_id
    blob_name = inp.get("blob_name", "")
    ctx = derive_project_context(blob_name)

    # --- Phase 1: Ingestion ---
    context.set_custom_status({"phase": "ingestion", "step": "parsing_kml"})
    features = cast("Any", (yield context.call_activity("parse_kml", inp)))

    if isinstance(features, list):
        feature_list = cast("list[dict[str, Any]]", features)
        offloaded = False
    else:
        loaded = cast(
            "list[dict[str, Any]]",
            (yield context.call_activity("load_offloaded_features", features)),
        )
        feature_list = loaded
        offloaded = True

    # Fan-out: prepare AOIs
    context.set_custom_status(
        {"phase": "ingestion", "step": "preparing_aois", "features": len(feature_list)}
    )
    aoi_tasks = [
        context.call_activity("prepare_aoi", {"feature": f, "buffer_m": inp.get("buffer_m")})
        for f in feature_list
    ]
    aois = cast("list[dict[str, Any]]", (yield context.task_all(aoi_tasks)))

    # Claim-check: extract enrichment coords before offloading AOIs
    all_coords = _collect_enrichment_coords(aois)

    # Extract area_ha per AOI for batch routing (before claim-check offload)
    aoi_area_by_name: dict[str, float] = {
        a.get("feature_name", ""): a.get("area_ha", 0.0) for a in aois
    }

    # Claim-check: store full AOI dicts in blob storage, get lightweight refs
    context.set_custom_status({"phase": "ingestion", "step": "storing_claims", "aois": len(aois)})
    aoi_refs = cast(
        "list[dict[str, str]]",
        (
            yield context.call_activity(
                "store_aoi_claims",
                {"instance_id": instance_id, "aois": aois},
            )
        ),
    )

    # Fan-out: write metadata (activities retrieve AOI from claim check)
    meta_tasks = [
        context.call_activity(
            "write_metadata",
            {
                "aoi_ref": ref["ref"],
                "processing_id": instance_id,
                "timestamp": ctx["timestamp"],
                "tenant_id": inp.get("tenant_id", ""),
                "source_file": blob_name,
                "output_container": inp.get("output_container", DEFAULT_OUTPUT_CONTAINER),
                "input_container": inp.get("container_name", DEFAULT_INPUT_CONTAINER),
            },
        )
        for ref in aoi_refs
    ]
    metadata_results = cast(
        "list[dict[str, Any]]",
        (yield context.task_all(meta_tasks)),
    )

    ingestion: dict[str, Any] = {
        "feature_count": len(feature_list),
        "offloaded": offloaded,
        "aoi_refs": aoi_refs,
        "aoi_count": len(aoi_refs),
        "metadata_results": metadata_results,
        "metadata_count": len(metadata_results),
    }

    # --- Phase 2: Acquisition (batched) ---
    context.set_custom_status({"phase": "acquisition", "step": "searching", "aois": len(aoi_refs)})
    composite = bool(inp.get("composite_search", True))
    acq_batch_size = max(
        1, config_get_int(inp, "acquisition_batch_size", DEFAULT_ACQUISITION_BATCH_SIZE)
    )

    orders: list[dict[str, Any]] = []
    for i in range(0, len(aoi_refs), acq_batch_size):
        batch_refs = aoi_refs[i : i + acq_batch_size]
        activity = "acquire_composite" if composite else "acquire_imagery"
        acq_tasks = [
            context.call_activity(activity, _acq_payload(ref, inp, composite)) for ref in batch_refs
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

    # Poll orders
    context.set_custom_status({"phase": "acquisition", "step": "polling", "orders": len(orders)})
    poll_tasks = [
        context.call_activity("poll_order", _poll_payload(o, inp))
        for o in orders
        if o.get("order_id")
    ]
    poll_results = cast(
        "list[dict[str, Any]]",
        (yield context.task_all(poll_tasks)) if poll_tasks else [],
    )

    ready: list[dict[str, Any]] = [r for r in poll_results if r.get("state") == "ready"]
    failed: list[dict[str, Any]] = [r for r in poll_results if r.get("state") != "ready"]
    asset_urls, order_meta = _build_order_lookups(orders)

    # Build AOI ref lookup for fulfilment (key → ref)
    aoi_ref_lookup: dict[str, str] = {}
    for r in aoi_refs:
        if r["key"] in aoi_ref_lookup:
            raise ValueError(f"Duplicate AOI key: {r['key']}")
        aoi_ref_lookup[r["key"]] = r["ref"]

    acquisition: dict[str, Any] = {
        "imagery_outcomes": poll_results,
        "ready_count": len(ready),
        "failed_count": len(failed),
    }

    # --- Phase 3: Fulfilment ---
    context.set_custom_status({"phase": "fulfilment", "step": "downloading", "ready": len(ready)})
    output_container = inp.get("output_container", DEFAULT_OUTPUT_CONTAINER)
    batch_size = config_get_int(inp, "download_batch_size", DEFAULT_DOWNLOAD_BATCH_SIZE)

    # Split ready imagery: oversized AOIs → Azure Batch, normal → serverless
    serverless_ready, batch_ready = _split_batch_routing(ready, aoi_area_by_name)

    # Route oversized AOIs to Azure Batch Spot VMs
    batch_tracking: list[dict[str, Any]] = []
    if batch_ready:
        context.set_custom_status(
            {"phase": "fulfilment", "step": "batch_submit", "count": len(batch_ready)}
        )
        submit_tasks = [
            context.call_activity(
                "submit_batch_fulfilment",
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
        while pending:
            context.set_custom_status(
                {"phase": "fulfilment", "step": "batch_polling", "pending": len(pending)}
            )
            poll_batch_tasks = [
                context.call_activity(
                    "poll_batch_fulfilment",
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

    # Download serverless-tier imagery in batches
    download_results: list[dict[str, Any]] = []
    for i in range(0, len(serverless_ready), batch_size):
        batch = serverless_ready[i : i + batch_size]
        dl_tasks = [
            context.call_activity(
                "download_imagery",
                _download_payload(
                    outcome,
                    inp,
                    ctx,
                    asset_urls,
                    order_meta,
                    aoi_ref_lookup,
                    output_container,
                ),
            )
            for outcome in batch
        ]
        batch_results = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(dl_tasks)),
        )
        download_results.extend(batch_results)

    successful_downloads: list[dict[str, Any]] = [
        d for d in download_results if d.get("state") != "failed"
    ]
    failed_downloads: list[dict[str, Any]] = [
        d for d in download_results if d.get("state") == "failed"
    ]

    # Post-process in batches
    context.set_custom_status(
        {"phase": "fulfilment", "step": "post_processing", "downloads": len(download_results)}
    )
    pp_batch_size = config_get_int(inp, "post_process_batch_size", DEFAULT_POST_PROCESS_BATCH_SIZE)
    pp_results: list[dict[str, Any]] = []

    for i in range(0, len(successful_downloads), pp_batch_size):
        batch = successful_downloads[i : i + pp_batch_size]
        pp_tasks = [
            context.call_activity(
                "post_process_imagery",
                _post_process_payload(dl, inp, ctx, aoi_ref_lookup, output_container),
            )
            for dl in batch
        ]
        batch_pp = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(pp_tasks)),
        )
        pp_results.extend(batch_pp)

    # Merge batch results into download tracking
    batch_succeeded = [t for t in batch_tracking if t.get("state") == "completed"]
    batch_failed_items = [t for t in batch_tracking if t.get("state") == "failed"]

    fulfilment: dict[str, Any] = {
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

    # --- Phase 4: Enrichment (weather, mosaics, NDVI, manifest) ---
    context.set_custom_status({"phase": "enrichment", "step": "fetching_data"})

    enrichment: dict[str, Any] = {}
    if all_coords:
        enrichment = cast(
            "dict[str, Any]",
            (
                yield context.call_activity(
                    "run_enrichment",
                    {
                        "coords": all_coords,
                        "project_name": ctx["project_name"],
                        "timestamp": ctx["timestamp"],
                        "output_container": output_container,
                        "eudr_mode": inp.get("eudr_mode", False),
                        "date_start": inp.get("date_start"),
                        "date_end": inp.get("date_end"),
                        "cadence": inp.get("cadence", "maximum"),
                        "max_history_years": inp.get("max_history_years"),
                    },
                )
            ),
        )

    # --- Summary ---
    summary = build_pipeline_summary(
        instance_id=instance_id,
        blob_name=blob_name,
        blob_url=inp.get("blob_url", ""),
        ingestion=ingestion,
        acquisition=acquisition,
        fulfilment=fulfilment,
    )

    if enrichment.get("manifest_path"):
        summary["enrichment_manifest"] = enrichment["manifest_path"]
        summary["enrichment_duration"] = enrichment.get("enrichment_duration_seconds")

    return summary
