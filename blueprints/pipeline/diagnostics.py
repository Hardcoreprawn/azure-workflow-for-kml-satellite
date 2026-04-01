"""Diagnostic HTTP endpoints: orchestrator status, analysis history.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight
from treesight.security.rate_limit import get_client_ip, pipeline_limiter

from . import bp
from ._helpers import _durable_status_payload, _error_response
from .history import _build_analysis_history_response


@bp.route(
    route="orchestrator/{instance_id}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def orchestrator_status(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/orchestrator/{instance_id} — direct JSON diagnostics (§4.3)."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return _error_response(429, "Rate limit exceeded — try again later")

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return func.HttpResponse(
            json.dumps({"error": "instance_id required"}),
            status_code=400,
            mimetype="application/json",
        )

    status = await client.get_status(instance_id)
    if not status:
        return func.HttpResponse(
            json.dumps({"error": "not found"}), status_code=404, mimetype="application/json"
        )

    result = _durable_status_payload(status)
    return func.HttpResponse(
        json.dumps(result, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="analysis/history",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def analysis_history(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/analysis/history — recent signed-in runs for the current user."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc))

    if user_id == "anonymous":
        return _error_response(401, "Authentication required for analysis history")

    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return _error_response(429, "Rate limit exceeded — try again later")

    return await _build_analysis_history_response(req, client, user_id)
