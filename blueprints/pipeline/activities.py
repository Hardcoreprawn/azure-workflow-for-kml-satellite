"""Durable activity functions: Ingestion, Acquisition, Fulfilment, Enrichment.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
The Azure Functions v2 runtime inspects binding parameter annotations at
import time.  PEP 563 (stringified annotations) causes the runtime to fail
with ``FunctionLoadError: binding payload has invalid non-type annotation``.
For the same reason, activity trigger ``payload`` parameters use bare ``dict``
instead of ``dict[str, Any]`` — the runtime cannot resolve parameterised
generics on binding arguments.
"""

import contextlib
from typing import TYPE_CHECKING, Any

from treesight.config import config_get_int
from treesight.constants import DEFAULT_OUTPUT_CONTAINER

from . import bp

if TYPE_CHECKING:
    _Payload = dict[str, Any]
else:
    _Payload = dict


# ---------------------------------------------------------------------------
# Ingestion activities
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


# ---------------------------------------------------------------------------
# Acquisition activities
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Fulfilment activities
# ---------------------------------------------------------------------------


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
