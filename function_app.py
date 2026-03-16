"""Azure Functions entry point — KML Satellite Imagery Pipeline.

This module registers all Azure Functions (triggers, orchestrators, activities)
using the Python v2 programming model.

All business logic lives in the kml_satellite package. This file is purely
the wiring layer between Azure Functions bindings and application code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import azure.durable_functions as df
import azure.functions as func

from kml_satellite.core.config import PipelineConfig, config_get_int
from kml_satellite.core.constants import DEFAULT_OUTPUT_CONTAINER, PIPELINE_PAYLOADS_CONTAINER
from kml_satellite.core.exceptions import ContractError
from kml_satellite.core.ingress import (
    build_and_validate_orchestrator_input,
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


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_API_CONTRACT_VERSION = "2026-03-15.1"
_DEMO_VALET_TOKEN_TTL_SECONDS = 24 * 60 * 60
_DEMO_VALET_TOKEN_MAX_USES = 3


def _isoformat_or_empty(value: object) -> str:
    """Serialize datetime-like values for JSON responses."""
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def _extract_unique_paths(results: object, *candidate_keys: str) -> list[str]:
    """Collect unique blob paths from a list of activity result dicts."""
    if not isinstance(results, list):
        return []

    paths: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        for key in candidate_keys:
            value = item.get(key)
            if isinstance(value, str) and value and value not in paths:
                paths.append(value)
    return paths


def _summarize_orchestrator_output(output: object) -> dict[str, object] | None:
    """Return a compact, diagnostics-friendly view of orchestration output."""
    if not isinstance(output, dict):
        return None

    metadata_results = output.get("metadata_results")
    download_results = output.get("download_results")
    post_process_results = output.get("post_process_results")

    return {
        "status": str(output.get("status", "")),
        "message": str(output.get("message", "")),
        "blobName": str(output.get("blob_name", "")),
        "featureCount": int(output.get("feature_count", 0) or 0),
        "metadataCount": int(output.get("metadata_count", 0) or 0),
        "imageryReady": int(output.get("imagery_ready", 0) or 0),
        "imageryFailed": int(output.get("imagery_failed", 0) or 0),
        "downloadsCompleted": int(output.get("downloads_completed", 0) or 0),
        "postProcessCompleted": int(output.get("post_process_completed", 0) or 0),
        "artifacts": {
            "metadataPaths": _extract_unique_paths(metadata_results, "metadata_path"),
            "rawImageryPaths": _extract_unique_paths(
                download_results,
                "blob_path",
                "canonical_blob_path",
                "source_blob_path",
            ),
            "clippedImageryPaths": _extract_unique_paths(
                post_process_results,
                "clipped_blob_path",
                "output_path",
            ),
        },
    }


def _build_orchestrator_diagnostics_payload(status: object) -> dict[str, object]:
    """Build a direct JSON payload for anonymous orchestration diagnostics."""
    payload: dict[str, object] = {
        "instanceId": str(getattr(status, "instance_id", "")),
        "name": str(getattr(status, "name", "")),
        "runtimeStatus": str(getattr(status, "runtime_status", "")),
        "createdTime": _isoformat_or_empty(getattr(status, "created_time", None)),
        "lastUpdatedTime": _isoformat_or_empty(getattr(status, "last_updated_time", None)),
        "customStatus": getattr(status, "custom_status", None),
    }

    output_summary = _summarize_orchestrator_output(getattr(status, "output", None))
    if output_summary is not None:
        payload["output"] = output_summary

    return payload


def _sanitize_marketing_field(value: object, *, max_length: int = 2000) -> str:
    """Return a trimmed string field suitable for persistence and logging."""
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _get_demo_valet_secret() -> bytes:
    """Return the HMAC secret for signed valet tokens."""
    secret = os.getenv("DEMO_VALET_TOKEN_SECRET", "").strip()
    if not secret:
        raise RuntimeError("DEMO_VALET_TOKEN_SECRET is not configured")
    return secret.encode("utf-8")


def _base64url_encode_bytes(value: bytes) -> str:
    """Encode bytes without `=` padding for URL-safe tokens."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode_bytes(value: str) -> bytes:
    """Decode a URL-safe base64 segment with optional stripped padding."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _hash_demo_recipient(email: str) -> str:
    """Return a stable hash for the token-bound recipient."""
    normalized = email.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _get_demo_valet_ttl_seconds() -> int:
    """Return the configured valet token TTL in seconds."""
    value = os.getenv("DEMO_VALET_TOKEN_TTL_SECONDS", str(_DEMO_VALET_TOKEN_TTL_SECONDS))
    try:
        parsed = int(value)
    except ValueError:
        return _DEMO_VALET_TOKEN_TTL_SECONDS
    return parsed if parsed > 0 else _DEMO_VALET_TOKEN_TTL_SECONDS


def _get_demo_valet_max_uses() -> int:
    """Return the configured per-token replay limit."""
    value = os.getenv("DEMO_VALET_TOKEN_MAX_USES", str(_DEMO_VALET_TOKEN_MAX_USES))
    try:
        parsed = int(value)
    except ValueError:
        return _DEMO_VALET_TOKEN_MAX_USES
    return parsed if parsed > 0 else _DEMO_VALET_TOKEN_MAX_USES


def _mint_demo_valet_token(
    *,
    submission_id: str,
    submission_blob_name: str,
    artifact_path: str,
    recipient_email: str,
    expires_at: datetime | None = None,
    nonce: str | None = None,
    max_uses: int | None = None,
    output_container: str = DEFAULT_OUTPUT_CONTAINER,
) -> str:
    """Create a signed valet token scoped to a single demo artifact."""
    now = datetime.now(UTC)
    if expires_at is None:
        expires_at = now + timedelta(seconds=_get_demo_valet_ttl_seconds())

    claims = {
        "submission_id": submission_id,
        "submission_blob_name": submission_blob_name,
        "artifact_path": artifact_path,
        "recipient_hash": _hash_demo_recipient(recipient_email),
        "exp": int(expires_at.timestamp()),
        "nonce": nonce or uuid4().hex,
        "max_uses": max_uses or _get_demo_valet_max_uses(),
        "output_container": output_container,
    }

    payload = _base64url_encode_bytes(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _base64url_encode_bytes(
        hmac.new(_get_demo_valet_secret(), payload.encode("utf-8"), hashlib.sha256).digest()
    )
    return f"{payload}.{signature}"


def _verify_demo_valet_token(
    token: str,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    """Verify token signature and expiry without exposing internal failure detail."""
    try:
        payload_segment, signature_segment = token.split(".", 1)
    except ValueError:
        return None, "invalid"

    try:
        expected_signature = _base64url_encode_bytes(
            hmac.new(
                _get_demo_valet_secret(),
                payload_segment.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )
    except RuntimeError:
        return None, "misconfigured"

    if not hmac.compare_digest(signature_segment, expected_signature):
        return None, "invalid"

    try:
        claims = json.loads(_base64url_decode_bytes(payload_segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "invalid"

    if not isinstance(claims, dict):
        return None, "invalid"

    current_time = now or datetime.now(UTC)
    expires_at = claims.get("exp")
    if not isinstance(expires_at, int):
        return None, "invalid"
    if current_time.timestamp() > expires_at:
        return None, "expired"

    return claims, None


def _extract_demo_artifact_paths(submission: object) -> list[str]:
    """Collect unique artifact paths from a persisted demo submission record."""
    if not isinstance(submission, dict):
        return []

    artifacts = submission.get("artifacts")
    if not isinstance(artifacts, dict):
        return []

    paths: list[str] = []
    for key in ("metadataPaths", "rawImageryPaths", "clippedImageryPaths"):
        values = artifacts.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value and value not in paths:
                paths.append(value)
    return paths


def _load_json_blob(
    blob_service: Any, *, container: str, blob_name: str
) -> dict[str, object] | None:
    """Load a JSON blob from storage or return None when it does not exist."""
    try:
        blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
        payload = blob_client.download_blob().readall()
    except Exception:
        return None

    try:
        decoded = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        data = json.loads(decoded)
    except (UnicodeDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    return data


def _find_demo_submission_blob_name(blob_service: Any, submission_id: str) -> str | None:
    """Locate a persisted demo submission record by scanning the payload prefix."""
    try:
        container_client = blob_service.get_container_client(PIPELINE_PAYLOADS_CONTAINER)
        blobs = container_client.list_blobs(name_starts_with="demo-submissions/")
    except Exception:
        return None

    suffix = f"/{submission_id}.json"
    for blob in blobs:
        name = getattr(blob, "name", "")
        if isinstance(name, str) and name.endswith(suffix):
            return name
    return None


def _get_demo_token_usage_blob_name(nonce: str) -> str:
    """Return the blob name used to track token replay usage."""
    return f"demo-valet-usage/{nonce}.json"


def _get_demo_token_usage_count(blob_service: Any, nonce: str) -> int:
    """Return the current usage count for a replay-limited token."""
    payload = _load_json_blob(
        blob_service,
        container=PIPELINE_PAYLOADS_CONTAINER,
        blob_name=_get_demo_token_usage_blob_name(nonce),
    )
    if not payload:
        return 0
    count = payload.get("count", 0)
    return count if isinstance(count, int) and count >= 0 else 0


def _consume_demo_token_use(blob_service: Any, claims: dict[str, object]) -> bool:
    """Increment the replay counter and return False once the max use count is exceeded."""
    nonce = claims.get("nonce")
    max_uses = claims.get("max_uses")
    if not isinstance(nonce, str) or not isinstance(max_uses, int):
        return False

    usage_count = _get_demo_token_usage_count(blob_service, nonce)
    if usage_count >= max_uses:
        return False

    blob_service.get_blob_client(
        container=PIPELINE_PAYLOADS_CONTAINER,
        blob=_get_demo_token_usage_blob_name(nonce),
    ).upload_blob(
        json.dumps(
            {
                "nonce": nonce,
                "count": usage_count + 1,
                "last_used_at": datetime.now(UTC).isoformat(),
            }
        ),
        overwrite=True,
    )
    return True


def _guess_artifact_mimetype(blob_path: str) -> str:
    """Return a reasonable content type for proxied artifact downloads."""
    guessed, _ = mimetypes.guess_type(blob_path)
    return guessed or "application/octet-stream"


def _load_demo_submission_for_claims(
    blob_service: Any, claims: dict[str, object]
) -> tuple[dict[str, object] | None, str | None]:
    """Resolve the persisted submission record referenced by token claims."""
    submission_blob_name = claims.get("submission_blob_name")
    if not isinstance(submission_blob_name, str) or not submission_blob_name:
        return None, None

    submission = _load_json_blob(
        blob_service,
        container=PIPELINE_PAYLOADS_CONTAINER,
        blob_name=submission_blob_name,
    )
    return submission, submission_blob_name


def _artifact_is_authorized(submission: dict[str, object], claims: dict[str, object]) -> bool:
    """Check that the token still matches the persisted submission record."""
    artifact_path = claims.get("artifact_path")
    recipient_hash = claims.get("recipient_hash")
    if not isinstance(artifact_path, str) or not isinstance(recipient_hash, str):
        return False

    email = submission.get("email")
    if not isinstance(email, str) or _hash_demo_recipient(email) != recipient_hash:
        return False

    return artifact_path in _extract_demo_artifact_paths(submission)


def _validate_marketing_interest_payload(
    payload: object,
) -> tuple[dict[str, str] | None, str | None]:
    """Validate and normalize incoming contact form payload."""
    if not isinstance(payload, dict):
        return None, "Request body must be a JSON object"

    email = _sanitize_marketing_field(payload.get("email"), max_length=320).lower()
    organization = _sanitize_marketing_field(payload.get("organization"), max_length=256)
    use_case = _sanitize_marketing_field(payload.get("use_case"), max_length=4000)
    aoi_size = _sanitize_marketing_field(payload.get("aoi_size"), max_length=64)

    if not email:
        return None, "Field 'email' is required"
    if not _EMAIL_PATTERN.match(email):
        return None, "Field 'email' must be a valid email address"
    if not organization:
        return None, "Field 'organization' is required"
    if not use_case:
        return None, "Field 'use_case' is required"

    return {
        "email": email,
        "organization": organization,
        "use_case": use_case,
        "aoi_size": aoi_size,
    }, None


def _validate_demo_submission_payload(
    payload: object,
) -> tuple[dict[str, str] | None, str | None]:
    """Validate and normalize incoming demo submission payload."""
    if not isinstance(payload, dict):
        return None, "Request body must be a JSON object"

    email = _sanitize_marketing_field(payload.get("email"), max_length=320).lower()
    kml = _sanitize_marketing_field(payload.get("kml"), max_length=200000)

    if not email:
        return None, "Field 'email' is required"
    if not _EMAIL_PATTERN.match(email):
        return None, "Field 'email' must be a valid email address"
    if not kml:
        return None, "Field 'kml' is required"

    return {
        "email": email,
        "kml": kml,
    }, None


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
    # Build and validate orchestrator input from the Event Grid event.
    try:
        orchestrator_input = build_and_validate_orchestrator_input(
            event.get_json(),
            event_time=event.event_time.isoformat() if event.event_time else "",
            event_id=event.id or "",
        )
    except ContractError as e:
        logger.warning(
            "Rejecting malformed Event Grid event: %s",
            str(e),
        )
        return

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
    if not container.endswith("-input"):
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
        Dict describing the final outcome from ``poll_until_ready``.
    """
    from kml_satellite.orchestrators.polling import poll_until_ready

    sub_input: dict[str, object] = context.get_input() or {}
    acquisition = sub_input.get("acquisition", {})
    if not isinstance(acquisition, dict):
        acquisition = {}

    return poll_until_ready(
        context,
        acquisition,
        poll_interval=config_get_int(sub_input, "poll_interval", 30),
        poll_timeout=config_get_int(sub_input, "poll_timeout", 1800),
        max_retries=config_get_int(sub_input, "max_retries", 3),
        retry_base=config_get_int(sub_input, "retry_base", 5),
        instance_id=str(sub_input.get("instance_id", "")),
    )


# ---------------------------------------------------------------------------
# HTTP: Orchestrator Status Endpoint (convenience for local debugging)
# ---------------------------------------------------------------------------


@app.function_name("orchestrator_status")
@app.route(
    route="orchestrator/{instance_id}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@app.durable_client_input(client_name="client")
async def orchestrator_status(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """Return the status of a specific orchestrator instance.

    This endpoint is intentionally anonymous for operational diagnostics:
    deploy smoke checks and responders can inspect Durable instance state
    and output artifact paths without requiring key bootstrap first.
    """
    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return func.HttpResponse("Missing instance_id", status_code=400)

    status = await client.get_status(instance_id)
    if not status:
        return func.HttpResponse("Instance not found", status_code=404)

    response_body = json.dumps(_build_orchestrator_diagnostics_payload(status))
    return func.HttpResponse(response_body, status_code=200, mimetype="application/json")


# ---------------------------------------------------------------------------
# HTTP: Health Check Endpoints
# ---------------------------------------------------------------------------


@app.function_name("health_liveness")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health_liveness(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness probe — validates that function app can start.

    Fast, minimal check — only validates configuration loads successfully.
    Should respond in <100ms under normal conditions.

    Returns:
        200 OK if configuration is valid and required env vars are present.
        500 if config validation fails (e.g. missing env vars).
    """
    _ = req
    try:
        # Validate all required environment variables and configuration.
        # This will raise ConfigValidationError if anything is missing.
        _ = PipelineConfig.from_env()

        response_body = json.dumps({"status": "alive", "service": "kml-satellite"})
        return func.HttpResponse(response_body, status_code=200, mimetype="application/json")
    except Exception:
        # Config validation failed — app cannot start.
        logger.exception("Health check (liveness) failed")
        response_body = json.dumps(
            {
                "status": "dead",
                "error": "service configuration unavailable",
            }
        )
        return func.HttpResponse(response_body, status_code=500, mimetype="application/json")


@app.function_name("health_readiness")
@app.route(route="readiness", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health_readiness(req: func.HttpRequest) -> func.HttpResponse:
    """Readiness probe — validates all dependencies are available.

    Checks:
    - Configuration loads successfully
    - Blob Storage (AzureWebJobsStorage) is reachable
    - Key Vault (if configured) is reachable

    Container orchestrators use this to decide whether to route traffic.
    Returns 503 if any dependency is unavailable.

    Returns:
        200 OK if all dependencies are ready.
        503 Service Unavailable if any dependency fails.
    """
    _ = req
    dependencies_ok = True
    dependency_status: dict[str, object] = {}

    # 1. Validate configuration.
    try:
        _ = PipelineConfig.from_env()
        dependency_status["config"] = "ok"
    except Exception:
        logger.exception("Config validation failed (readiness)")
        dependency_status["config"] = "error"
        dependencies_ok = False

    # 2. Verify Blob Storage connectivity.
    try:
        if dependencies_ok:  # Only check if config is valid.
            _ = get_blob_service_client()
            dependency_status["blob_storage"] = "ok"
    except Exception:
        logger.exception("Blob Storage connectivity check failed (readiness)")
        dependency_status["blob_storage"] = "error"
        dependencies_ok = False

    # Build response.
    status_code = 200 if dependencies_ok else 503
    response_body = json.dumps(
        {
            "status": "ready" if dependencies_ok else "not_ready",
            "dependencies": dependency_status,
        }
    )

    logger.info(
        "Readiness probe: %s | dependencies=%s",
        "ready" if dependencies_ok else "not_ready",
        dependency_status,
    )

    return func.HttpResponse(response_body, status_code=status_code, mimetype="application/json")


@app.function_name("api_contract")
@app.route(route="api-contract", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def api_contract(_req: func.HttpRequest) -> func.HttpResponse:
    """Publish backend API contract version for frontend compatibility gating."""
    # _req is intentionally unused; endpoint is static contract metadata.
    response = json.dumps(
        {
            "api_version": _API_CONTRACT_VERSION,
            "supported_routes": [
                "/api/health",
                "/api/readiness",
                "/api/contact-form",
                "/api/demo-submit",
                "/api/demo-results-token",
                "/api/demo-results",
                "/api/demo-results/download",
                "/api/orchestrator/{instance_id}",
            ],
        }
    )
    return func.HttpResponse(response, status_code=200, mimetype="application/json")


@app.function_name("marketing_interest")
@app.route(
    route="contact-form",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
async def marketing_interest(req: func.HttpRequest) -> func.HttpResponse:
    """Capture early-access requests from the marketing website (#154)."""
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204)

    try:
        payload = req.get_json()
    except ValueError:
        response = json.dumps({"error": "Request body must be valid JSON"})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    normalized, validation_error = _validate_marketing_interest_payload(payload)
    if validation_error:
        response = json.dumps({"error": validation_error})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    assert normalized is not None  # Type narrowing: validation guarantees normalized payload.

    submitted_at = datetime.now(UTC).isoformat()
    submission_id = uuid4().hex
    source_ip = _sanitize_marketing_field(
        req.headers.get("x-forwarded-for") or req.headers.get("x-client-ip"),
        max_length=256,
    )
    user_agent = _sanitize_marketing_field(req.headers.get("user-agent"), max_length=512)

    submission = {
        "submission_id": submission_id,
        "submitted_at": submitted_at,
        "source_ip": source_ip,
        "user_agent": user_agent,
        **normalized,
    }

    blob_name = f"marketing-interest/{submitted_at[:10]}/{submission_id}.json"

    try:
        blob_service = get_blob_service_client()
        container_client = blob_service.get_container_client(PIPELINE_PAYLOADS_CONTAINER)
        container_client.create_container()
    except Exception:
        # Container likely already exists; continue to upload.
        pass

    try:
        blob_service = get_blob_service_client()
        blob_client = blob_service.get_blob_client(
            container=PIPELINE_PAYLOADS_CONTAINER,
            blob=blob_name,
        )
        blob_client.upload_blob(json.dumps(submission), overwrite=False)
    except Exception as exc:
        logger.exception("Failed to persist marketing interest submission: %s", str(exc))
        response = json.dumps({"error": "Failed to capture request. Please try again."})
        return func.HttpResponse(response, status_code=500, mimetype="application/json")

    logger.info(
        "Marketing interest captured | submission_id=%s | organization=%s",
        submission_id,
        normalized["organization"],
    )

    response = json.dumps(
        {
            "status": "accepted",
            "submission_id": submission_id,
            "message": "Interest request received",
        }
    )
    return func.HttpResponse(response, status_code=202, mimetype="application/json")


@app.function_name("demo_submission")
@app.route(
    route="demo-submit",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
async def demo_submission(req: func.HttpRequest) -> func.HttpResponse:
    """Capture demo requests with email + KML payload for async processing delivery."""
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204)

    try:
        payload = req.get_json()
    except ValueError:
        response = json.dumps({"error": "Request body must be valid JSON"})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    normalized, validation_error = _validate_demo_submission_payload(payload)
    if validation_error:
        response = json.dumps({"error": validation_error})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    assert normalized is not None  # Type narrowing: validation guarantees normalized payload.

    submitted_at = datetime.now(UTC).isoformat()
    submission_id = uuid4().hex
    source_ip = _sanitize_marketing_field(
        req.headers.get("x-forwarded-for") or req.headers.get("x-client-ip"),
        max_length=256,
    )
    user_agent = _sanitize_marketing_field(req.headers.get("user-agent"), max_length=512)

    submission = {
        "submission_id": submission_id,
        "submitted_at": submitted_at,
        "source_ip": source_ip,
        "user_agent": user_agent,
        "status": "pending",
        **normalized,
    }

    blob_name = f"demo-submissions/{submitted_at[:10]}/{submission_id}.json"

    try:
        blob_service = get_blob_service_client()
        container_client = blob_service.get_container_client(PIPELINE_PAYLOADS_CONTAINER)
        container_client.create_container()
    except Exception:
        # Container likely already exists; continue to upload.
        pass

    try:
        blob_service = get_blob_service_client()
        blob_client = blob_service.get_blob_client(
            container=PIPELINE_PAYLOADS_CONTAINER,
            blob=blob_name,
        )
        blob_client.upload_blob(json.dumps(submission), overwrite=False)
    except Exception as exc:
        logger.exception("Failed to persist demo submission: %s", str(exc))
        response = json.dumps({"error": "Failed to capture demo request. Please try again."})
        return func.HttpResponse(response, status_code=500, mimetype="application/json")

    logger.info("Demo submission captured | submission_id=%s", submission_id)

    response = json.dumps(
        {
            "status": "accepted",
            "submission_id": submission_id,
            "message": "Demo request received",
        }
    )
    return func.HttpResponse(response, status_code=202, mimetype="application/json")


@app.function_name("demo_result_token")
@app.route(
    route="demo-results-token",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION,
)
async def demo_result_token(req: func.HttpRequest) -> func.HttpResponse:
    """Issue a short-lived valet token scoped to one demo artifact."""
    try:
        payload = req.get_json()
    except ValueError:
        response = json.dumps({"error": "Request body must be valid JSON"})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    if not isinstance(payload, dict):
        response = json.dumps({"error": "Request body must be a JSON object"})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    submission_id = _sanitize_marketing_field(payload.get("submission_id"), max_length=128)
    artifact_path = _sanitize_marketing_field(payload.get("artifact_path"), max_length=1024)
    if not submission_id or not artifact_path:
        response = json.dumps({"error": "Fields 'submission_id' and 'artifact_path' are required"})
        return func.HttpResponse(response, status_code=400, mimetype="application/json")

    try:
        blob_service = get_blob_service_client()
        submission_blob_name = _find_demo_submission_blob_name(blob_service, submission_id)
        if submission_blob_name is None:
            return func.HttpResponse(status_code=404)

        submission = _load_json_blob(
            blob_service,
            container=PIPELINE_PAYLOADS_CONTAINER,
            blob_name=submission_blob_name,
        )
        if not submission or artifact_path not in _extract_demo_artifact_paths(submission):
            return func.HttpResponse(status_code=404)

        email = submission.get("email")
        output_container = submission.get("output_container", DEFAULT_OUTPUT_CONTAINER)
        if not isinstance(email, str) or not email:
            return func.HttpResponse(status_code=409)
        if not isinstance(output_container, str) or not output_container:
            output_container = DEFAULT_OUTPUT_CONTAINER

        token = _mint_demo_valet_token(
            submission_id=submission_id,
            submission_blob_name=submission_blob_name,
            artifact_path=artifact_path,
            recipient_email=email,
            output_container=output_container,
        )
    except RuntimeError:
        logger.exception("Demo valet token secret is not configured")
        return func.HttpResponse(status_code=503)
    except Exception:
        logger.exception(
            "Failed to issue demo result token | submission_id=%s | artifact_path=%s",
            submission_id,
            artifact_path,
        )
        return func.HttpResponse(status_code=500)

    response = json.dumps(
        {
            "token": token,
            "results_url": f"/api/demo-results?token={token}",
            "download_url": f"/api/demo-results/download?token={token}",
        }
    )
    return func.HttpResponse(response, status_code=200, mimetype="application/json")


@app.function_name("demo_results")
@app.route(
    route="demo-results",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
async def demo_results(req: func.HttpRequest) -> func.HttpResponse:
    """Validate a valet token and expose only the intended demo artifact metadata."""
    token = _sanitize_marketing_field(getattr(req, "params", {}).get("token"), max_length=8192)
    if not token:
        return func.HttpResponse(status_code=401)

    claims, error = _verify_demo_valet_token(token)
    if error == "expired":
        return func.HttpResponse(status_code=403)
    if error == "misconfigured":
        return func.HttpResponse(status_code=503)
    if error or claims is None:
        return func.HttpResponse(status_code=401)

    try:
        blob_service = get_blob_service_client()
        submission, _ = _load_demo_submission_for_claims(blob_service, claims)
        if not submission or not _artifact_is_authorized(submission, claims):
            return func.HttpResponse(status_code=403)

        artifact_path = str(claims["artifact_path"])
        response = json.dumps(
            {
                "submission_id": str(claims["submission_id"]),
                "status": str(submission.get("status", "unknown")),
                "artifact": {
                    "path": artifact_path,
                    "kind": Path(artifact_path).suffix.lower().lstrip(".") or "blob",
                    "download_url": f"/api/demo-results/download?token={token}",
                },
            }
        )
        return func.HttpResponse(response, status_code=200, mimetype="application/json")
    except Exception:
        logger.exception("Failed to resolve demo results for a valet token")
        return func.HttpResponse(status_code=500)


@app.function_name("demo_result_download")
@app.route(
    route="demo-results/download",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
async def demo_result_download(req: func.HttpRequest) -> func.HttpResponse:
    """Proxy a demo artifact download after validating a signed valet token."""
    token = _sanitize_marketing_field(getattr(req, "params", {}).get("token"), max_length=8192)
    if not token:
        return func.HttpResponse(status_code=401)

    claims, error = _verify_demo_valet_token(token)
    if error == "expired":
        return func.HttpResponse(status_code=403)
    if error == "misconfigured":
        return func.HttpResponse(status_code=503)
    if error or claims is None:
        return func.HttpResponse(status_code=401)

    try:
        blob_service = get_blob_service_client()
        submission, _ = _load_demo_submission_for_claims(blob_service, claims)
        if not submission or not _artifact_is_authorized(submission, claims):
            return func.HttpResponse(status_code=403)
        if not _consume_demo_token_use(blob_service, claims):
            return func.HttpResponse(status_code=403)

        artifact_path = str(claims["artifact_path"])
        output_container = claims.get("output_container", DEFAULT_OUTPUT_CONTAINER)
        if not isinstance(output_container, str) or not output_container:
            output_container = DEFAULT_OUTPUT_CONTAINER

        blob_client = blob_service.get_blob_client(container=output_container, blob=artifact_path)
        payload = blob_client.download_blob().readall()
        try:
            content_type = blob_client.get_blob_properties().content_settings.content_type
        except Exception:
            content_type = _guess_artifact_mimetype(artifact_path)

        headers = {
            "Content-Disposition": f'attachment; filename="{Path(artifact_path).name}"',
        }
        return func.HttpResponse(
            body=payload,
            status_code=200,
            mimetype=content_type or _guess_artifact_mimetype(artifact_path),
            headers=headers,
        )
    except FileNotFoundError:
        return func.HttpResponse(status_code=404)
    except Exception:
        logger.exception("Failed to proxy demo artifact download")
        return func.HttpResponse(status_code=500)


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
    source_kml_container = str(payload.get("source_kml_container", ""))
    source_kml_blob_name = str(payload.get("source_kml_blob_name", ""))

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
        source_kml_container=source_kml_container,
        source_kml_blob_name=source_kml_blob_name,
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
    output_container = str(payload.get("output_container", DEFAULT_OUTPUT_CONTAINER))

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
    output_container = str(payload.get("output_container", DEFAULT_OUTPUT_CONTAINER))

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
