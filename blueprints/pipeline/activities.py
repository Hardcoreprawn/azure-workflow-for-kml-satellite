"""Durable activity functions: Ingestion, Acquisition, Fulfilment, Enrichment.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
The Azure Functions v2 runtime inspects binding parameter annotations at
import time.  PEP 563 (stringified annotations) causes the runtime to fail
with ``FunctionLoadError: binding payload has invalid non-type annotation``.
For the same reason, activity trigger ``payload`` parameters use bare ``dict``
instead of ``dict[str, Any]`` — the runtime cannot resolve parameterised
generics on binding arguments.
"""

import logging
from typing import TYPE_CHECKING, Any

from treesight.constants import DEFAULT_OUTPUT_CONTAINER, DEFAULT_PROVIDER

from . import bp

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    _Payload = dict[str, Any]
else:
    _Payload = dict


# ---------------------------------------------------------------------------
# Ingestion activities
# ---------------------------------------------------------------------------


def _load_aoi(payload: dict[str, Any], storage: Any = None) -> Any:
    """Resolve AOI from claim-check ref or inline ``aoi`` dict."""
    from treesight.models.aoi import AOI
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    if payload.get("aoi_ref"):
        s = storage or BlobStorageClient()
        data = PayloadOffloader(s).load_claim(payload["aoi_ref"])
        return AOI.model_validate(data)
    return AOI.model_validate(payload["aoi"])


@bp.activity_trigger(input_name="payload")
def parse_kml(payload: _Payload) -> list[dict[str, Any]] | dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError(f"parse_kml expects dict payload, got {type(payload).__name__}")

    from treesight.models.blob_event import BlobEvent
    from treesight.pipeline.ingestion import parse_kml_from_blob
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    logger.info(
        "parse_kml: started correlation_id=%s",
        payload.get("correlation_id", "unknown"),
    )
    blob_event = BlobEvent.model_validate(payload)
    storage = BlobStorageClient()
    logger.info(
        "parse_kml: parsing container=%s blob=%s",
        blob_event.container_name,
        blob_event.blob_name,
    )
    features = parse_kml_from_blob(blob_event, storage)
    logger.info("parse_kml: got features=%d", len(features))

    from treesight.constants import MAX_FEATURES_PER_KML

    if len(features) > MAX_FEATURES_PER_KML:
        raise ValueError(f"KML contains {len(features)} features, exceeding the limit of {MAX_FEATURES_PER_KML}")

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
    from treesight.pipeline.ingestion import write_metadata as _write
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    aoi = _load_aoi(payload, storage)

    kml_bytes: bytes | None = None
    input_container = payload.get("input_container", "")
    source_file = payload["source_file"]
    if input_container and source_file:
        try:
            kml_bytes = storage.download_bytes(input_container, source_file)
        except Exception:
            logger.warning(
                "Failed to download source KML %s/%s for metadata",
                input_container,
                source_file,
                exc_info=True,
            )

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
def store_aoi_claims(payload: _Payload) -> list[dict[str, str]]:
    """Claim-check: store AOIs in blob storage, return lightweight refs."""
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    offloader = PayloadOffloader(BlobStorageClient())
    return offloader.store_claims_batch(
        instance_id=payload["instance_id"],
        items=payload["aois"],
        key_field="feature_name",
    )


@bp.activity_trigger(input_name="payload")
def load_aoi_claim(payload: _Payload) -> dict[str, Any]:
    """Claim-check: retrieve a single AOI by blob ref."""
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    offloader = PayloadOffloader(BlobStorageClient())
    return offloader.load_claim(payload.get("aoi_ref") or payload["ref"])


# ---------------------------------------------------------------------------
# Acquisition activities
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def acquire_imagery(payload: _Payload) -> dict[str, Any]:
    from treesight.models.imagery import ImageryFilters
    from treesight.pipeline.acquisition import acquire_imagery as _acquire
    from treesight.providers.registry import get_provider

    aoi = _load_aoi(payload)
    provider = get_provider(
        payload.get("provider_name", DEFAULT_PROVIDER),
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
    from treesight.models.imagery import ImageryFilters
    from treesight.pipeline.acquisition import acquire_composite as _composite
    from treesight.providers.registry import get_provider

    aoi = _load_aoi(payload)
    provider = get_provider(
        payload.get("provider_name", DEFAULT_PROVIDER),
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
def check_order_status(payload: _Payload) -> dict[str, Any]:
    from treesight.pipeline.acquisition import check_order_status as _check
    from treesight.providers.registry import get_provider

    provider = get_provider(
        payload.get("provider_name", DEFAULT_PROVIDER),
        payload.get("provider_config"),
    )
    result = _check(payload["order_id"], provider)
    result["scene_id"] = payload.get("scene_id", "")
    result["aoi_feature_name"] = payload.get("aoi_feature_name", "")
    return result


# ---------------------------------------------------------------------------
# Fulfilment activities
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def download_imagery(payload: _Payload) -> dict[str, Any]:
    from treesight.pipeline.fulfilment import download_imagery as _download
    from treesight.providers.registry import get_provider
    from treesight.storage.client import BlobStorageClient

    provider = get_provider(
        payload.get("provider_name", DEFAULT_PROVIDER),
        payload.get("provider_config"),
    )
    storage = BlobStorageClient()

    # Resolve aoi_bbox from claim check or inline payload
    aoi_bbox = payload.get("aoi_bbox")
    if not aoi_bbox and payload.get("aoi_ref"):
        aoi = _load_aoi(payload, storage)
        aoi_bbox = aoi.buffered_bbox

    return _download(
        outcome=payload["outcome"],
        provider=provider,
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        output_container=payload["output_container"],
        storage=storage,
        asset_url=payload.get("asset_url", ""),
        aoi_bbox=aoi_bbox,
        role=payload.get("role", ""),
        collection=payload.get("collection", ""),
    )


@bp.activity_trigger(input_name="payload")
def post_process_imagery(payload: _Payload) -> dict[str, Any]:
    from treesight.pipeline.fulfilment import post_process_imagery as _post_process
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    aoi = _load_aoi(payload, storage)
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


# ---------------------------------------------------------------------------
# Enrichment activity
# ---------------------------------------------------------------------------


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
        per_aoi_coords=payload.get("per_aoi_coords"),
        eudr_mode=payload.get("eudr_mode", False),
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
        cadence=payload.get("cadence", "maximum"),
        max_history_years=payload.get("max_history_years"),
    )


# ---------------------------------------------------------------------------
# Enrichment sub-step activities (#574 — parallel fan-out)
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def enrich_data_sources(payload: _Payload) -> dict[str, Any]:
    """Enrichment sub-step 1: weather, flood/fire, EUDR datasets.

    When SAFE_MODE is enabled (#759), skip non-critical external data sources
    (weather, flood/fire, EUDR datasets) and return an empty dict so the
    determination pipeline still runs to completion.
    """
    from treesight import config

    if config.SAFE_MODE:
        logger.info("SAFE_MODE: skipping enrich_data_sources")
        return {"safe_mode": True, "skipped": ["weather", "flood_fire", "eudr_datasets"]}

    from treesight.pipeline.enrichment import enrich_data_sources as _enrich_ds

    return _enrich_ds(
        payload["coords"],
        eudr_mode=payload.get("eudr_mode", False),
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
        cadence=payload.get("cadence", "maximum"),
        max_history_years=payload.get("max_history_years"),
    )


@bp.activity_trigger(input_name="payload")
def enrich_imagery(payload: _Payload) -> dict[str, Any]:
    """Enrichment sub-step 2: mosaic registration, NDVI, change detection."""
    from treesight.pipeline.enrichment import enrich_imagery as _enrich_img
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    return _enrich_img(
        payload["coords"],
        eudr_mode=payload.get("eudr_mode", False),
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
        cadence=payload.get("cadence", "maximum"),
        max_history_years=payload.get("max_history_years"),
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        output_container=payload.get("output_container", DEFAULT_OUTPUT_CONTAINER),
        storage=storage,
    )


@bp.activity_trigger(input_name="payload")
def enrich_single_aoi(payload: _Payload) -> dict[str, Any]:
    """Enrichment sub-step 3a: per-AOI enrichment (fan-out one per AOI)."""
    from treesight.pipeline.enrichment import enrich_single_aoi_step as _enrich_aoi
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    return _enrich_aoi(
        payload["aoi_entry"],
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
        cadence=payload.get("cadence", "maximum"),
        max_history_years=payload.get("max_history_years"),
        eudr_mode=payload.get("eudr_mode", False),
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        output_container=payload.get("output_container", DEFAULT_OUTPUT_CONTAINER),
        storage=storage,
    )


@bp.activity_trigger(input_name="payload")
def enrich_finalize(payload: _Payload) -> dict[str, Any]:
    """Enrichment sub-step 4: merge parallel results + store manifest."""
    from treesight.pipeline.enrichment import enrich_finalize as _finalize
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    return _finalize(
        payload["data_sources"],
        payload["imagery"],
        payload.get("per_aoi_results", []),
        eudr_mode=payload.get("eudr_mode", False),
        date_start=payload.get("date_start"),
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
        output_container=payload.get("output_container", DEFAULT_OUTPUT_CONTAINER),
        storage=storage,
    )


# ---------------------------------------------------------------------------
# Azure Batch fallback activities (#315)
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def submit_batch_fulfilment(payload: _Payload) -> dict[str, Any]:
    """Submit an oversized-AOI fulfilment job to Azure Batch Spot VMs."""
    from treesight.pipeline.batch import submit_batch_job

    outcome = payload["outcome"]
    return submit_batch_job(
        aoi_ref=outcome.get("aoi_feature_name", ""),
        claim_key=outcome.get("order_id", ""),
        asset_url=payload.get("asset_url", ""),
        output_container=payload["output_container"],
        project_name=payload["project_name"],
        timestamp=payload["timestamp"],
    )


@bp.activity_trigger(input_name="payload")
def poll_batch_fulfilment(payload: _Payload) -> dict[str, Any]:
    """Poll an Azure Batch task for completion."""
    from treesight.pipeline.batch import poll_batch_task

    return poll_batch_task(payload["job_id"], payload["task_id"])


@bp.activity_trigger(input_name="payload")
def complete_billing(payload: _Payload) -> dict[str, Any]:
    """Mark a run as charged in the billing ledger (#589)."""
    from treesight.security.billing_ledger import complete_run_billing

    user_id: str = payload["user_id"]
    instance_id: str = payload["instance_id"]
    complete_run_billing(user_id, instance_id)
    return {"completed": True}


@bp.activity_trigger(input_name="payload")
def fail_billing(payload: _Payload) -> dict[str, Any]:
    """Mark a run as refunded in the billing ledger (#589)."""
    from treesight.security.billing_ledger import fail_run_billing

    user_id: str = payload["user_id"]
    instance_id: str = payload["instance_id"]
    reason: str = payload.get("reason", "pipeline_failure")
    fail_run_billing(user_id, instance_id, reason=reason)
    return {"refunded": True}


# ---------------------------------------------------------------------------
# Org-pooled run accounting (Stage 2 of #814)
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def finalize_run_completed(payload: _Payload) -> dict[str, Any]:
    """Finalize a completed run in org-pooled accounting (#814).

    Moves runs from reserved → completed in org.usage, emits Stripe metered event.
    """
    from treesight.billing.accounting import finalize_run
    from treesight.pipeline.concurrency import release_admission_slot

    org_id: str = payload["org_id"]
    instance_id: str = payload["instance_id"]

    try:
        finalize_run(org_id=org_id, instance_id=instance_id, status="completed")
        release_admission_slot(instance_id)
        logger.info(
            "Run finalized (completed) org=%s instance=%s",
            org_id,
            instance_id,
        )
        return {"finalized": True, "status": "completed"}
    except Exception:
        logger.exception(
            "Failed to finalize run (completed) org=%s instance=%s",
            org_id,
            instance_id,
        )
        raise


@bp.activity_trigger(input_name="payload")
def finalize_run_failed(payload: _Payload) -> dict[str, Any]:
    """Finalize a failed run in org-pooled accounting (#814).

    Moves runs from reserved → refunded in org.usage, refunds member per-period cap.
    """
    from treesight.billing.accounting import finalize_run
    from treesight.pipeline.concurrency import release_admission_slot

    org_id: str = payload["org_id"]
    instance_id: str = payload["instance_id"]

    try:
        finalize_run(org_id=org_id, instance_id=instance_id, status="failed")
        release_admission_slot(instance_id)
        logger.info(
            "Run finalized (failed) org=%s instance=%s",
            org_id,
            instance_id,
        )
        return {"finalized": True, "status": "failed"}
    except Exception:
        logger.exception(
            "Failed to finalize run (failed) org=%s instance=%s",
            org_id,
            instance_id,
        )
        raise


# ---------------------------------------------------------------------------
# Pipeline telemetry (#400)
# ---------------------------------------------------------------------------


@bp.activity_trigger(input_name="payload")
def write_pipeline_stats(payload: _Payload) -> dict[str, Any]:
    """Write per-run telemetry to the ``pipeline_stats`` Cosmos container (#400).

    Best-effort: the orchestrator already wraps this call in a try/except
    (a Cosmos failure must never block the pipeline result), but this
    function also catches its own errors and returns ``{"written": False}``
    rather than raising, so a malformed payload or transient Cosmos error
    never surfaces as a Durable activity failure.
    """
    from treesight.constants import COSMOS_CONTAINER_PIPELINE_STATS
    from treesight.pipeline.telemetry import build_stats_document
    from treesight.storage import cosmos as _cosmos

    if not _cosmos.cosmos_available():
        logger.info("write_pipeline_stats: Cosmos not configured, skipping")
        return {"written": False, "reason": "cosmos_unavailable"}

    try:
        doc = build_stats_document(
            instance_id=payload["instance_id"],
            user_id=payload.get("user_id", ""),
            tier=payload.get("tier", ""),
            aoi_count=payload.get("aoi_count", 0),
            aoi_area_by_name=payload.get("aoi_area_by_name", {}),
            aoi_centroids=payload.get("aoi_centroids", []),
            image_count=payload.get("image_count", 0),
            batch_used=bool(payload.get("batch_used", False)),
            enrichment=payload.get("enrichment", {}),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            status=payload.get("status", "completed"),
        )
        _cosmos.upsert_item(COSMOS_CONTAINER_PIPELINE_STATS, doc)
    except Exception:
        logger.exception("write_pipeline_stats: failed to write stats")
        return {"written": False, "reason": "error"}

    logger.info(
        "write_pipeline_stats: wrote stats for instance=%s aoi_count=%s",
        doc["instance_id"],
        doc["aoi_count"],
    )
    return {"written": True, "instance_id": doc["instance_id"]}
