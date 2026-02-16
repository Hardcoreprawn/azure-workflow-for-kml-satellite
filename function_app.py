"""Azure Functions entry point — KML Satellite Imagery Pipeline.

This module registers all Azure Functions (triggers, orchestrators, activities)
using the Python v2 programming model.

All business logic lives in the kml_satellite package. This file is purely
the wiring layer between Azure Functions bindings and application code.
"""

from __future__ import annotations

import logging
import os

import azure.durable_functions as df
import azure.functions as func

from kml_satellite.models.blob_event import BlobEvent

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
    event_data = event.get_json()
    event_time = event.event_time.isoformat() if event.event_time else ""

    blob_event = BlobEvent.from_event_grid_event(
        event_data,
        event_time=event_time,
        event_id=event.id or "",
    )

    logger.info(
        "Event Grid trigger fired | blob=%s | container=%s | size=%d | event_id=%s",
        blob_event.blob_name,
        blob_event.container_name,
        blob_event.content_length,
        blob_event.correlation_id,
    )

    # Defence-in-depth: Event Grid subscription filters for .kml in kml-input,
    # but we validate here too in case of misconfiguration.
    if blob_event.container_name != "kml-input":
        logger.warning(
            "Ignoring blob from unexpected container: %s (defence-in-depth filter)",
            blob_event.container_name,
        )
        return

    if not blob_event.blob_name.lower().endswith(".kml"):
        logger.warning(
            "Ignoring non-KML file: %s (defence-in-depth filter)",
            blob_event.blob_name,
        )
        return

    # Start the Durable Functions orchestrator.
    try:
        instance_id = await client.start_new(
            "kml_processing_orchestrator",
            client_input=blob_event.to_dict(),
        )
    except Exception:
        logger.exception(
            "Failed to start orchestrator for blob=%s",
            blob_event.blob_name,
        )
        raise

    logger.info(
        "Orchestrator started | instance_id=%s | blob=%s",
        instance_id,
        blob_event.blob_name,
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
def parse_kml_activity(activityInput: str) -> list[dict[str, object]]:  # noqa: N803
    """Durable Functions activity: parse a KML blob and return features.

    Input:
        JSON string (or dict when replaying) containing a ``BlobEvent``
        payload with ``container_name`` and ``blob_name`` identifying the
        blob to download and parse.

    Returns:
        List of Feature dicts serialised for the orchestrator.

    Raises:
        KmlParseError (via Durable Functions retry) on invalid input.
        ValueError: If required configuration or payload fields are missing.
    """
    import json
    import tempfile
    from pathlib import Path

    from azure.storage.blob import BlobServiceClient

    from kml_satellite.activities.parse_kml import parse_kml_file

    payload: dict[str, object] = (
        json.loads(activityInput) if isinstance(activityInput, str) else activityInput
    )  # type: ignore[assignment]

    container_name = str(payload.get("container_name", ""))
    blob_name = str(payload.get("blob_name", ""))
    correlation_id = str(payload.get("correlation_id", ""))

    # Validate required fields before calling SDK (PID 7.4.1)
    if not container_name:
        msg = "parse_kml activity: container_name is missing from payload"
        raise ValueError(msg)
    if not blob_name:
        msg = "parse_kml activity: blob_name is missing from payload"
        raise ValueError(msg)

    logger.info(
        "parse_kml activity started | blob=%s | correlation_id=%s",
        blob_name,
        correlation_id,
    )

    # Download blob to a temp file for fiona (which needs a file path)
    connection_string = os.environ.get("AzureWebJobsStorage", "")  # noqa: SIM112
    if not connection_string:
        msg = "AzureWebJobsStorage environment variable is not set"
        raise ValueError(msg)
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
    blob_data = blob_client.download_blob().readall()

    with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
        tmp.write(blob_data)
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

    return [f.to_dict() for f in features]


# TODO (Issue #5): parse_kml_multi activity (extends parse_kml for multi-feature)
# TODO (Issue #6): prepare_aoi activity
# TODO (Issue #7): write_metadata activity
# TODO (Issue #8-#12): imagery acquisition activities
