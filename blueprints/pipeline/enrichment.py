"""Enrichment manifest serving: timelapse data, analysis save/load.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
import logging
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
from .history import assert_run_write_access, get_run_record_by_instance_id

logger = logging.getLogger(__name__)

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
    if manifest is None:
        return error_response(404, "No enrichment data for this pipeline run", req=req)

    # Internal cost telemetry should not be exposed in user-facing API payloads.
    sanitized_manifest = manifest.copy()
    sanitized_manifest.pop("estimated_cost_pence", None)

    # Merge user-generated annotations stored in Cosmos (parcel_notes, parcel_overrides).
    # Failures are non-fatal — manifest data always takes precedence.
    instance_id = req.route_params.get("instance_id", "")
    try:
        run_record = get_run_record_by_instance_id(instance_id)
        if run_record:
            if run_record.get("parcel_notes"):
                sanitized_manifest["parcel_notes"] = run_record["parcel_notes"]
            if run_record.get("parcel_overrides"):
                sanitized_manifest["parcel_overrides"] = run_record["parcel_overrides"]
    except Exception:
        logger.warning("Could not merge annotation data into manifest for run %s", instance_id)

    return func.HttpResponse(
        json.dumps(sanitized_manifest, default=str),
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
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    if user_id == "anonymous":
        return error_response(401, "Authentication required", req=req)

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

    run_record = get_run_record_by_instance_id(instance_id)
    if not run_record:
        return error_response(404, "Run not found", req=req)
    try:
        assert_run_write_access(run_record, user_id)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

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
        logger.warning("analysis load failed path=%s", analysis_path, exc_info=True)
        return error_response(404, "No saved analysis for this pipeline run", req=req)

    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
