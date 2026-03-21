"""Health, readiness, and contract endpoints (§4.1, §4.4).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json

import azure.functions as func

from treesight.constants import API_CONTRACT_VERSION

bp = func.Blueprint()


@bp.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "healthy"}),
        status_code=200,
        mimetype="application/json",
    )


@bp.route(route="readiness", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def readiness(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ready", "api_version": API_CONTRACT_VERSION}),
        status_code=200,
        mimetype="application/json",
    )


@bp.route(route="contract", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def contract(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"api_version": API_CONTRACT_VERSION}),
        status_code=200,
        mimetype="application/json",
    )
