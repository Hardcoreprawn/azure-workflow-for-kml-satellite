"""Enrichment manifest serving: timelapse data, analysis save/load.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
from datetime import UTC, datetime

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight
from treesight.constants import DEFAULT_OUTPUT_CONTAINER

from . import bp
from ._helpers import _MAX_ANALYSIS_BODY_BYTES, _error_response, _reshape_output


@bp.route(
    route="timelapse-data/{instance_id}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def timelapse_data(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/timelapse-data/{instance_id} — serve cached enrichment manifest."""
    try:
        check_auth(req)
    except ValueError as exc:
        return _error_response(401, str(exc), req)

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return _error_response(400, "instance_id required", req)

    status = await client.get_status(instance_id)
    if not status or not status.output:
        return _error_response(404, "Pipeline not found or not complete", req)

    output = _reshape_output(status.output) if status.output else {}
    manifest_path = output.get("enrichment_manifest") or output.get("enrichmentManifest")
    if not manifest_path:
        return _error_response(404, "No enrichment data for this pipeline run", req)

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, manifest_path)
    except Exception:
        return _error_response(404, "Enrichment manifest not found in storage", req)

    return func.HttpResponse(
        json.dumps(data, default=str),
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
        return _error_response(401, str(exc), req)

    raw_body = req.get_body()
    if len(raw_body) > _MAX_ANALYSIS_BODY_BYTES:
        return _error_response(
            413, f"Request body too large (max {_MAX_ANALYSIS_BODY_BYTES} bytes)", req
        )

    try:
        body = req.get_json()
    except ValueError:
        return _error_response(400, "Invalid JSON body", req)

    instance_id = body.get("instance_id", "")
    analysis = body.get("analysis", {})

    if not instance_id or not analysis:
        return _error_response(400, "instance_id and analysis are required", req)

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
        return _error_response(401, str(exc), req)

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return _error_response(400, "instance_id required", req)

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    analysis_path = f"analysis/{instance_id}/timelapse_analysis.json"
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, analysis_path)
    except Exception:
        return _error_response(404, "No saved analysis for this pipeline run", req)

    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
