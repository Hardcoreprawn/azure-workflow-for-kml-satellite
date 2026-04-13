"""Ops dashboard endpoint — live pipeline visibility for operators.

Serves a single JSON payload with:
- app health / version info
- active durable orchestrations with phase/step detail
- recent submissions from Cosmos ``runs`` container
- basic request-rate counters

Protected by ``OPS_DASHBOARD_KEY`` bearer token (env var).
Not exposed to end users or CORS origins.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
Azure Functions worker cannot resolve deferred type annotations at
function-index time.
"""

import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import azure.durable_functions as df
import azure.functions as func

from treesight import __git_sha__, __version__

logger = logging.getLogger(__name__)

bp = func.Blueprint()

# ---------------------------------------------------------------------------
# In-memory request tracker (lightweight, no external deps)
# ---------------------------------------------------------------------------

_MAX_RECENT = 200
_recent_requests: list[dict[str, Any]] = []
_start_time = time.monotonic()


def track_request(
    *,
    method: str,
    path: str,
    status: int,
    user_id: str = "",
    duration_ms: float = 0,
) -> None:
    """Record a request for ops visibility. Call from _helpers or middleware."""
    _recent_requests.append(
        {
            "ts": datetime.now(UTC).isoformat(),
            "method": method,
            "path": path,
            "status": status,
            "user": user_id or "anon",
            "dur_ms": round(duration_ms, 1),
        }
    )
    # Trim oldest when buffer is full
    while len(_recent_requests) > _MAX_RECENT:
        _recent_requests.pop(0)


def _active_users(minutes: int = 15) -> list[str]:
    """Distinct user IDs seen in the last N minutes."""
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    seen: dict[str, str] = {}
    for r in reversed(_recent_requests):
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, KeyError):
            continue
        if ts < cutoff:
            break
        uid = r.get("user", "anon")
        if uid not in seen:
            seen[uid] = r["ts"]
    return list(seen.keys())


def _request_summary(minutes: int = 15) -> dict[str, Any]:
    """Summarise recent requests by path and status."""
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    total = 0
    by_path: dict[str, int] = {}
    by_status: dict[int, int] = {}
    uploads = 0
    for r in reversed(_recent_requests):
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, KeyError):
            continue
        if ts < cutoff:
            break
        total += 1
        path = r.get("path", "?")
        by_path[path] = by_path.get(path, 0) + 1
        status = r.get("status", 0)
        by_status[status] = by_status.get(status, 0) + 1
        if "upload" in path or "submit" in path:
            uploads += 1
    return {
        "total": total,
        "uploads": uploads,
        "by_path": dict(sorted(by_path.items(), key=lambda x: -x[1])[:10]),
        "by_status": by_status,
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _check_ops_key(req: func.HttpRequest) -> bool:
    """Validate bearer token against OPS_DASHBOARD_KEY."""
    key = os.environ.get("OPS_DASHBOARD_KEY", "")
    if not key:
        # No key configured → allow in dev, block in prod
        return os.environ.get("REQUIRE_AUTH", "").lower() not in ("true", "1", "yes")

    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return hmac.compare_digest(auth[7:].strip(), key)
    return False  # header-only auth; query-param keys leak via logs/referrers


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


async def _fetch_orchestrations(
    client: df.DurableOrchestrationClient,
) -> list[dict[str, Any]]:
    """Query Durable Functions for active + recently completed orchestrations."""
    results: list[dict[str, Any]] = []

    for runtime_filter in [
        df.OrchestrationRuntimeStatus.Running,
        df.OrchestrationRuntimeStatus.Pending,
    ]:
        try:
            instances = await client.get_status_by(  # type: ignore[attr-defined]
                runtime_status=[runtime_filter],
            )
            for inst in instances:
                custom = inst.custom_status or {}
                if isinstance(custom, str):
                    try:
                        custom = json.loads(custom)
                    except (json.JSONDecodeError, TypeError):
                        custom = {"raw": custom}

                results.append(
                    {
                        "instanceId": inst.instance_id,
                        "name": inst.name,
                        "runtimeStatus": inst.runtime_status.value if inst.runtime_status else None,
                        "createdTime": str(inst.created_time),
                        "lastUpdatedTime": str(inst.last_updated_time),
                        "phase": custom.get("phase", "") if isinstance(custom, dict) else "",
                        "step": custom.get("step", "") if isinstance(custom, dict) else "",
                        "customStatus": custom,
                    }
                )
        except Exception:
            logger.debug("Failed to query orchestrations for %s", runtime_filter, exc_info=True)

    return results


def _fetch_recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Fetch recent pipeline runs from Cosmos."""
    from treesight.storage.cosmos import cosmos_available, query_items

    if not cosmos_available():
        return []

    try:
        return query_items(
            "runs",
            "SELECT TOP @limit c.id, c.submission_id, c.user_id, c.status,"
            " c.submitted_at, c.feature_count, c.aoi_count,"
            " c.provider_name, c.processing_mode"
            " FROM c ORDER BY c.submitted_at DESC",
            parameters=[{"name": "@limit", "value": limit}],
        )
    except Exception:
        logger.debug("Cosmos query for recent runs failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@bp.route(
    route="ops/dashboard",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def ops_dashboard(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/ops/dashboard — live pipeline status for the CLI dashboard."""
    if not _check_ops_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json",
        )

    orchestrations = await _fetch_orchestrations(client)
    recent_runs = _fetch_recent_runs()
    active_users = _active_users()
    req_summary = _request_summary()
    uptime_s = int(time.monotonic() - _start_time)

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "app": {
            "version": __version__,
            "commit": __git_sha__,
            "uptime_seconds": uptime_s,
        },
        "activeUsers": active_users,
        "activeUserCount": len(active_users),
        "requests": req_summary,
        "recentRequests": _recent_requests[-30:],
        "orchestrations": orchestrations,
        "orchestrationCount": len(orchestrations),
        "recentRuns": recent_runs,
        "recentRunCount": len(recent_runs),
    }

    return func.HttpResponse(
        json.dumps(payload, default=str),
        status_code=200,
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# User management endpoints (ops-key protected)
# ---------------------------------------------------------------------------


def _clean_user_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip Cosmos metadata fields from a user document."""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


@bp.route(route="ops/users", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ops_list_users(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/ops/users — list registered users."""
    if not _check_ops_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json",
        )

    from treesight.security.users import list_users

    limit = min(int(req.params.get("limit", "50")), 200)
    users = list_users(limit=limit)
    return func.HttpResponse(
        json.dumps([_clean_user_doc(u) for u in users], default=str),
        status_code=200,
        mimetype="application/json",
    )


@bp.route(route="ops/users/lookup", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def ops_lookup_user(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/ops/users/lookup?email=... — find user by email."""
    if not _check_ops_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json",
        )

    email = req.params.get("email", "").strip()
    if not email:
        return func.HttpResponse(
            json.dumps({"error": "Missing 'email' query parameter"}),
            status_code=400,
            mimetype="application/json",
        )

    from treesight.security.users import lookup_user_by_email

    user = lookup_user_by_email(email)
    if not user:
        return func.HttpResponse(
            json.dumps({"error": "User not found"}),
            status_code=404,
            mimetype="application/json",
        )

    return func.HttpResponse(
        json.dumps(_clean_user_doc(user), default=str),
        status_code=200,
        mimetype="application/json",
    )


@bp.route(route="ops/users/{user_id}/role", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def ops_set_user_role(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/ops/users/{user_id}/role — set billing_allowed / tier."""
    if not _check_ops_key(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401,
            mimetype="application/json",
        )

    user_id = req.route_params.get("user_id", "").strip()
    if not user_id:
        return func.HttpResponse(
            json.dumps({"error": "Missing user_id in path"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json",
        )

    billing_allowed = body.get("billing_allowed")
    tier = body.get("tier")

    if billing_allowed is None and tier is None:
        return func.HttpResponse(
            json.dumps({"error": "Provide 'billing_allowed' and/or 'tier'"}),
            status_code=400,
            mimetype="application/json",
        )

    from treesight.security.users import set_user_role

    updated = set_user_role(
        user_id,
        billing_allowed=billing_allowed,
        tier=tier,
    )

    logger.info(
        "Operator set role: user=%s billing_allowed=%s tier=%s",
        user_id,
        billing_allowed,
        tier,
    )

    return func.HttpResponse(
        json.dumps(_clean_user_doc(updated), default=str),
        status_code=200,
        mimetype="application/json",
    )
