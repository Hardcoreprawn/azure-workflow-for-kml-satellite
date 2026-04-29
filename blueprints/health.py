"""Health, readiness, and contract endpoints (§4.1, §4.4).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json
from urllib.parse import urlparse

import azure.functions as func

from treesight import __git_sha__, __version__
from treesight.constants import API_CONTRACT_VERSION

from ._helpers import cors_headers, cors_preflight

bp = func.Blueprint()


def _internal_smoke_allowed(req: func.HttpRequest) -> bool:
    """Allow internal smoke checks only on the dev orchestrator ingress host."""
    hostname = (urlparse(req.url).hostname or "").lower()
    return hostname.startswith("func-kmlsat-dev-orch.") and hostname.endswith(
        ".azurecontainerapps.io"
    )


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
