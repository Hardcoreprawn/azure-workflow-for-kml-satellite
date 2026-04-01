"""Event Grid blob trigger: validate uploaded KML and start orchestration.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import logging

import azure.durable_functions as df
import azure.functions as func

from treesight.models.blob_event import BlobEvent

from . import bp
from ._helpers import _extract_blob_name, _extract_container, _validate_blob_event


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

    safe_pipeline_keys = {"provider_name", "target_crs"}
    for key in safe_pipeline_keys:
        if key in data and isinstance(data[key], str):
            orchestrator_input[key] = data[key]

    instance_id = blob_event.correlation_id
    await client.start_new(
        "treesight_orchestrator",
        instance_id=instance_id,
        client_input=orchestrator_input,
    )
    logging.info("Started orchestration instance=%s blob=%s", instance_id, blob_name)
