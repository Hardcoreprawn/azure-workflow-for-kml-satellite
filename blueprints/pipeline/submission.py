"""Submission HTTP endpoints: demo and authenticated analysis requests.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, error_response
from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_PROVIDER, MAX_KML_FILE_SIZE_BYTES
from treesight.security.quota import consume_quota
from treesight.security.rate_limit import demo_limiter, get_client_ip

from . import bp
from .history import _extract_submission_context, _persist_submission_record


@bp.route(route="demo-process", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def demo_process(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """POST /api/demo-process — anonymous demo submission with tier limits."""
    return await _submit_demo_request(req, client)


@bp.route(route="analysis/submit", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def analysis_submit(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """POST /api/analysis/submit — authenticated analysis submission."""
    return await _submit_analysis_request(req, client, blob_prefix="analysis")


async def _submit_demo_request(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """Validate, persist, and enqueue an anonymous demo KML submission."""
    client_ip = get_client_ip(req)

    if not demo_limiter.is_allowed(client_ip):
        return error_response(429, "Demo rate limit exceeded — try again later", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:12]
    demo_user_id = f"demo:{ip_hash}"

    return await _submit_kml(
        req,
        client,
        body,
        blob_prefix="demo",
        extra_input={
            "cadence": "seasonal",
            "max_history_years": 2,
            "user_id": demo_user_id,
            "tier": "demo",
        },
        log_tag=f"Demo process started user={demo_user_id}",
    )


async def _submit_analysis_request(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
    *,
    blob_prefix: str,
) -> func.HttpResponse:
    """Validate, persist, and enqueue a KML analysis submission."""
    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    try:
        consume_quota(user_id)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    submission_context = _extract_submission_context(body)

    effective_provider = submission_context.get("provider_name", DEFAULT_PROVIDER)

    resp = await _submit_kml(
        req,
        client,
        body,
        blob_prefix=blob_prefix,
        extra_input={"provider_name": effective_provider},
        log_tag=f"Analysis process started prefix={blob_prefix}",
    )

    # Persist submission record for analysis history
    if resp.status_code == 202 and (blob_prefix.strip("/") or "analysis") == "analysis":
        resp_data = json.loads(resp.get_body())
        submission_id = resp_data["instance_id"]
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        record: dict[str, Any] = {
            "submission_id": submission_id,
            "instance_id": submission_id,
            "user_id": user_id,
            "submitted_at": datetime.now(UTC).isoformat(),
            "kml_blob_name": f"{blob_prefix.strip('/') or 'analysis'}/{submission_id}.kml",
            "kml_size_bytes": len(body.get("kml_content", "").encode("utf-8"))
            if isinstance(body, dict)
            else 0,
            "submission_prefix": blob_prefix.strip("/") or "analysis",
            "provider_name": effective_provider,
            "status": "submitted",
        }
        record.update(submission_context)
        _persist_submission_record(storage, record, user_id, submission_id)

    return resp


async def _submit_kml(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
    body: Any,
    *,
    blob_prefix: str,
    extra_input: dict[str, Any] | None = None,
    log_tag: str = "",
) -> func.HttpResponse:
    """Shared KML validation, upload, and orchestrator start."""
    kml_content = body.get("kml_content", "") if isinstance(body, dict) else ""
    if not isinstance(kml_content, str) or not kml_content.strip():
        return error_response(400, "kml_content is required", req=req)

    kml_bytes = kml_content.encode("utf-8")
    if len(kml_bytes) > MAX_KML_FILE_SIZE_BYTES:
        return error_response(400, f"KML exceeds {MAX_KML_FILE_SIZE_BYTES} bytes", req=req)

    submission_id = str(uuid.uuid4())
    safe_prefix = blob_prefix.strip("/") or "analysis"
    kml_blob_name = f"{safe_prefix}/{submission_id}.kml"

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    blob_url = storage.upload_bytes(
        DEFAULT_INPUT_CONTAINER,
        kml_blob_name,
        kml_bytes,
        content_type="application/vnd.google-earth.kml+xml",
    )

    orchestrator_input: dict[str, Any] = {
        "blob_url": blob_url,
        "container_name": DEFAULT_INPUT_CONTAINER,
        "blob_name": kml_blob_name,
        "content_length": len(kml_bytes),
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": datetime.now(UTC).isoformat(),
        "correlation_id": submission_id,
        "composite_search": True,
        "provider_name": DEFAULT_PROVIDER,
    }
    if extra_input:
        orchestrator_input.update(extra_input)

    await client.start_new(
        "treesight_orchestrator",
        instance_id=submission_id,
        client_input=orchestrator_input,
    )

    logging.info("%s instance=%s", log_tag, submission_id)

    return func.HttpResponse(
        json.dumps({"instance_id": submission_id, "submission_prefix": safe_prefix}),
        status_code=202,
        mimetype="application/json",
        headers=cors_headers(req),
    )
