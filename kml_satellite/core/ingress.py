"""Thin ingress boundary helpers for Azure Functions entrypoints (Issue #61).

Centralises three cross-cutting transport concerns so that
``function_app.py`` contains only trigger bindings and handoff:

- **deserialize_activity_input** — normalises the JSON-string-or-dict
  payload that Durable Functions passes to activities (idempotent on
  replays).
- **build_orchestrator_input** — constructs the canonical
  ``OrchestratorInput`` dict from an Event Grid blob-created event,
  validating required fields and propagating correlation identifiers.
- **get_blob_service_client** — creates an ``azure.storage.blob``
  client from the ``AzureWebJobsStorage`` environment variable,
  failing fast with a structured error if unconfigured.

References:
    PID 7.4.5  (Explicit Over Implicit)
    Issue #61
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from kml_satellite.core.constants import MAX_KML_FILE_SIZE_BYTES
from kml_satellite.core.exceptions import ContractError

if TYPE_CHECKING:
    from azure.storage.blob import BlobServiceClient

logger = logging.getLogger("kml_satellite.core.ingress")


# ---------------------------------------------------------------------------
# Canonical orchestrator input schema
# ---------------------------------------------------------------------------


class OrchestratorInput(TypedDict):
    """Canonical payload for KML processing orchestrator starts.

    Built by ``build_orchestrator_input`` and consumed by the
    orchestrator function.  Matches the ``BlobEvent.to_dict()`` shape
    so that the orchestrator can work with either source.
    """

    blob_url: str
    container_name: str
    blob_name: str
    content_length: int
    content_type: str
    event_time: str
    correlation_id: str
    tenant_id: str
    output_container: str
    provider_name: NotRequired[str]
    provider_config: NotRequired[dict[str, Any] | None]
    imagery_filters: NotRequired[dict[str, Any] | None]


# ---------------------------------------------------------------------------
# Activity input deserialisation
# ---------------------------------------------------------------------------


def deserialize_activity_input(raw: str | dict[str, Any] | object) -> dict[str, Any]:
    """Normalise Durable Functions activity input to a plain dict.

    During initial execution the activity input arrives as a JSON
    string; on orchestrator replay it may already be a ``dict``.  This
    function handles both cases and raises ``ContractError`` for
    unexpected types.

    Args:
        raw: The ``activityInput`` value from the binding.

    Returns:
        Parsed dict payload.

    Raises:
        ContractError: If *raw* is neither a JSON string nor a dict.
    """
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            msg = f"Activity input is not valid JSON: {exc}"
            raise ContractError(msg, stage="ingress", code="INVALID_JSON") from exc
        if not isinstance(parsed, dict):
            msg = f"Activity input JSON must be an object, got {type(parsed).__name__}"
            raise ContractError(msg, stage="ingress", code="INVALID_INPUT_TYPE")
        return parsed
    if isinstance(raw, dict):
        return raw
    msg = f"Unexpected activity input type: {type(raw).__name__}"
    raise ContractError(msg, stage="ingress", code="INVALID_INPUT_TYPE")


# ---------------------------------------------------------------------------
# Canonical orchestrator input builder
# ---------------------------------------------------------------------------

_ORCHESTRATOR_REQUIRED_FIELDS = frozenset({"blob_url", "container_name", "blob_name"})


def build_orchestrator_input(
    event_data: dict[str, Any],
    *,
    event_time: str = "",
    event_id: str = "",
) -> OrchestratorInput:
    """Build a canonical ``OrchestratorInput`` from Event Grid data.

    Encapsulates ``BlobEvent`` construction, required-field validation,
    and correlation-ID propagation so that the trigger function stays
    minimal.

    Args:
        event_data: The ``event.get_json()`` body from an Event Grid event.
        event_time: ISO-8601 timestamp from ``event.event_time``.
        event_id: Event Grid event ID used as correlation identifier.

    Returns:
        Validated ``OrchestratorInput`` dict.

    Raises:
        ContractError: If the constructed input is missing required fields.
    """
    from kml_satellite.models.blob_event import BlobEvent

    blob_event = BlobEvent.from_event_grid_event(
        event_data,
        event_time=event_time or None,
        event_id=event_id,
    )

    payload: OrchestratorInput = blob_event.to_dict()  # type: ignore[assignment]

    # Validate required fields are non-empty
    missing = {k for k in _ORCHESTRATOR_REQUIRED_FIELDS if not str(payload.get(k, "")).strip()}
    if missing:
        msg = f"Orchestrator input missing required field(s): {', '.join(sorted(missing))}"
        raise ContractError(msg, stage="ingress", code="MISSING_ORCHESTRATOR_FIELDS")

    logger.debug(
        "Built orchestrator input | blob=%s | container=%s | correlation_id=%s",
        payload["blob_name"],
        payload["container_name"],
        payload["correlation_id"],
    )

    return payload


def build_and_validate_orchestrator_input(
    event_data: dict[str, Any],
    *,
    event_time: str = "",
    event_id: str = "",
) -> OrchestratorInput:
    """Build orchestrator input from Event Grid data and validate the blob (Issue #105).

    Combines ``build_orchestrator_input`` with zero-assumption blob validation:
    - File size within limits
    - File extension is .kml
    - Container name ends with -input
    - Empty blob check
    - Negative content_length check

    This is the recommended entrypoint for the blob trigger function.

    Args:
        event_data: The ``event.get_json()`` body from an Event Grid event.
        event_time: ISO-8601 timestamp from ``event.event_time``.
        event_id: Event Grid event ID used as correlation identifier.

    Returns:
        Validated ``OrchestratorInput`` dict (passed all validation checks).

    Raises:
        ContractError: If blob fails any validation check or input is malformed.
    """
    from kml_satellite.models.blob_event import BlobEvent

    # First, construct the BlobEvent for validation
    blob_event = BlobEvent.from_event_grid_event(
        event_data,
        event_time=event_time or None,
        event_id=event_id,
    )

    # Run ingress-boundary validation
    validate_blob_input(blob_event)

    # Then build the orchestrator input (which also performs its own validation)
    payload = build_orchestrator_input(
        event_data,
        event_time=event_time,
        event_id=event_id,
    )

    return payload


# ---------------------------------------------------------------------------
# Blob service client factory
# ---------------------------------------------------------------------------


def get_blob_service_client() -> BlobServiceClient:
    """Create a ``BlobServiceClient`` from the ``AzureWebJobsStorage`` env var.

    Returns:
        A ``BlobServiceClient`` instance.

    Raises:
        ContractError: If the environment variable is not set.
    """
    from azure.storage.blob import BlobServiceClient

    connection_string = os.environ.get("AzureWebJobsStorage", "")
    if not connection_string:
        msg = "AzureWebJobsStorage environment variable is not set"
        raise ContractError(msg, stage="ingress", code="MISSING_CONNECTION_STRING")

    return BlobServiceClient.from_connection_string(connection_string)


# ---------------------------------------------------------------------------
# Input validation (Issue #105 — zero-assumption handling per PID 7.4.1)
# ---------------------------------------------------------------------------

#: Maximum allowed KML file size in bytes (10 MiB).
#:
#: Rationale:
#: - PID Assumption A-6: AOIs do not exceed 10,000 hectares (100 km²)
#: - Real-world complex boundaries with extreme detail: ~100-500 KB
#: - 10 MiB provides safe margin while respecting Durable Functions history
#:   constraints (Azure Storage 1 MB entity max, orchestration history overflow)
#: - Risk mitigation for Issue #62 (payload offload to Blob Storage)
#: - Enforced at ingress by validate_blob_input() per Issue #105 (zero-assumption input handling)
MAX_KML_FILE_SIZE = MAX_KML_FILE_SIZE_BYTES


def validate_blob_input(blob_event: object) -> None:
    """Validate that a blob meets ingress requirements (Issue #105).

    Enforces zero-assumption input handling per PID 7.4.1:
    - File size is within limits (0 < size ≤ MAX_KML_FILE_SIZE)
    - Blob name has .kml extension
    - Container name ends with -input
    - Blob name and container name are non-empty

    Args:
        blob_event: Object to validate as a BlobEvent.

    Raises:
        ContractError: If the blob does not pass validation.
    """
    from kml_satellite.models.blob_event import BlobEvent

    if not isinstance(blob_event, BlobEvent):
        msg = f"Expected BlobEvent, got {type(blob_event).__name__}"
        raise ContractError(msg, stage="ingress", code="INVALID_BLOB_TYPE")

    # Validate blob name is non-empty and has .kml extension
    blob_name = str(blob_event.blob_name).strip()
    if not blob_name:
        msg = "Blob name is empty"
        raise ContractError(
            msg,
            stage="ingress",
            code="EMPTY_BLOB_NAME",
        )

    if not blob_name.lower().endswith(".kml"):
        msg = f"Blob must have .kml extension: {blob_name}"
        raise ContractError(
            msg,
            stage="ingress",
            code="INVALID_FILE_TYPE",
        )

    # Validate container name is non-empty and ends with -input
    container_name = str(blob_event.container_name).strip()
    if not container_name:
        msg = "Container name is empty"
        raise ContractError(
            msg,
            stage="ingress",
            code="EMPTY_CONTAINER_NAME",
        )

    if not container_name.endswith("-input"):
        msg = f"Blob must be in a container ending with -input, got: {container_name}"
        raise ContractError(
            msg,
            stage="ingress",
            code="INVALID_CONTAINER",
        )

    # Validate content_length is valid
    content_length = blob_event.content_length
    if content_length < 0:
        msg = f"Content length cannot be negative: {content_length}"
        raise ContractError(
            msg,
            stage="ingress",
            code="INVALID_CONTENT_LENGTH",
        )

    if content_length == 0:
        msg = f"Blob is empty: {blob_name}"
        raise ContractError(
            msg,
            stage="ingress",
            code="EMPTY_BLOB",
        )

    if content_length > MAX_KML_FILE_SIZE:
        msg = (
            f"Blob exceeds maximum size ({blob_name}): "
            f"{content_length} bytes > {MAX_KML_FILE_SIZE} bytes"
        )
        raise ContractError(
            msg,
            stage="ingress",
            code="FILE_TOO_LARGE",
        )
