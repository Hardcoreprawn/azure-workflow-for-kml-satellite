"""Durable orchestrator: four-phase sequential pipeline with fan-out parallelism.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from typing import Any, cast

import azure.durable_functions as df

from treesight.config import config_get_int
from treesight.constants import (
    DEFAULT_DOWNLOAD_BATCH_SIZE,
    DEFAULT_INPUT_CONTAINER,
    DEFAULT_OUTPUT_CONTAINER,
    DEFAULT_POST_PROCESS_BATCH_SIZE,
)
from treesight.pipeline.orchestrator import build_pipeline_summary, derive_project_context

from . import bp
from ._helpers import _build_order_lookups, _collect_enrichment_coords


@bp.orchestration_trigger(context_name="context")
def treesight_orchestrator(context: df.DurableOrchestrationContext):  # type: ignore[return-type]
    """Four-phase sequential orchestrator with fan-out parallelism.

    Phases: Ingestion, Acquisition, Fulfilment, Enrichment.
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

    # Fan-out: write metadata
    meta_tasks = [
        context.call_activity(
            "write_metadata",
            {
                "aoi": aoi,
                "processing_id": instance_id,
                "timestamp": ctx["timestamp"],
                "tenant_id": inp.get("tenant_id", ""),
                "source_file": blob_name,
                "output_container": inp.get("output_container", DEFAULT_OUTPUT_CONTAINER),
                "input_container": inp.get("container_name", DEFAULT_INPUT_CONTAINER),
            },
        )
        for aoi in aois
    ]
    metadata_results = cast(
        "list[dict[str, Any]]",
        (yield context.task_all(meta_tasks)),
    )

    ingestion: dict[str, Any] = {
        "feature_count": len(feature_list),
        "offloaded": offloaded,
        "aois": aois,
        "aoi_count": len(aois),
        "metadata_results": metadata_results,
        "metadata_count": len(metadata_results),
    }

    # --- Phase 2: Acquisition ---
    context.set_custom_status({"phase": "acquisition", "step": "searching", "aois": len(aois)})
    composite = bool(inp.get("composite_search", True))

    if composite:
        acq_tasks = [
            context.call_activity(
                "acquire_composite",
                {
                    "aoi": aoi,
                    "provider_name": inp.get("provider_name", "planetary_computer"),
                    "provider_config": inp.get("provider_config"),
                    "imagery_filters": inp.get("imagery_filters"),
                    "temporal_count": config_get_int(inp, "temporal_count", 6),
                },
            )
            for aoi in aois
        ]
        all_order_lists = cast(
            "list[list[dict[str, Any]]]",
            (yield context.task_all(acq_tasks)),
        )
        orders: list[dict[str, Any]] = []
        for order_list in all_order_lists:
            orders.extend(order_list)
    else:
        acq_tasks = [
            context.call_activity(
                "acquire_imagery",
                {
                    "aoi": aoi,
                    "provider_name": inp.get("provider_name", "planetary_computer"),
                    "provider_config": inp.get("provider_config"),
                    "imagery_filters": inp.get("imagery_filters"),
                },
            )
            for aoi in aois
        ]
        orders = cast("list[dict[str, Any]]", (yield context.task_all(acq_tasks)))

    # Poll orders
    context.set_custom_status({"phase": "acquisition", "step": "polling", "orders": len(orders)})
    poll_tasks = [
        context.call_activity(
            "poll_order",
            {
                "order_id": o.get("order_id", ""),
                "scene_id": o.get("scene_id", ""),
                "aoi_feature_name": o.get("aoi_feature_name", ""),
                "provider_name": inp.get("provider_name", "planetary_computer"),
                "provider_config": inp.get("provider_config"),
                "overrides": inp,
            },
        )
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

    acquisition: dict[str, Any] = {
        "imagery_outcomes": poll_results,
        "ready_count": len(ready),
        "failed_count": len(failed),
    }

    # --- Phase 3: Fulfilment ---
    context.set_custom_status({"phase": "fulfilment", "step": "downloading", "ready": len(ready)})
    output_container = inp.get("output_container", DEFAULT_OUTPUT_CONTAINER)
    batch_size = config_get_int(inp, "download_batch_size", DEFAULT_DOWNLOAD_BATCH_SIZE)
    aoi_lookup: dict[str, dict[str, Any]] = (
        {a.get("feature_name", ""): a for a in aois} if aois else {}
    )

    # Download in batches
    download_results: list[dict[str, Any]] = []
    for i in range(0, len(ready), batch_size):
        batch = ready[i : i + batch_size]
        dl_tasks = [
            context.call_activity(
                "download_imagery",
                {
                    "outcome": outcome,
                    "asset_url": asset_urls.get(outcome.get("order_id", ""), ""),
                    "aoi_bbox": aoi_lookup.get(
                        outcome.get("aoi_feature_name", ""),
                        {},
                    ).get("buffered_bbox"),
                    "role": order_meta.get(
                        outcome.get("order_id", ""),
                        {},
                    ).get("role", ""),
                    "collection": order_meta.get(
                        outcome.get("order_id", ""),
                        {},
                    ).get("collection", ""),
                    "provider_name": inp.get("provider_name", "planetary_computer"),
                    "provider_config": inp.get("provider_config"),
                    "project_name": ctx["project_name"],
                    "timestamp": ctx["timestamp"],
                    "output_container": output_container,
                },
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
                {
                    "download_result": dl,
                    "aoi": aoi_lookup.get(dl.get("aoi_feature_name", ""), {}),
                    "project_name": ctx["project_name"],
                    "timestamp": ctx["timestamp"],
                    "target_crs": inp.get("target_crs", "EPSG:4326"),
                    "enable_clipping": inp.get("enable_clipping", True),
                    "enable_reprojection": inp.get("enable_reprojection", True),
                    "output_container": output_container,
                    "square_frame": inp.get("square_frame", True),
                    "frame_padding_pct": inp.get("frame_padding_pct", 10.0),
                },
            )
            for dl in batch
        ]
        batch_pp = cast(
            "list[dict[str, Any]]",
            (yield context.task_all(pp_tasks)),
        )
        pp_results.extend(batch_pp)

    fulfilment: dict[str, Any] = {
        "download_results": download_results,
        "downloads_completed": len(download_results),
        "downloads_succeeded": len(successful_downloads),
        "downloads_failed": len(failed_downloads),
        "post_process_results": pp_results,
        "pp_completed": len(pp_results),
        "pp_clipped": sum(1 for p in pp_results if p.get("clipped")),
        "pp_reprojected": sum(1 for p in pp_results if p.get("reprojected")),
        "pp_failed": sum(1 for p in pp_results if p.get("state") == "failed"),
    }

    # --- Phase 4: Enrichment (weather, mosaics, NDVI, manifest) ---
    context.set_custom_status({"phase": "enrichment", "step": "fetching_data"})

    all_coords = _collect_enrichment_coords(aois)

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
