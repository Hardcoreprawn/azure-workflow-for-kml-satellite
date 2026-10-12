"""Event Grid blob trigger: validate uploaded KML and start orchestration.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import hashlib
import logging
import uuid
from pathlib import PurePosixPath

import azure.durable_functions as df
import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError

from treesight.constants import DEFAULT_INPUT_CONTAINER
from treesight.models.blob_event import BlobEvent
from treesight.security.billing import get_effective_subscription, plan_capabilities

from . import bp
from ._blob_url import _extract_blob_name, _extract_container, _validate_blob_event

logger = logging.getLogger(__name__)
ORCHESTRATION_MARKER_MAX_AGE_SECONDS = 300.0


def _is_api_managed_blob(blob_name: str) -> bool:
    """Return True for ``analysis/{uuid}.kml|kmz`` blobs submitted via the API.

    These blobs must have an associated submission ticket.  Storage-native
    uploads (any other path pattern) are allowed to proceed without one.
    """
    parts = PurePosixPath(blob_name).parts
    if len(parts) != 2 or parts[0] != "analysis":
        return False
    path = PurePosixPath(parts[-1])
    if path.suffix.lower() not in {".kml", ".kmz"}:
        return False
    stem = path.stem
    try:
        uuid.UUID(stem)
        return True
    except ValueError:
        return False


def _read_submission_ticket(container_name: str, blob_name: str) -> dict | None:
    """Read the ticket blob written by SWA API or submission endpoint.

    Returns ``None`` if no ticket is found (e.g. storage-native uploads).

    For API-managed ``analysis/{uuid}.kml|kmz`` blobs every read failure,
    including a missing ticket, is re-raised so that Event Grid retries rather
    than starting unattributed, unaccounted orchestration.

    For storage-native upload paths all exceptions are swallowed because no
    ticket is ever written for those blobs.
    """
    parts = PurePosixPath(blob_name).parts
    if not parts:
        return None
    stem = PurePosixPath(parts[-1]).stem
    ticket_path = f".tickets/{stem}.json"
    api_managed = _is_api_managed_blob(blob_name)
    try:
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        return storage.download_json(container_name, ticket_path)
    except Exception as exc:
        exc_name = type(exc).__name__
        if isinstance(exc, ResourceNotFoundError) and not api_managed:
            logger.debug("No ticket found for blob=%s (path=%s)", blob_name, ticket_path)
            return None
        logger.warning(
            "Ticket read failed for blob=%s (path=%s): %s",
            blob_name,
            ticket_path,
            exc_name,
            exc_info=True,
        )
        if api_managed:
            raise RuntimeError(
                f"Ticket read failed for API blob {blob_name!r}: {exc_name} — failing "
                "so Event Grid retries rather than starting unattributed orchestration"
            ) from exc
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

    # Add org_id for Stage 2 of #814 (org-pooled run accounting)
    org_id = ticket.get("org_id", "")
    if isinstance(org_id, str) and org_id:
        orchestrator_input["org_id"] = org_id

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

    # EUDR mode — only accept strict boolean
    eudr_mode = ticket.get("eudr_mode")
    if isinstance(eudr_mode, bool):
        orchestrator_input["eudr_mode"] = eudr_mode

    # EUDR imagery filter overrides
    imagery_filters = ticket.get("imagery_filters")
    if isinstance(imagery_filters, dict):
        orchestrator_input["imagery_filters"] = imagery_filters

    # If tier was not pre-resolved, look it up from billing
    if "tier" not in orchestrator_input and orchestrator_input.get("user_id"):
        _enrich_tier_from_billing(orchestrator_input, user_id)


def _enrich_tier_from_billing(orchestrator_input: dict, user_id: str) -> None:
    """Resolve tier/cadence/max_history from billing when not pre-set by submission."""
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


async def _start_or_reuse_orchestration(
    client: df.DurableOrchestrationClient,
    instance_id: str,
    orchestrator_input: dict,
) -> bool:
    """Start once for an instance ID, treating duplicate delivery as a no-op."""
    from treesight.storage.client import BlobStorageClient

    marker_path = _orchestration_marker_path(instance_id)
    marker = BlobStorageClient()
    claimed = marker.create_json_if_absent(
        DEFAULT_INPUT_CONTAINER,
        marker_path,
        {"instance_id": instance_id, "orchestrator": "treesight_orchestrator"},
    )
    if claimed is False:
        existing = await client.get_status(instance_id)
        if existing is not None:
            logger.info("Reused existing orchestration instance=%s", instance_id)
            return False
        if not marker.delete_blob_if_older_than(
            DEFAULT_INPUT_CONTAINER, marker_path, ORCHESTRATION_MARKER_MAX_AGE_SECONDS
        ):
            raise RuntimeError(f"Orchestration admission marker is pending for instance={instance_id}")
        if (
            marker.create_json_if_absent(
                DEFAULT_INPUT_CONTAINER,
                marker_path,
                {"instance_id": instance_id, "orchestrator": "treesight_orchestrator"},
            )
            is False
        ):
            raise RuntimeError(f"Orchestration admission marker was claimed concurrently for instance={instance_id}")
        logger.info("Reclaimed expired orchestration marker instance=%s", instance_id)
    try:
        await client.start_new(
            "treesight_orchestrator",
            instance_id=instance_id,
            client_input=orchestrator_input,
        )
    except Exception as start_error:
        try:
            existing = await client.get_status(instance_id)
        except Exception as status_error:
            raise start_error from status_error
        if existing is None:
            marker.delete_blob(DEFAULT_INPUT_CONTAINER, marker_path)
            raise start_error
        logger.info("Concurrent delivery reused orchestration instance=%s", instance_id)
        return False
    return True


def _orchestration_marker_path(instance_id: str) -> str:
    """Return a stable safe blob path for an orchestration admission marker."""
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
    return f".orchestration-starts/{digest}.json"


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
    started = await _start_or_reuse_orchestration(client, instance_id, orchestrator_input)
    if started:
        logger.info("Started orchestration instance=%s blob=%s", instance_id, blob_name)
