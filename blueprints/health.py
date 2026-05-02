"""Health, readiness, and contract endpoints (§4.1, §4.4).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json
import logging
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import azure.functions as func

from treesight import __git_sha__, __version__
from treesight.constants import API_CONTRACT_VERSION

from ._helpers import cors_headers, cors_preflight

bp = func.Blueprint()
logger = logging.getLogger(__name__)

_INTERNAL_SMOKE_HOST_RE = re.compile(r"^func-kmlsat-(dev|prd)-orch\..+\.azurecontainerapps\.io$")


def _internal_smoke_allowed(req: func.HttpRequest) -> bool:
    """Allow internal smoke checks only on dev/prd orchestrator ingress hosts."""
    hostname = (urlparse(req.url).hostname or "").lower()
    return bool(_INTERNAL_SMOKE_HOST_RE.fullmatch(hostname))


@bp.route(route="health", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)
    return func.HttpResponse(
        json.dumps({"status": "healthy", "version": __version__, "commit": __git_sha__}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(route="readiness", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def readiness(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)
    return func.HttpResponse(
        json.dumps(
            {
                "status": "ready",
                "api_version": API_CONTRACT_VERSION,
                "version": __version__,
                "commit": __git_sha__,
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(route="contract", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def contract(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)
    return func.HttpResponse(
        json.dumps({"api_version": API_CONTRACT_VERSION}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(route="internal-smoke", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def internal_smoke(req: func.HttpRequest) -> func.HttpResponse:
    """Internal deploy smoke probe, restricted to dev orchestrator ingress."""
    if not _internal_smoke_allowed(req):
        return func.HttpResponse(status_code=404)

    if req.method == "OPTIONS":
        return cors_preflight(req)

    return func.HttpResponse(
        json.dumps(
            {
                "status": "ok",
                "scope": "internal-deploy-smoke",
                "target": "dev-orchestrator",
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# Deep health (#760) — pre-demo smoke validation
# ---------------------------------------------------------------------------

def _check_ciam(authority: str) -> dict:
    """Check CIAM OIDC discovery endpoint reachability."""
    if not authority:
        return {"status": "unconfigured"}
    url = authority.rstrip("/") + "/v2.0/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 — well-known URL built from config
            if r.status == 200:
                return {"status": "ok"}
            return {"status": "unreachable", "http": r.status}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


def _check_blob(container_name: str = "kml-input") -> dict:
    """Check Blob storage list access on the input container."""
    from treesight.storage.client import BlobStorageClient

    try:
        client = BlobStorageClient()
        # list_blobs returns a list; we only need proof of access, so stop at first item.
        blobs = client.list_blobs(container_name)
        _ = blobs[:1]
        return {"status": "ok"}
    except PermissionError:
        return {"status": "permission_denied"}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


def _check_recent_pipeline(lookback_hours: int = 24) -> dict:
    """Check whether a completed pipeline run exists in the last ``lookback_hours``."""
    from treesight.storage import cosmos as _cosmos

    if not _cosmos.cosmos_available():
        return {"status": "cosmos_unavailable"}

    cutoff = (datetime.now(UTC) - timedelta(hours=lookback_hours)).isoformat()
    try:
        rows = _cosmos.query_items(
            "run-records",
            (
                "SELECT VALUE COUNT(1) FROM c "
                "WHERE c.status = 'completed' "
                "AND c.submitted_at >= @cutoff"
            ),
            parameters=[{"name": "@cutoff", "value": cutoff}],
        )
        count = int(rows[0]) if rows else 0
        if count > 0:
            return {"status": "ok", "recent_completed": count}
        return {"status": "no_recent_run"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _build_deep_status(components: dict) -> str:
    """Derive overall status from component results."""
    statuses = {v.get("status") for v in components.values() if isinstance(v, dict)}
    if any(s in ("unreachable", "permission_denied", "error") for s in statuses):
        return "failing"
    if any(s in ("no_recent_run", "unconfigured", "cosmos_unavailable") for s in statuses):
        return "degraded"
    return "healthy"


@bp.route(route="health/deep", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def health_deep(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/health/deep — pre-demo infra smoke check (#760).

    Checks CIAM discoverability, Blob storage list access, and recent
    pipeline completion.  Returns ``200`` for all states (healthy/degraded/
    failing) so monitoring tools can always parse the body.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    from treesight import config
    from treesight.pipeline.concurrency import count_active_runs

    components = {
        "ciam": _check_ciam(config.CIAM_AUTHORITY),
        "blob": _check_blob(),
        "recent_pipeline": _check_recent_pipeline(),
    }
    status = _build_deep_status(components)

    body = {
        "status": status,
        "components": components,
        "config": {
            "max_concurrent_jobs": config.MAX_CONCURRENT_JOBS,
            "safe_mode": config.SAFE_MODE,
            "active_runs": count_active_runs(),
        },
    }
    return func.HttpResponse(
        json.dumps(body),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
