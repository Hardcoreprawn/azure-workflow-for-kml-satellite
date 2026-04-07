"""Event Grid blob trigger: validate uploaded KML and start orchestration.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import logging
import uuid
from pathlib import PurePosixPath

import azure.durable_functions as df
import azure.functions as func

from treesight.models.blob_event import BlobEvent
from treesight.security.billing import get_effective_subscription, plan_capabilities

from . import bp
from ._helpers import _extract_blob_name, _extract_container, _validate_blob_event

logger = logging.getLogger(__name__)


def _read_submission_ticket(container_name: str, blob_name: str) -> dict | None:
    """Read the ticket blob written by SWA API or submission endpoint.

    Returns ``None`` if no ticket is found (e.g. storage-native uploads).
    Logs a warning on transient errors to make billing/tier failures visible.
    """
    parts = PurePosixPath(blob_name).parts
    if len(parts) < 2:
        return None
    stem = PurePosixPath(parts[-1]).stem
    ticket_path = f".tickets/{stem}.json"
    try:
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        return storage.download_json(container_name, ticket_path)
    except Exception as exc:
        # Distinguish "not found" from transient/unexpected errors.
        exc_name = type(exc).__name__
        if "NotFound" in exc_name or "ResourceNotFound" in exc_name:
            logger.debug("No ticket found for blob=%s (path=%s)", blob_name, ticket_path)
        else:
            logger.warning(
                "Ticket read failed for blob=%s (path=%s): %s", blob_name, ticket_path, exc_name
            )
        return None


def _derive_instance_id(blob_name: str, event_id: str) -> str:
    """Derive the orchestrator instance ID from the blob path.

    For ``analysis/{submission_id}.kml`` blobs (submitted via the SWA API
    or submission endpoint), use the submission_id so the frontend can
    poll status by the ID it received at upload time.

    Only uses the stem if it is a valid UUID (matching the submission_id
    format), preventing arbitrary instance ID injection.

    For other blobs (storage-native uploads), use the Event Grid event ID.
    """
    parts = PurePosixPath(blob_name).parts
    if len(parts) == 2 and parts[0] == "analysis":
        stem = PurePosixPath(parts[-1]).stem
        try:
            uuid.UUID(stem)
            return stem
        except ValueError:
            pass
    return event_id


def _enrich_from_ticket(orchestrator_input: dict, ticket: dict) -> None:
    """Add user metadata and billing tier to the orchestrator input."""
    user_id = ticket.get("user_id", "")
    if isinstance(user_id, str) and user_id:
        orchestrator_input["user_id"] = user_id

    # Copy through typed fields already resolved by submission endpoint
    tier = ticket.get("tier")
    if isinstance(tier, str) and tier:
        orchestrator_input["tier"] = tier
    cadence = ticket.get("cadence")
    if isinstance(cadence, str) and cadence:
        orchestrator_input["cadence"] = cadence
    max_hist = ticket.get("max_history_years")
    if isinstance(max_hist, (int, float)) and max_hist >= 0:
        orchestrator_input["max_history_years"] = int(max_hist)
    provider = ticket.get("provider_name")
    if isinstance(provider, str) and provider:
        orchestrator_input["provider_name"] = provider

    # If tier was not pre-resolved, look it up from billing
    if "tier" not in orchestrator_input and orchestrator_input.get("user_id"):
        try:
            subscription = get_effective_subscription(user_id)
            plan = plan_capabilities(subscription.get("tier"))
        except Exception:
            logger.exception("Billing lookup failed for user=%s — defaulting to free", user_id)
            plan = plan_capabilities("free")

        tier = plan.get("tier", "free")
        orchestrator_input["tier"] = tier
        if tier in {"free", "demo"}:
            orchestrator_input.setdefault("cadence", plan.get("temporal_cadence", "seasonal"))
            max_hist = plan.get("max_history_years")
            if max_hist is not None:
                orchestrator_input.setdefault("max_history_years", max_hist)


@bp.event_grid_trigger(arg_name="event")
@bp.durable_client_input(client_name="client")
async def blob_trigger(
    event: func.EventGridEvent,
    client: df.DurableOrchestrationClient,
) -> None:
    """Event Grid BlobCreated → validate → start orchestration (§4.2)."""
    await _process_blob_trigger(event, client)


async def _process_blob_trigger(
    event: func.EventGridEvent,
    client: df.DurableOrchestrationClient,
) -> None:
    """Process a blob-created event after bindings have been resolved."""
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

    # Read submission ticket for user metadata enrichment
    # TODO: Add lifecycle policy or post-orchestration cleanup for
    # .tickets/ blobs to prevent indefinite accumulation.
    ticket = _read_submission_ticket(container_name, blob_name)
    if ticket:
        _enrich_from_ticket(orchestrator_input, ticket)

    instance_id = _derive_instance_id(blob_name, blob_event.correlation_id)
    await client.start_new(
        "treesight_orchestrator",
        instance_id=instance_id,
        client_input=orchestrator_input,
    )
    logger.info("Started orchestration instance=%s blob=%s", instance_id, blob_name)
