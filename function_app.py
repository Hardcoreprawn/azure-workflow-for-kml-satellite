"""Azure Functions entry point — KML Satellite Imagery Pipeline.

This module registers all Azure Functions (triggers, orchestrators, activities)
using the Python v2 programming model.

All business logic lives in the kml_satellite package. This file is purely
the wiring layer between Azure Functions bindings and application code.
"""

from __future__ import annotations

import logging

import azure.durable_functions as df
import azure.functions as func

from kml_satellite.core.constants import INPUT_CONTAINER
from kml_satellite.core.ingress import (
    build_orchestrator_input,
    deserialize_activity_input,
    get_blob_service_client,
)
from kml_satellite.models.payloads import (
    AcquireImageryInput,
    DownloadImageryInput,
    ParseKmlInput,
    PollOrderInput,
    PostProcessImageryInput,
    WriteMetadataInput,
    validate_payload,
)

app = func.FunctionApp()

logger = logging.getLogger("kml_satellite.function_app")


# ---------------------------------------------------------------------------
# Trigger: Blob Created → Start Orchestration
# ---------------------------------------------------------------------------


@app.function_name("kml_blob_trigger")
@app.event_grid_trigger(arg_name="event")
@app.durable_client_input(client_name="client")
async def kml_blob_trigger(
    event: func.EventGridEvent, client: df.DurableOrchestrationClient
) -> None:
    """Event Grid trigger that starts the Durable Functions orchestrator.

    Fires when a ``.kml`` blob is created in the ``kml-input`` container.
    Event Grid subscription handles the filtering (suffix, container).

    This function:
    1. Parses the Event Grid event into a ``BlobEvent``
    2. Validates the blob is a ``.kml`` file in the expected container
    3. Starts the orchestrator with the event data
    """
    # Build canonical orchestrator input from the Event Grid event.
    orchestrator_input = build_orchestrator_input(
        event.get_json(),
        event_time=event.event_time.isoformat() if event.event_time else "",
        event_id=event.id or "",
    )

    container = str(orchestrator_input["container_name"])
    blob_name = str(orchestrator_input["blob_name"])
    tenant_id = str(orchestrator_input.get("tenant_id", ""))

    logger.info(
        "Event Grid trigger fired | blob=%s | container=%s | size=%d | event_id=%s | tenant_id=%s",
        blob_name,
        container,
        orchestrator_input["content_length"],
        orchestrator_input["correlation_id"],
        tenant_id,
    )

    # Defence-in-depth: Event Grid subscription filters for .kml in kml-input,
    # but we validate here too in case of misconfiguration.
    if container != INPUT_CONTAINER:
        logger.warning(
            "Ignoring blob from unexpected container: %s (defence-in-depth filter)",
            container,
        )
        return

    if not blob_name.lower().endswith(".kml"):
        logger.warning(
            "Ignoring non-KML file: %s (defence-in-depth filter)",
            blob_name,
        )
        return

    # Start the Durable Functions orchestrator.
    try:
        instance_id = await client.start_new(
            "kml_processing_orchestrator",
            client_input=orchestrator_input,
        )
    except Exception:
        logger.exception(
            "Failed to start orchestrator for blob=%s",
            blob_name,
        )
        raise

    logger.info(
        "Orchestrator started | instance_id=%s | blob=%s",
        instance_id,
        blob_name,
    )


# ---------------------------------------------------------------------------
# Orchestrator: KML Processing Pipeline
# ---------------------------------------------------------------------------


@app.function_name("kml_processing_orchestrator")
@app.orchestration_trigger(context_name="context")
def kml_processing_orchestrator(context: df.DurableOrchestrationContext) -> object:
    """Durable Functions orchestrator for the KML processing pipeline.

    Coordinates: parse KML → fan-out per polygon → acquire imagery → fan-in.
    See ``kml_satellite.orchestrators.kml_pipeline`` for implementation.
    """
    from kml_satellite.orchestrators.kml_pipeline import orchestrator_function

    return orchestrator_function(context)


@app.function_name("poll_order_suborchestrator")
@app.orchestration_trigger(context_name="context")
def poll_order_suborchestrator(context: df.DurableOrchestrationContext) -> object:
    """Sub-orchestrator: poll a single imagery order until terminal.

    Called concurrently via ``task_all`` from the acquisition phase
    (Issue #55) to poll multiple orders in parallel.

    Input (via ``context.get_input``):
        Dict with ``acquisition``, ``poll_interval``, ``poll_timeout``,
        ``max_retries``, ``retry_base``, ``instance_id``.

    Returns:
        Dict describing the final outcome from ``_poll_until_ready``.
    """
    from kml_satellite.orchestrators.phases import _poll_until_ready

    sub_input: dict[str, object] = context.get_input() or {}
    acquisition = sub_input.get("acquisition", {})
    if not isinstance(acquisition, dict):
        acquisition = {}

    def _int_val(key: str, default: int) -> int:
        raw = sub_input.get(key, default)
        if isinstance(raw, int | float | str):
            try:
                return int(raw)
            except (ValueError, OverflowError):
                return default
        return default

    return _poll_until_ready(
        context,
        acquisition,
        poll_interval=_int_val("poll_interval", 30),
        poll_timeout=_int_val("poll_timeout", 1800),
        max_retries=_int_val("max_retries", 3),
        retry_base=_int_val("retry_base", 5),
        instance_id=str(sub_input.get("instance_id", "")),
    )


# ---------------------------------------------------------------------------
# HTTP: Orchestrator Status Endpoint (convenience for local debugging)
# ---------------------------------------------------------------------------


@app.function_name("orchestrator_status")
@app.route(route="orchestrator/{instance_id}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def orchestrator_status(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """Return the status of a specific orchestrator instance.

    Useful for local development and debugging. Production monitoring
    uses Application Insights.
    """
    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return func.HttpResponse("Missing instance_id", status_code=400)

    status = await client.get_status(instance_id)
    if not status:
        return func.HttpResponse("Instance not found", status_code=404)

    return client.create_check_status_response(req, instance_id)


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@app.function_name("parse_kml")
@app.activity_trigger(input_name="activityInput")
def parse_kml_activity(activityInput: str) -> list[dict[str, object]] | dict[str, object]:  # noqa: N803
    """Durable Functions activity: parse a KML blob and return features.

    Input:
        JSON string (or dict when replaying) containing a ``BlobEvent``
        payload with ``container_name`` and ``blob_name`` identifying the
        blob to download and parse.

    Returns:
        List of Feature dicts serialised for the orchestrator, **or** a
        small offloaded-payload reference dict when the serialised list
        exceeds the offload threshold (Issue #62).

    Raises:
        KmlParseError (via Durable Functions retry) on invalid input.
        ValueError: If required configuration or payload fields are missing.
    """
    import tempfile
    from pathlib import Path

    from kml_satellite.activities.parse_kml import parse_kml_file

    payload = deserialize_activity_input(activityInput)
    validate_payload(payload, ParseKmlInput, activity="parse_kml")

    container_name = str(payload.get("container_name", ""))
    blob_name = str(payload.get("blob_name", ""))
    correlation_id = str(payload.get("correlation_id", ""))

    logger.info(
        "parse_kml activity started | blob=%s | correlation_id=%s",
        blob_name,
        correlation_id,
    )

    # Download blob to a temp file for fiona (which needs a file path)
    blob_service = get_blob_service_client()
    blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)

    with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
        blob_client.download_blob().readinto(tmp)
        tmp_path = Path(tmp.name)

    try:
        features = parse_kml_file(tmp_path, source_filename=blob_name)
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(
        "parse_kml activity completed | blob=%s | features=%d | correlation_id=%s",
        blob_name,
        len(features),
        correlation_id,
    )

    from kml_satellite.core.payload_offload import offload_if_large

    feature_dicts: list[dict[str, object]] = [f.to_dict() for f in features]
    return offload_if_large(
        feature_dicts,
        blob_path=f"payloads/{correlation_id or 'no-id'}/features.json",
        blob_service_client=blob_service,
    )


@app.function_name("prepare_aoi")
@app.activity_trigger(input_name="activityInput")
def prepare_aoi_activity(activityInput: str) -> dict[str, object]:  # noqa: N803
    """Durable Functions activity: compute AOI geometry metadata for a feature.

    Input:
        JSON string (or dict when replaying) containing either:
        - A serialised ``Feature`` dict from the parse_kml activity, **or**
        - A payload reference (``__payload_ref__``) + index for offloaded
          features (Issue #62).

    Returns:
        AOI dict serialised for the orchestrator.

    Raises:
        AOIError: If the feature has invalid geometry.
    """
    from kml_satellite.activities.prepare_aoi import prepare_aoi
    from kml_satellite.core.payload_offload import resolve_ref_input
    from kml_satellite.models.feature import Feature as FeatureModel

    payload = deserialize_activity_input(activityInput)

    # Resolve payload reference if features were offloaded (Issue #62)
    payload = resolve_ref_input(payload, blob_service_client=get_blob_service_client())

    feature = FeatureModel.from_dict(payload)

    logger.info(
        "prepare_aoi activity started | feature=%s | source=%s",
        feature.name,
        feature.source_file,
    )

    aoi = prepare_aoi(feature)

    logger.info(
        "prepare_aoi activity completed | feature=%s | area=%.2f ha | buffer=%.0f m",
        feature.name,
        aoi.area_ha,
        aoi.buffer_m,
    )

    return aoi.to_dict()


@app.function_name("write_metadata")
@app.activity_trigger(input_name="activityInput")
def write_metadata_activity(activityInput: str) -> dict[str, object]:  # noqa: N803
    """Durable Functions activity: generate and store per-AOI metadata JSON.

    Input:
        JSON string (or dict when replaying) containing:
        - ``aoi``: Serialised AOI dict from the prepare_aoi activity
        - ``processing_id``: Orchestration instance ID
        - ``timestamp``: Processing timestamp (ISO 8601)

    Returns:
        Dict with ``metadata``, ``metadata_path``, and ``kml_archive_path``.

    Raises:
        MetadataWriteError: If blob upload fails.
    """
    from kml_satellite.activities.write_metadata import write_metadata
    from kml_satellite.models.aoi import AOI as AOIModel  # noqa: N811

    payload = deserialize_activity_input(activityInput)
    validate_payload(payload, WriteMetadataInput, activity="write_metadata")

    aoi_data = payload.get("aoi", payload)
    if not isinstance(aoi_data, dict):
        msg = "write_metadata activity: aoi data must be a dict"
        raise TypeError(msg)

    aoi = AOIModel.from_dict(aoi_data)
    processing_id = str(payload.get("processing_id", ""))
    timestamp = str(payload.get("timestamp", ""))
    tenant_id = str(payload.get("tenant_id", ""))

    logger.info(
        "write_metadata activity started | feature=%s | processing_id=%s",
        aoi.feature_name,
        processing_id,
    )

    # Connect to Blob Storage for writing (optional — not all paths require it)
    try:
        blob_service = get_blob_service_client()
    except Exception:
        blob_service = None

    result = write_metadata(
        aoi,
        processing_id=processing_id,
        timestamp=timestamp,
        tenant_id=tenant_id,
        blob_service_client=blob_service,
    )

    logger.info(
        "write_metadata activity completed | feature=%s | path=%s",
        aoi.feature_name,
        result.get("metadata_path", ""),
    )

    return result


# TODO (Issue #13-#19): compositing and delivery activities


@app.function_name("acquire_imagery")
@app.activity_trigger(input_name="activityInput")
def acquire_imagery_activity(activityInput: str) -> dict[str, object]:  # noqa: N803
    """Durable Functions activity: search for imagery and submit an order.

    Input:
        JSON string (or dict when replaying) containing:
        - ``aoi``: Serialised AOI dict from the prepare_aoi activity.
        - ``provider_name``: Imagery provider name (default ``"planetary_computer"``).
        - ``provider_config``: Optional provider configuration overrides.
        - ``imagery_filters``: Optional imagery filter overrides.

    Returns:
        Dict with ``order_id``, ``scene_id``, ``provider``, and scene metadata.

    Raises:
        ImageryAcquisitionError: If search or order fails.
    """
    from kml_satellite.activities.acquire_imagery import acquire_imagery

    payload = deserialize_activity_input(activityInput)
    validate_payload(payload, AcquireImageryInput, activity="acquire_imagery")

    aoi_data = payload.get("aoi", payload)
    if not isinstance(aoi_data, dict):
        msg = "acquire_imagery activity: aoi data must be a dict"
        raise TypeError(msg)

    provider_name = str(payload.get("provider_name", "planetary_computer"))
    provider_config = payload.get("provider_config")
    imagery_filters = payload.get("imagery_filters")

    logger.info(
        "acquire_imagery activity started | provider=%s",
        provider_name,
    )

    result = acquire_imagery(
        aoi_data,
        provider_name=provider_name,
        provider_config=provider_config,  # type: ignore[arg-type]
        filters_dict=imagery_filters,  # type: ignore[arg-type]
    )

    logger.info(
        "acquire_imagery activity completed | order_id=%s | scene=%s",
        result.get("order_id", ""),
        result.get("scene_id", ""),
    )

    return result


@app.function_name("poll_order")
@app.activity_trigger(input_name="activityInput")
def poll_order_activity(activityInput: str) -> dict[str, object]:  # noqa: N803
    """Durable Functions activity: poll the status of an imagery order.

    Input:
        JSON string (or dict when replaying) containing:
        - ``order_id``: The order identifier to poll.
        - ``provider``: The imagery provider name.

    Returns:
        Dict with ``order_id``, ``state``, ``message``, ``progress_pct``,
        and ``is_terminal``.

    Raises:
        PollError: If polling fails.
    """
    from kml_satellite.activities.poll_order import poll_order

    payload = deserialize_activity_input(activityInput)
    validate_payload(payload, PollOrderInput, activity="poll_order")

    logger.info(
        "poll_order activity started | order_id=%s",
        payload.get("order_id", ""),
    )

    result = poll_order(payload)

    logger.info(
        "poll_order activity completed | order_id=%s | state=%s",
        result.get("order_id", ""),
        result.get("state", ""),
    )

    return result


@app.function_name("download_imagery")
@app.activity_trigger(input_name="activityInput")
def download_imagery_activity(activityInput: str) -> dict[str, object]:  # noqa: N803
    """Durable Functions activity: download GeoTIFF and store in Blob Storage.

    Input:
        JSON string (or dict when replaying) containing:
        - ``imagery_outcome``: Dict from the polling phase with
          ``order_id``, ``scene_id``, ``provider``, ``aoi_feature_name``.
        - ``provider_name``: Imagery provider name (default ``"planetary_computer"``).
        - ``provider_config``: Optional provider configuration overrides.
        - ``project_name``: Project name for blob path generation.
        - ``timestamp``: Processing timestamp (ISO 8601).

    Returns:
        Dict with ``order_id``, ``blob_path``, ``size_bytes``,
        ``download_duration_seconds``, and ``retry_count``.

    Raises:
        DownloadError: If download fails after retries or validation fails.
    """
    from kml_satellite.activities.download_imagery import download_imagery

    payload = deserialize_activity_input(activityInput)
    validate_payload(payload, DownloadImageryInput, activity="download_imagery")

    imagery_outcome = payload.get("imagery_outcome", payload)
    if not isinstance(imagery_outcome, dict):
        msg = "download_imagery activity: imagery_outcome must be a dict"
        raise TypeError(msg)

    provider_name = str(payload.get("provider_name", "planetary_computer"))
    provider_config = payload.get("provider_config")
    project_name = str(payload.get("project_name", ""))
    timestamp = str(payload.get("timestamp", ""))
    output_container = str(payload.get("output_container", "kml-output"))

    logger.info(
        "download_imagery activity started | order_id=%s | feature=%s",
        imagery_outcome.get("order_id", ""),
        imagery_outcome.get("aoi_feature_name", ""),
    )

    result = download_imagery(
        imagery_outcome,
        provider_name=provider_name,
        provider_config=provider_config,  # type: ignore[arg-type]
        project_name=project_name,
        timestamp=timestamp,
        output_container=output_container,
    )

    logger.info(
        "download_imagery activity completed | order_id=%s | blob_path=%s | size=%s bytes",
        result.get("order_id", ""),
        result.get("blob_path", ""),
        result.get("size_bytes", 0),
    )

    return result


@app.function_name("post_process_imagery")
@app.activity_trigger(input_name="activityInput")
def post_process_imagery_activity(activityInput: str) -> dict[str, object]:  # noqa: N803
    """Durable Functions activity: clip and reproject downloaded imagery.

    Input:
        JSON string (or dict when replaying) containing:
        - ``download_result``: Dict from download_imagery with
          ``order_id``, ``blob_path``, ``size_bytes``, etc.
        - ``aoi``: Serialised AOI dict with polygon geometry.
        - ``project_name``: Project name for output path.
        - ``timestamp``: Processing timestamp (ISO 8601).
        - ``target_crs``: Target CRS for reprojection (default EPSG:4326).
        - ``enable_clipping``: Whether to clip (default True).
        - ``enable_reprojection``: Whether to reproject (default True).

    Returns:
        Dict with ``order_id``, ``clipped_blob_path``, ``clipped``,
        ``reprojected``, ``source_crs``, ``target_crs``, and sizes.

    Raises:
        PostProcessError: If a fatal error prevents useful output.
    """
    from kml_satellite.activities.post_process_imagery import post_process_imagery

    payload = deserialize_activity_input(activityInput)
    validate_payload(payload, PostProcessImageryInput, activity="post_process_imagery")

    download_result = payload.get("download_result", payload)
    if not isinstance(download_result, dict):
        msg = "post_process_imagery activity: download_result must be a dict"
        raise TypeError(msg)

    aoi_data = payload.get("aoi", {})
    if not isinstance(aoi_data, dict):
        msg = "post_process_imagery activity: aoi must be a dict"
        raise TypeError(msg)

    project_name = str(payload.get("project_name", ""))
    timestamp = str(payload.get("timestamp", ""))
    target_crs = str(payload.get("target_crs", "EPSG:4326"))
    enable_clipping = bool(payload.get("enable_clipping", True))
    enable_reprojection = bool(payload.get("enable_reprojection", True))
    output_container = str(payload.get("output_container", "kml-output"))

    logger.info(
        "post_process_imagery activity started | order_id=%s | feature=%s",
        download_result.get("order_id", ""),
        aoi_data.get("feature_name", ""),
    )

    result = post_process_imagery(
        download_result,
        aoi_data,
        project_name=project_name,
        timestamp=timestamp,
        target_crs=target_crs,
        enable_clipping=enable_clipping,
        enable_reprojection=enable_reprojection,
        output_container=output_container,
    )

    logger.info(
        "post_process_imagery activity completed | order_id=%s | "
        "clipped=%s | reprojected=%s | output=%s",
        result.get("order_id", ""),
        result.get("clipped", False),
        result.get("reprojected", False),
        result.get("clipped_blob_path", ""),
    )

    return result
