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

from treesight.config import config_get_int
from treesight.constants import DEFAULT_OUTPUT_CONTAINER, DEFAULT_PROVIDER

from . import bp

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
    from treesight.models.blob_event import BlobEvent
    from treesight.pipeline.ingestion import parse_kml_from_blob
    from treesight.storage.client import BlobStorageClient
    from treesight.storage.offload import PayloadOffloader

    blob_event = BlobEvent.model_validate(payload)
    storage = BlobStorageClient()
    features = parse_kml_from_blob(blob_event, storage)

    from treesight.constants import MAX_FEATURES_PER_KML

    if len(features) > MAX_FEATURES_PER_KML:
        raise ValueError(
            f"KML contains {len(features)} features, exceeding the limit of {MAX_FEATURES_PER_KML}"
        )

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
            logging.getLogger(__name__).warning(
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
def poll_order(payload: _Payload) -> dict[str, Any]:
    from treesight.pipeline.acquisition import poll_order as _poll
    from treesight.providers.registry import get_provider

    provider = get_provider(
        payload.get("provider_name", DEFAULT_PROVIDER),
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
        eudr_mode=payload.get("eudr_mode", False),
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
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
def release_quota(payload: _Payload) -> dict[str, Any]:
    """Refund a quota slot when a pipeline run fails."""
    from treesight.security.quota import release_quota as _release

    user_id: str = payload["user_id"]
    instance_id: str = payload.get("instance_id", "")
    remaining = _release(user_id, instance_id=instance_id)
    logging.info(
        "Quota released (run failed) user=%s instance=%s remaining=%d",
        user_id,
        instance_id,
        remaining,
    )
    return {"released": True, "remaining": remaining}
