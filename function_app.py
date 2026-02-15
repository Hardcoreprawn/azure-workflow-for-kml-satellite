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

from kml_satellite.models.blob_event import BlobEvent

app = func.FunctionApp()

logger = logging.getLogger("kml_satellite.function_app")


# ---------------------------------------------------------------------------
# Trigger: Blob Created → Start Orchestration
# ---------------------------------------------------------------------------


@app.function_name("kml_blob_trigger")
@app.event_grid_trigger(arg_name="event")
@app.durable_client_input(client_name="starter")
async def kml_blob_trigger(event: func.EventGridEvent, starter) -> None:
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
    if not blob_event.blob_name.lower().endswith(".kml"):
        logger.warning(
            "Ignoring non-KML file: %s (defence-in-depth filter)",
            blob_event.blob_name,
        )
        return

    # Start the Durable Functions orchestrator.
    client = df.DurableOrchestrationClient(starter)
    instance_id = await client.start_new(
        "kml_processing_orchestrator",
        client_input=blob_event.to_dict(),
    )

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
# TODO (Issue #4): parse_kml activity
# TODO (Issue #5): parse_kml_multi activity
# TODO (Issue #6): prepare_aoi activity
# TODO (Issue #7): write_metadata activity
# TODO (Issue #8-#12): imagery acquisition activities
