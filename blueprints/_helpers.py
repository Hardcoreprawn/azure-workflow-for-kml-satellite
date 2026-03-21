"""Shared helpers for blueprint HTTP endpoints."""

import json
import re
from functools import wraps

import azure.functions as func

from treesight.security.auth import b2c_enabled, get_user_id, validate_token

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FIELD_LEN = 2000


def sanitise(value: str) -> str:
    """Strip and truncate a user-supplied string field."""
    return value.strip()[:MAX_FIELD_LEN] if isinstance(value, str) else ""


def error_response(status: int, message: str) -> func.HttpResponse:
    """Return a JSON error response with the given status code."""
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def cors_preflight() -> func.HttpResponse:
    """Return a 204 CORS preflight response."""
    return func.HttpResponse(status_code=204, headers=CORS_HEADERS)


def require_auth(fn):
    """Decorator that validates B2C JWT on the request.

    When B2C is not configured the request passes through unauthenticated
    (graceful degradation for local dev / pre-B2C deployments).

    On success, the original function receives two extra keyword arguments:
        auth_claims  — decoded JWT claims dict
        user_id      — subject identifier string
    """

    @wraps(fn)
    def wrapper(req: func.HttpRequest) -> func.HttpResponse:
        if req.method == "OPTIONS":
            return cors_preflight()

        if not b2c_enabled():
            # B2C not configured — allow through without auth
            return fn(req, auth_claims={}, user_id="anonymous")

        auth_header = req.headers.get("Authorization", "")
        try:
            claims = validate_token(auth_header)
        except ValueError as exc:
            return error_response(401, str(exc))

        return fn(req, auth_claims=claims, user_id=get_user_id(claims))

    return wrapper


def check_auth(req: func.HttpRequest) -> tuple:
    """Validate B2C JWT and return (claims, user_id).

    Returns ({}, "anonymous") when B2C is not configured.
    Raises ValueError with a user-safe message on auth failure.
    """
    if not b2c_enabled():
        return {}, "anonymous"
    auth_header = req.headers.get("Authorization", "")
    claims = validate_token(auth_header)
    return claims, get_user_id(claims)
