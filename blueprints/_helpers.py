"""Shared helpers for blueprint HTTP endpoints."""

import json
import re

import azure.functions as func

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
    )


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def cors_preflight() -> func.HttpResponse:
    """Return a 204 CORS preflight response."""
    return func.HttpResponse(status_code=204, headers=CORS_HEADERS)
