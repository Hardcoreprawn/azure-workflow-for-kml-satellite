"""Shared helpers for blueprint HTTP endpoints."""

import json
import logging
import os
import re
from functools import wraps
from typing import Any

import azure.functions as func

from treesight.security.auth import auth_enabled, get_user_id, validate_token

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FIELD_LEN = 2000

# Allowed CORS origins — production SWA + local dev
_ALLOWED_ORIGINS: set[str] = {
    "https://polite-glacier-0d6885003.4.azurestaticapps.net",
    "https://canopex.hrdcrprwn.com",
    "http://localhost:4280",
    "http://localhost:1111",
}

# Allow override via env var (comma-separated) for custom domains.
# Only https:// origins are accepted to prevent open CORS misconfiguration.
_extra = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _extra:
    for origin in _extra.split(","):
        origin = origin.strip()
        if origin and origin.startswith("https://"):
            _ALLOWED_ORIGINS.add(origin)


def _cors_origin(req: func.HttpRequest) -> str:
    """Return the request Origin if it is in the allowed set, else empty."""
    origin = req.headers.get("Origin", "")
    return origin if origin in _ALLOWED_ORIGINS else ""


def sanitise(value: str) -> str:
    """Strip and truncate a user-supplied string field."""
    return value.strip()[:MAX_FIELD_LEN] if isinstance(value, str) else ""


def error_response(
    status: int, message: str, *, req: func.HttpRequest | None = None
) -> func.HttpResponse:
    """Return a JSON error response with the given status code."""
    origin = _cors_origin(req) if req else ""
    headers: dict[str, str] = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
        headers=headers or None,
    )


def cors_headers(req: func.HttpRequest) -> dict[str, str]:
    """Build CORS response headers scoped to the request Origin."""
    origin = _cors_origin(req)
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }


def cors_preflight(req: func.HttpRequest) -> func.HttpResponse:
    """Return a 204 CORS preflight response."""
    return func.HttpResponse(status_code=204, headers=cors_headers(req))


def require_auth(fn):
    """Decorator that validates CIAM JWT on the request.

    When CIAM is not configured the request passes through unauthenticated
    (graceful degradation for local dev / pre-auth deployments).

    On success, the original function receives two extra keyword arguments:
        auth_claims  — decoded JWT claims dict
        user_id      — subject identifier string
    """

    @wraps(fn)
    def wrapper(req: func.HttpRequest) -> func.HttpResponse:
        if req.method == "OPTIONS":
            return cors_preflight(req)

        if not auth_enabled():
            # Auth not configured — allow through without auth
            return fn(req, auth_claims={}, user_id="anonymous")

        auth_header = req.headers.get("Authorization", "")
        try:
            claims = validate_token(auth_header)
        except ValueError as exc:
            return error_response(401, str(exc), req=req)

        return fn(req, auth_claims=claims, user_id=get_user_id(claims))

    # @wraps copies __wrapped__, which makes inspect.signature() expose
    # the inner function's extra parameters (auth_claims, user_id).
    # The Azure Functions worker treats every parameter as a binding;
    # these are not bindings, so we remove __wrapped__ to hide them.
    del wrapper.__wrapped__
    return wrapper


def check_auth(req: func.HttpRequest) -> tuple:
    """Validate CIAM JWT and return (claims, user_id).

    Returns ({}, "anonymous") when CIAM is not configured.
    Raises ValueError with a user-safe message on auth failure.
    """
    if not auth_enabled():
        return {}, "anonymous"
    auth_header = req.headers.get("Authorization", "")
    claims = validate_token(auth_header)
    return claims, get_user_id(claims)


def submit_contact(
    req: func.HttpRequest,
    body: dict,
    source: str,
    *,
    extra_fields: dict | None = None,
) -> func.HttpResponse:
    """Shared contact-submission logic: rate-limit, validate, store, notify.

    Used by both the marketing contact form and the billing interest endpoint.
    """
    import uuid
    from datetime import UTC, datetime

    from treesight.constants import PIPELINE_PAYLOADS_CONTAINER
    from treesight.email import send_contact_notification
    from treesight.security.rate_limit import form_limiter, get_client_ip
    from treesight.storage.client import BlobStorageClient

    if not form_limiter.is_allowed(get_client_ip(req)):
        return error_response(429, "Rate limit exceeded \u2014 try again later", req=req)

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object", req=req)

    email = sanitise(body.get("email", ""))
    if not email or not EMAIL_RE.match(email):
        return error_response(400, "Valid email is required", req=req)

    organization = sanitise(body.get("organization", ""))

    submission_id = str(uuid.uuid4())
    record = {
        "submission_id": submission_id,
        "email": email,
        "organization": organization,
        "submitted_at": datetime.now(UTC).isoformat(),
        "source": source,
    }
    if extra_fields:
        record.update(extra_fields)

    storage = BlobStorageClient()
    storage.upload_json(
        PIPELINE_PAYLOADS_CONTAINER,
        f"contact-submissions/{submission_id}.json",
        record,
    )

    send_contact_notification(record)

    return func.HttpResponse(
        json.dumps({"status": "received", "submission_id": submission_id}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


async def fetch_enrichment_manifest(
    req: func.HttpRequest,
    client: Any,
    *,
    reshape_output: Any | None = None,
) -> tuple[dict[str, Any] | None, func.HttpResponse | None]:
    """Return (manifest_dict, None) on success or (None, error_response) on failure.

    Shared between export and timelapse-data endpoints.
    When *reshape_output* is provided, it is applied to status.output before
    extracting the manifest path.
    """
    try:
        check_auth(req)
    except ValueError as exc:
        return None, error_response(401, str(exc), req=req)

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return None, error_response(400, "instance_id required", req=req)

    status = await client.get_status(instance_id)
    if not status or not status.output:
        return None, error_response(404, "Pipeline not found or not complete", req=req)

    output = status.output if isinstance(status.output, dict) else {}
    if reshape_output is not None:
        output = reshape_output(status.output) if status.output else {}
    manifest_path = output.get("enrichment_manifest") or output.get("enrichmentManifest")
    if not manifest_path:
        return None, error_response(404, "No enrichment data for this pipeline run", req=req)

    from treesight.constants import DEFAULT_OUTPUT_CONTAINER
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, manifest_path)
    except Exception:
        logger.exception("Failed to download enrichment manifest")
        return None, error_response(404, "Enrichment manifest not found in storage", req=req)

    return data, None
