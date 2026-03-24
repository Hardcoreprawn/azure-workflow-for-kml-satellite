"""Shared helpers for blueprint HTTP endpoints."""

import json
import os
import re
from functools import wraps

import azure.functions as func

from treesight.security.auth import auth_enabled, get_user_id, validate_token

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FIELD_LEN = 2000

# Allowed CORS origins — production SWA + local dev
_ALLOWED_ORIGINS: set[str] = {
    "https://polite-glacier-0d6885003.4.azurestaticapps.net",
    "https://treesight.hrdcrprwn.com",
    "http://localhost:4280",
    "http://localhost:1111",
}

# Allow override via env var (comma-separated) for custom domains
_extra = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _extra:
    _ALLOWED_ORIGINS.update(o.strip() for o in _extra.split(",") if o.strip())


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
        "Access-Control-Max-Age": "7200",
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
