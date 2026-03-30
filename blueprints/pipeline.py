"""Durable Functions pipeline: orchestrator, activities, blob trigger (§3, §4.2).

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
The Azure Functions v2 runtime inspects binding parameter annotations at
import time.  PEP 563 (stringified annotations) causes the runtime to fail
with ``FunctionLoadError: binding payload has invalid non-type annotation``.
For the same reason, activity trigger ``payload`` parameters use bare ``dict``
instead of ``dict[str, Any]`` — the runtime cannot resolve parameterised
generics on binding arguments.
"""

import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight
from treesight.config import config_get_int
from treesight.constants import (
    DEFAULT_DOWNLOAD_BATCH_SIZE,
    DEFAULT_INPUT_CONTAINER,
    DEFAULT_OUTPUT_CONTAINER,
    DEFAULT_POST_PROCESS_BATCH_SIZE,
    MAX_KML_FILE_SIZE_BYTES,
    PIPELINE_PAYLOADS_CONTAINER,
)
from treesight.errors import ContractError
from treesight.models.blob_event import BlobEvent
from treesight.pipeline.orchestrator import build_pipeline_summary, derive_project_context
from treesight.security.quota import consume_quota
from treesight.security.rate_limit import demo_limiter, get_client_ip, pipeline_limiter

# At runtime resolves to bare ``dict`` (Azure Functions binding requirement);
# Pylance sees ``dict[str, Any]`` for full type-checking.
if TYPE_CHECKING:
    _Payload = dict[str, Any]
else:
    _Payload = dict

bp = df.Blueprint()

# Maximum body size for analysis save endpoint (128 KiB)
_MAX_ANALYSIS_BODY_BYTES = 131_072
_SIGNED_IN_SUBMISSIONS_PREFIX = "analysis-submissions"
_DEFAULT_HISTORY_LIMIT = 8
_MAX_HISTORY_LIMIT = 20


# ---------------------------------------------------------------------------
# Blob trigger → start orchestration (§4.2)
# ---------------------------------------------------------------------------


@bp.route(
    route="orchestrator/{instance_id}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def orchestrator_status(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/orchestrator/{instance_id} — direct JSON diagnostics (§4.3)."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return _error_response(429, "Rate limit exceeded — try again later")

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return func.HttpResponse(
            json.dumps({"error": "instance_id required"}),
            status_code=400,
            mimetype="application/json",
        )

    status = await client.get_status(instance_id)
    if not status:
        return func.HttpResponse(
            json.dumps({"error": "not found"}), status_code=404, mimetype="application/json"
        )

    result = _durable_status_payload(status)
    return func.HttpResponse(
        json.dumps(result, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="analysis/history",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def analysis_history(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/analysis/history — recent signed-in runs for the current user."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return _error_response(429, "Rate limit exceeded — try again later")

    return await _build_analysis_history_response(req, client, user_id)


async def _build_analysis_history_response(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
    user_id: str,
) -> func.HttpResponse:
    """Build the signed-in history response for a single authenticated user."""

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    limit = _parse_history_limit(req.params.get("limit", ""))
    blob_names = []
    prefix = _analysis_submission_prefix(user_id)

    try:
        blob_names = storage.list_blobs(PIPELINE_PAYLOADS_CONTAINER, prefix=prefix)
    except Exception:
        logging.info("No analysis history found for user=%s prefix=%s", user_id, prefix)

    records: list[dict[str, Any]] = []
    for blob_name in blob_names:
        try:
            record = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, blob_name)
        except Exception:
            logging.warning("Skipping unreadable analysis history blob=%s", blob_name)
            continue
        if record.get("user_id") != user_id:
            continue
        records.append(record)

    records.sort(key=lambda record: str(record.get("submitted_at", "")), reverse=True)

    runs = [await _build_analysis_history_entry(record, client) for record in records[:limit]]
    active_run = next((run for run in runs if _history_run_is_active(run)), None)

    return func.HttpResponse(
        json.dumps({"runs": runs, "activeRun": active_run}, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.event_grid_trigger(arg_name="event")
@bp.durable_client_input(client_name="client")
async def blob_trigger(
    event: func.EventGridEvent,
    client: df.DurableOrchestrationClient,
) -> None:
    """Event Grid BlobCreated → validate → start orchestration (§4.2)."""
    data = event.get_json()
    blob_url = data.get("url", "")
    container_name = _extract_container(blob_url)
    blob_name = _extract_blob_name(blob_url)

    # Validate (§4.2 step 2)
    _validate_blob_event(blob_name, container_name, data)

    blob_event = BlobEvent(
        blob_url=blob_url,
        container_name=container_name,
        blob_name=blob_name,
        content_length=data.get("contentLength", 0),
        content_type=data.get("contentType", ""),
        event_time=event.event_time.isoformat() if event.event_time else "",
        correlation_id=event.id,
    )

    orchestrator_input = blob_event.model_dump()

    # Merge optional pipeline configuration from event data (local dev / testing)
    pipeline_keys = ("provider_config", "provider_name", "imagery_filters", "target_crs")
    for key in pipeline_keys:
        if key in data:
            orchestrator_input[key] = data[key]

    instance_id = blob_event.correlation_id
    await client.start_new(
        "treesight_orchestrator",
        instance_id=instance_id,
        client_input=orchestrator_input,
    )
    logging.info("Started orchestration instance=%s blob=%s", instance_id, blob_name)


# ---------------------------------------------------------------------------
# Orchestrator (§3 three-phase pipeline)
# ---------------------------------------------------------------------------


@bp.orchestration_trigger(context_name="context")
def treesight_orchestrator(context: df.DurableOrchestrationContext):  # type: ignore[return-type]
    """Three-phase sequential orchestrator with fan-out parallelism."""
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
        # Payload was offloaded (§7.5) — load from blob
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
        # Composite mode: NAIP detail + S2 temporal for each AOI
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
        # Flatten: each activity returns a list of orders
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

    # Build lookups from acquisition results (signed download URLs + metadata)
    asset_urls: dict[str, str] = {o.get("order_id", ""): o.get("asset_url", "") for o in orders}
    order_meta: dict[str, dict[str, str]] = {
        o.get("order_id", ""): {
            "role": o.get("role", ""),
            "collection": o.get("collection", ""),
        }
        for o in orders
    }

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

    # Build aoi_lookup earlier in case it's needed (already built before pp)
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

    # Collect all AOI coords for enrichment (union of all polygons)
    all_coords: list[list[float]] = []
    for aoi in aois:
        ext = aoi.get("exterior_coords", [])
        if ext:
            all_coords.extend(ext)

    # Fall back to bounding box corners if no exterior coords
    if not all_coords:
        for aoi in aois:
            bb = aoi.get("bbox") or aoi.get("buffered_bbox")
            if bb and len(bb) == 4:
                min_lat, min_lon, max_lat, max_lon = bb
                all_coords = [
                    [min_lat, min_lon],
                    [min_lat, max_lon],
                    [max_lat, max_lon],
                    [max_lat, min_lon],
                    [min_lat, min_lon],
                ]
                break

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

    # Attach enrichment manifest path so frontend knows where to fetch
    if enrichment.get("manifest_path"):
        summary["enrichment_manifest"] = enrichment["manifest_path"]
        summary["enrichment_duration"] = enrichment.get("enrichment_duration_seconds")

    return summary


# ---------------------------------------------------------------------------
# Activities
# NOTE: payload params are typed as bare ``dict`` — see module docstring.
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def parse_kml(payload: _Payload) -> list[dict[str, Any]] | dict[str, Any]:
    from treesight.models.blob_event import BlobEvent
    from treesight.pipeline.ingestion import parse_kml_from_blob
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    blob_event = BlobEvent.model_validate(payload)
    storage = BlobStorageClient()
    features = parse_kml_from_blob(blob_event, storage)
    feature_dicts = [f.model_dump() for f in features]

    offloader = PayloadOffloader(storage)
    if offloader.should_offload(feature_dicts):
        return offloader.offload(blob_event.correlation_id, feature_dicts)

    return feature_dicts


@bp.activity_trigger(input_name="payload")
def load_offloaded_features(payload: _Payload) -> list[dict[str, Any]]:
    """Load features from offloaded blob storage (§7.5)."""
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    storage = BlobStorageClient()
    offloader = PayloadOffloader(storage)
    return offloader.load_all(payload["ref"])


@bp.activity_trigger(input_name="payload")
def prepare_aoi(payload: _Payload) -> dict[str, Any]:
    from treesight.geo import prepare_aoi as _prepare
    from treesight.models.feature import Feature

    feature = Feature.model_validate(payload["feature"])
    aoi = _prepare(feature, buffer_m=payload.get("buffer_m"))
    return aoi.model_dump()


@bp.activity_trigger(input_name="payload")
def write_metadata(payload: _Payload) -> dict[str, Any]:
    from treesight.models.aoi import AOI
    from treesight.pipeline.ingestion import write_metadata as _write
    from treesight.storage.client import BlobStorageClient

    aoi = AOI.model_validate(payload["aoi"])
    storage = BlobStorageClient()

    # Download KML for archival (§6.2)
    kml_bytes: bytes | None = None
    input_container = payload.get("input_container", "")
    source_file = payload["source_file"]
    if input_container and source_file:
        with contextlib.suppress(Exception):
            kml_bytes = storage.download_bytes(input_container, source_file)

    return _write(
        aoi=aoi,
        processing_id=payload["processing_id"],
        timestamp=payload["timestamp"],
        tenant_id=payload.get("tenant_id", ""),
        source_file=source_file,
        output_container=payload["output_container"],
        storage=storage,
        kml_bytes=kml_bytes,
    )


@bp.activity_trigger(input_name="payload")
def acquire_imagery(payload: _Payload) -> dict[str, Any]:
    from treesight.models.aoi import AOI
    from treesight.models.imagery import ImageryFilters
    from treesight.pipeline.acquisition import acquire_imagery as _acquire
    from treesight.providers.registry import get_provider

    aoi = AOI.model_validate(payload["aoi"])
    provider = get_provider(
        payload.get("provider_name", "planetary_computer"),
        payload.get("provider_config"),
    )
    filters = (
        ImageryFilters.model_validate(payload["imagery_filters"])
        if payload.get("imagery_filters")
        else ImageryFilters()
    )
    return _acquire(aoi, provider, filters)


@bp.activity_trigger(input_name="payload")
def acquire_composite(payload: _Payload) -> list[dict[str, Any]]:
    from treesight.models.aoi import AOI
    from treesight.models.imagery import ImageryFilters
    from treesight.pipeline.acquisition import acquire_composite as _composite
    from treesight.providers.registry import get_provider

    aoi = AOI.model_validate(payload["aoi"])
    provider = get_provider(
        payload.get("provider_name", "planetary_computer"),
        payload.get("provider_config"),
    )
    filters = (
        ImageryFilters.model_validate(payload["imagery_filters"])
        if payload.get("imagery_filters")
        else ImageryFilters()
    )
    return _composite(
        aoi,
        provider,
        filters,
        temporal_count=int(payload.get("temporal_count", 6)),
    )


@bp.activity_trigger(input_name="payload")
def poll_order(payload: _Payload) -> dict[str, Any]:
    from treesight.pipeline.acquisition import poll_order as _poll
    from treesight.providers.registry import get_provider

    provider = get_provider(
        payload.get("provider_name", "planetary_computer"),
        payload.get("provider_config"),
    )
    outcome = _poll(
        payload["order_id"],
        provider,
        poll_interval=config_get_int(payload.get("overrides", {}), "poll_interval_seconds", 30),
        poll_timeout=config_get_int(payload.get("overrides", {}), "poll_timeout_seconds", 1800),
        max_retries=config_get_int(payload.get("overrides", {}), "max_retries", 3),
        retry_base=config_get_int(payload.get("overrides", {}), "retry_base_seconds", 5),
    )
    outcome.scene_id = payload.get("scene_id", "")
    outcome.aoi_feature_name = payload.get("aoi_feature_name", "")
    return outcome.model_dump()


@bp.activity_trigger(input_name="payload")
def download_imagery(payload: _Payload) -> dict[str, Any]:
    from treesight.pipeline.fulfilment import download_imagery as _download
    from treesight.providers.registry import get_provider
    from treesight.storage.client import BlobStorageClient

    provider = get_provider(
        payload.get("provider_name", "planetary_computer"),
        payload.get("provider_config"),
    )
    storage = BlobStorageClient()
    return _download(
        outcome=payload["outcome"],
        provider=provider,
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        output_container=payload["output_container"],
        storage=storage,
        asset_url=payload.get("asset_url", ""),
        aoi_bbox=payload.get("aoi_bbox"),
        role=payload.get("role", ""),
        collection=payload.get("collection", ""),
    )


@bp.activity_trigger(input_name="payload")
def post_process_imagery(payload: _Payload) -> dict[str, Any]:
    from treesight.models.aoi import AOI
    from treesight.pipeline.fulfilment import post_process_imagery as _post_process
    from treesight.storage.client import BlobStorageClient

    aoi = AOI.model_validate(payload.get("aoi", {}))
    storage = BlobStorageClient()
    return _post_process(
        download_result=payload["download_result"],
        aoi=aoi,
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        target_crs=payload.get("target_crs", "EPSG:4326"),
        enable_clipping=payload.get("enable_clipping", True),
        enable_reprojection=payload.get("enable_reprojection", True),
        output_container=payload["output_container"],
        storage=storage,
        square_frame=payload.get("square_frame", True),
        frame_padding_pct=payload.get("frame_padding_pct", 10.0),
    )


@bp.activity_trigger(input_name="payload")
def run_enrichment(payload: _Payload) -> dict[str, Any]:
    """Phase 4 activity: fetch weather, register mosaics, sample NDVI, store manifest."""
    from treesight.pipeline.enrichment import run_enrichment as _enrich
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    return _enrich(
        coords=payload["coords"],
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        output_container=payload.get("output_container", DEFAULT_OUTPUT_CONTAINER),
        storage=storage,
        eudr_mode=payload.get("eudr_mode", False),
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
    )


# ---------------------------------------------------------------------------
# Enrichment manifest serving endpoints
# ---------------------------------------------------------------------------


@bp.route(
    route="timelapse-data/{instance_id}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def timelapse_data(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/timelapse-data/{instance_id} — serve cached enrichment manifest.

    Returns the timelapse_payload.json produced by the enrichment phase,
    containing weather, NDVI, mosaic search IDs, and frame metadata.
    The frontend uses this instead of fetching from external APIs.
    """
    try:
        check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return _error_response(400, "instance_id required")

    # Look up the orchestrator output to find the manifest path
    status = await client.get_status(instance_id)
    if not status or not status.output:
        return _error_response(404, "Pipeline not found or not complete")

    output = _reshape_output(status.output) if status.output else {}
    manifest_path = output.get("enrichment_manifest") or output.get("enrichmentManifest")
    if not manifest_path:
        return _error_response(404, "No enrichment data for this pipeline run")

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, manifest_path)
    except Exception:
        return _error_response(404, "Enrichment manifest not found in storage")

    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="timelapse-analysis-save",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def timelapse_analysis_save(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/timelapse-analysis-save — persist AI analysis results.

    Stores the LLM analysis alongside the enrichment manifest so it
    can be retrieved without re-running the LLM.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    raw_body = req.get_body()
    if len(raw_body) > _MAX_ANALYSIS_BODY_BYTES:
        return _error_response(
            413, f"Request body too large (max {_MAX_ANALYSIS_BODY_BYTES} bytes)"
        )

    try:
        body = req.get_json()
    except ValueError:
        return _error_response(400, "Invalid JSON body")

    instance_id = body.get("instance_id", "")
    analysis = body.get("analysis", {})

    if not instance_id or not analysis:
        return _error_response(400, "instance_id and analysis are required")

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()

    # Store analysis keyed by instance ID
    analysis_path = f"analysis/{instance_id}/timelapse_analysis.json"
    analysis["saved_at"] = datetime.now(UTC).isoformat()
    analysis["instance_id"] = instance_id
    storage.upload_json(DEFAULT_OUTPUT_CONTAINER, analysis_path, analysis)

    return func.HttpResponse(
        json.dumps({"saved": True, "path": analysis_path}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="timelapse-analysis-load/{instance_id}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def timelapse_analysis_load(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/timelapse-analysis-load/{instance_id} — retrieve saved analysis."""
    try:
        check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return _error_response(400, "instance_id required")

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    analysis_path = f"analysis/{instance_id}/timelapse_analysis.json"
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, analysis_path)
    except Exception:
        return _error_response(404, "No saved analysis for this pipeline run")

    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# Demo processing endpoint — anonymous, rate-limited, demo-tier constraints
# ---------------------------------------------------------------------------


@bp.route(route="demo-process", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def demo_process(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """POST /api/demo-process — anonymous demo submission with tier limits.

    No authentication required.  Rate-limited by IP.  Enforces demo tier
    constraints: 1 AOI, seasonal cadence, 2-year history window.
    """
    return await _submit_demo_request(req, client)


@bp.route(route="analysis/submit", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def analysis_submit(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """POST /api/analysis/submit — production-named analysis submission route.

    Accepts ``{"kml_content": "..."}`` and returns ``{"instance_id": "..."}``
    which can be polled via ``GET /api/orchestrator/{instance_id}``.
    """
    return await _submit_analysis_request(req, client, blob_prefix="analysis")


async def _submit_demo_request(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """Validate, persist, and enqueue an anonymous demo KML submission."""
    import hashlib

    client_ip = get_client_ip(req)

    if not demo_limiter.is_allowed(client_ip):
        return _error_response(429, "Demo rate limit exceeded — try again later")

    try:
        body = req.get_json()
    except ValueError:
        return _error_response(400, "Invalid JSON body")

    kml_content = body.get("kml_content", "") if isinstance(body, dict) else ""
    if not isinstance(kml_content, str) or not kml_content.strip():
        return _error_response(400, "kml_content is required")

    kml_bytes = kml_content.encode("utf-8")
    if len(kml_bytes) > MAX_KML_FILE_SIZE_BYTES:
        return _error_response(400, f"KML exceeds {MAX_KML_FILE_SIZE_BYTES} bytes")

    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:12]
    demo_user_id = f"demo:{ip_hash}"
    submission_id = str(uuid.uuid4())
    kml_blob_name = f"demo/{submission_id}.kml"

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    storage.upload_bytes(
        DEFAULT_INPUT_CONTAINER,
        kml_blob_name,
        kml_bytes,
        content_type="application/vnd.google-earth.kml+xml",
    )

    orchestrator_input = {
        "blob_url": f"https://devstoreaccount1.blob.core.windows.net/{DEFAULT_INPUT_CONTAINER}/{kml_blob_name}",
        "container_name": DEFAULT_INPUT_CONTAINER,
        "blob_name": kml_blob_name,
        "content_length": len(kml_bytes),
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": datetime.now(UTC).isoformat(),
        "correlation_id": submission_id,
        "composite_search": True,
        "provider_name": "planetary_computer",
        "cadence": "seasonal",
        "max_history_years": 2,
        "user_id": demo_user_id,
        "tier": "demo",
    }

    await client.start_new(
        "treesight_orchestrator",
        instance_id=submission_id,
        client_input=orchestrator_input,
    )

    logging.info(
        "Demo process started instance=%s user=%s",
        submission_id,
        demo_user_id,
    )

    return func.HttpResponse(
        json.dumps({"instance_id": submission_id, "submission_prefix": "demo"}),
        status_code=202,
        mimetype="application/json",
        headers=cors_headers(req),
    )


async def _submit_analysis_request(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
    *,
    blob_prefix: str,
) -> func.HttpResponse:
    """Validate, persist, and enqueue a KML analysis submission."""
    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    try:
        consume_quota(user_id)
    except ValueError as exc:
        return _error_response(403, str(exc))

    try:
        body = req.get_json()
    except ValueError:
        return _error_response(400, "Invalid JSON body")

    submission_context = _extract_submission_context(body)

    kml_content = body.get("kml_content", "") if isinstance(body, dict) else ""
    if not isinstance(kml_content, str) or not kml_content.strip():
        return _error_response(400, "kml_content is required")

    kml_bytes = kml_content.encode("utf-8")
    if len(kml_bytes) > MAX_KML_FILE_SIZE_BYTES:
        return _error_response(400, f"KML exceeds {MAX_KML_FILE_SIZE_BYTES} bytes")

    submission_id = str(uuid.uuid4())
    safe_prefix = blob_prefix.strip("/") or "analysis"
    kml_blob_name = f"{safe_prefix}/{submission_id}.kml"

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    storage.upload_bytes(
        DEFAULT_INPUT_CONTAINER,
        kml_blob_name,
        kml_bytes,
        content_type="application/vnd.google-earth.kml+xml",
    )

    orchestrator_input = {
        "blob_url": f"https://devstoreaccount1.blob.core.windows.net/{DEFAULT_INPUT_CONTAINER}/{kml_blob_name}",
        "container_name": DEFAULT_INPUT_CONTAINER,
        "blob_name": kml_blob_name,
        "content_length": len(kml_bytes),
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": datetime.now(UTC).isoformat(),
        "correlation_id": submission_id,
        "composite_search": True,
        "provider_name": "planetary_computer",
    }

    await client.start_new(
        "treesight_orchestrator",
        instance_id=submission_id,
        client_input=orchestrator_input,
    )

    if safe_prefix == "analysis":
        record = {
            "submission_id": submission_id,
            "instance_id": submission_id,
            "user_id": user_id,
            "submitted_at": orchestrator_input["event_time"],
            "kml_blob_name": kml_blob_name,
            "kml_size_bytes": len(kml_bytes),
            "submission_prefix": safe_prefix,
            "provider_name": submission_context.get(
                "provider_name", orchestrator_input["provider_name"]
            ),
            "status": "submitted",
        }
        record.update(submission_context)
        try:
            storage.upload_json(
                PIPELINE_PAYLOADS_CONTAINER,
                _analysis_submission_blob_name(user_id, submission_id),
                record,
            )
        except Exception:
            logging.warning(
                "Unable to persist analysis history record instance=%s user=%s",
                submission_id,
                user_id,
                exc_info=True,
            )

    logging.info("Analysis process started instance=%s prefix=%s", submission_id, safe_prefix)

    return func.HttpResponse(
        json.dumps({"instance_id": submission_id, "submission_prefix": safe_prefix}),
        status_code=202,
        mimetype="application/json",
    )


def _error_response(status: int, message: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_blob_event(blob_name: str, container_name: str, data: dict[str, Any]) -> None:
    if not blob_name:
        raise ContractError("Blob name is empty", code="EMPTY_BLOB_NAME")
    if not blob_name.lower().endswith(".kml"):
        raise ContractError("Not a .kml file", code="INVALID_FILE_TYPE")
    if not container_name:
        raise ContractError("Container name is empty", code="EMPTY_CONTAINER_NAME")
    if not container_name.endswith("-input"):
        raise ContractError("Container must end with -input", code="INVALID_CONTAINER")
    content_length = data.get("contentLength", 0)
    if content_length < 0:
        raise ContractError("Negative content length", code="INVALID_CONTENT_LENGTH")
    if content_length == 0:
        raise ContractError("Empty blob", code="EMPTY_BLOB")
    if content_length > MAX_KML_FILE_SIZE_BYTES:
        raise ContractError(f"File exceeds {MAX_KML_FILE_SIZE_BYTES} bytes", code="FILE_TOO_LARGE")


def _extract_container(blob_url: str) -> str:
    parts = blob_url.split("/")
    for i, p in enumerate(parts):
        if (p.endswith(".blob.core.windows.net") or p == "devstoreaccount1") and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _extract_blob_name(blob_url: str) -> str:
    parts = blob_url.split("/")
    for i, p in enumerate(parts):
        if (p.endswith(".blob.core.windows.net") or p == "devstoreaccount1") and i + 2 < len(parts):
            return "/".join(parts[i + 2 :])
    return ""


def _durable_status_payload(status: Any) -> dict[str, Any]:
    return {
        "instanceId": status.instance_id,
        "name": status.name,
        "runtimeStatus": status.runtime_status.value if status.runtime_status else None,
        "createdTime": str(status.created_time),
        "lastUpdatedTime": str(status.last_updated_time),
        "customStatus": status.custom_status,
        "output": _reshape_output(status.output) if status.output else None,
    }


def _analysis_submission_prefix(user_id: str) -> str:
    return f"{_SIGNED_IN_SUBMISSIONS_PREFIX}/{quote(user_id, safe='')}/"


def _analysis_submission_blob_name(user_id: str, submission_id: str) -> str:
    return f"{_analysis_submission_prefix(user_id)}{submission_id}.json"


def _extract_submission_context(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}

    raw_context = body.get("submission_context")
    if not isinstance(raw_context, dict):
        return {}

    context: dict[str, Any] = {}
    int_fields = ("feature_count", "aoi_count")
    float_fields = ("max_spread_km", "total_area_ha", "largest_area_ha")
    text_fields = ("processing_mode", "provider_name", "workspace_role", "workspace_preference")

    for field in int_fields:
        value = raw_context.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            context[field] = int(value)

    for field in float_fields:
        value = raw_context.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            context[field] = round(float(value), 2)

    for field in text_fields:
        value = raw_context.get(field)
        if isinstance(value, str) and value.strip():
            context[field] = value.strip()[:80]

    return context


def _parse_history_limit(raw_limit: str) -> int:
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return _DEFAULT_HISTORY_LIMIT
    return max(1, min(limit, _MAX_HISTORY_LIMIT))


async def _build_analysis_history_entry(
    record: dict[str, Any],
    client: df.DurableOrchestrationClient,
) -> dict[str, Any]:
    instance_id = str(record.get("instance_id") or record.get("submission_id") or "")
    status_payload: dict[str, Any] | None = None
    if instance_id:
        with contextlib.suppress(Exception):
            status = await client.get_status(instance_id)
            if status:
                status_payload = _durable_status_payload(status)

    runtime_status = record.get("status", "submitted")
    if status_payload and status_payload.get("runtimeStatus"):
        runtime_status = status_payload["runtimeStatus"]

    output = status_payload.get("output") if status_payload else None
    feature_count = output.get("featureCount") if output else record.get("feature_count")
    aoi_count = output.get("aoiCount") if output else record.get("aoi_count")
    artifacts = output.get("artifacts") if output else None

    return {
        "submissionId": record.get("submission_id", instance_id),
        "instanceId": instance_id,
        "submittedAt": record.get("submitted_at", ""),
        "submissionPrefix": record.get("submission_prefix", "analysis"),
        "providerName": record.get("provider_name", "planetary_computer"),
        "featureCount": feature_count,
        "aoiCount": aoi_count,
        "processingMode": record.get("processing_mode"),
        "maxSpreadKm": record.get("max_spread_km"),
        "totalAreaHa": record.get("total_area_ha"),
        "largestAreaHa": record.get("largest_area_ha"),
        "workspaceRole": record.get("workspace_role"),
        "workspacePreference": record.get("workspace_preference"),
        "runtimeStatus": runtime_status,
        "createdTime": status_payload.get("createdTime")
        if status_payload
        else record.get("submitted_at", ""),
        "lastUpdatedTime": status_payload.get("lastUpdatedTime")
        if status_payload
        else record.get("submitted_at", ""),
        "customStatus": status_payload.get("customStatus") if status_payload else None,
        "output": output,
        "artifactCount": len(artifacts) if isinstance(artifacts, dict) else 0,
        "partialFailures": {
            "imagery": output.get("imageryFailed", 0) if output else 0,
            "downloads": output.get("downloadsFailed", 0) if output else 0,
            "postProcess": output.get("postProcessFailed", 0) if output else 0,
        },
        "kmlBlobName": record.get("kml_blob_name", ""),
        "kmlSizeBytes": record.get("kml_size_bytes", 0),
    }


def _history_run_is_active(run: dict[str, Any]) -> bool:
    runtime_status = str(run.get("runtimeStatus") or "").strip().lower()
    return runtime_status not in {"", "completed", "failed", "terminated", "canceled"}


def _reshape_output(output: dict[str, Any]) -> dict[str, Any]:
    """Reshape PipelineSummary to the diagnostics contract (§4.3)."""
    result = {
        "status": output.get("status", ""),
        "message": output.get("message", ""),
        "blobName": output.get("blob_name", ""),
        "featureCount": output.get("feature_count", 0),
        "aoiCount": output.get("aoi_count", 0),
        "metadataCount": output.get("metadata_count", 0),
        "imageryReady": output.get("imagery_ready", 0),
        "imageryFailed": output.get("imagery_failed", 0),
        "downloadsCompleted": output.get("downloads_completed", 0),
        "downloadsFailed": output.get("downloads_failed", 0),
        "postProcessCompleted": output.get("post_process_completed", 0),
        "postProcessFailed": output.get("post_process_failed", 0),
        "artifacts": output.get("artifacts", {}),
    }
    # Pass through enrichment manifest path if present
    if output.get("enrichment_manifest"):
        result["enrichmentManifest"] = output["enrichment_manifest"]
    if output.get("enrichment_duration"):
        result["enrichmentDuration"] = output["enrichment_duration"]
    return result
