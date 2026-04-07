"""Enrichment manifest serving: timelapse data, analysis save/load.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
from datetime import UTC, datetime

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import (
    check_auth,
    cors_headers,
    cors_preflight,
    error_response,
    fetch_enrichment_manifest,
)
from treesight.constants import DEFAULT_OUTPUT_CONTAINER

from . import bp
from ._helpers import _reshape_output

_MAX_ANALYSIS_BODY_BYTES = 131_072


@bp.route(
    route="timelapse-data/{instance_id}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def timelapse_data(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/timelapse-data/{instance_id} — serve cached enrichment manifest."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    manifest, err = await fetch_enrichment_manifest(
        req,
        client,
        reshape_output=_reshape_output,
    )
    if err:
        return err

    return func.HttpResponse(
        json.dumps(manifest, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="timelapse-analysis-save",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def timelapse_analysis_save(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/timelapse-analysis-save — persist AI analysis results."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    raw_body = req.get_body()
    if len(raw_body) > _MAX_ANALYSIS_BODY_BYTES:
        return error_response(
            413, f"Request body too large (max {_MAX_ANALYSIS_BODY_BYTES} bytes)", req=req
        )

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    instance_id = body.get("instance_id", "")
    analysis = body.get("analysis", {})

    if not instance_id or not analysis:
        return error_response(400, "instance_id and analysis are required", req=req)

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()

    analysis_path = f"analysis/{instance_id}/timelapse_analysis.json"
    analysis["saved_at"] = datetime.now(UTC).isoformat()
    analysis["instance_id"] = instance_id
    storage.upload_json(DEFAULT_OUTPUT_CONTAINER, analysis_path, analysis)

    return func.HttpResponse(
        json.dumps({"saved": True, "path": analysis_path}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="timelapse-analysis-load/{instance_id}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def timelapse_analysis_load(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/timelapse-analysis-load/{instance_id} — retrieve saved analysis."""
    try:
        check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return error_response(400, "instance_id required", req=req)

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    analysis_path = f"analysis/{instance_id}/timelapse_analysis.json"
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, analysis_path)
    except Exception:
        return error_response(404, "No saved analysis for this pipeline run", req=req)

    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
