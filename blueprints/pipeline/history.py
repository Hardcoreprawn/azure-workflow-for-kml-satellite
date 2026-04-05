"""Submission record persistence and analysis history queries.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import contextlib
import json
import logging
from typing import Any
from urllib.parse import quote

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import cors_headers
from treesight.constants import DEFAULT_PROVIDER, PIPELINE_PAYLOADS_CONTAINER
from treesight.storage import cosmos as _cosmos_mod

from ._helpers import _durable_status_payload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SIGNED_IN_SUBMISSIONS_PREFIX = "analysis-submissions"
_DEFAULT_HISTORY_LIMIT = 8
_MAX_HISTORY_LIMIT = 20
_MAX_HISTORY_OFFSET = 200


# ---------------------------------------------------------------------------
# Submission record helpers
# ---------------------------------------------------------------------------


def _analysis_submission_prefix(user_id: str) -> str:
    return f"{_SIGNED_IN_SUBMISSIONS_PREFIX}/{quote(user_id, safe='')}/"


def _analysis_submission_blob_name(user_id: str, submission_id: str) -> str:
    return f"{_analysis_submission_prefix(user_id)}{submission_id}.json"


def _extract_submission_context(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}

    raw_context = body.get("submission_context")
    if not isinstance(raw_context, dict):
        return {}

    context: dict[str, Any] = {}
    int_fields = ("feature_count", "aoi_count")
    float_fields = ("max_spread_km", "total_area_ha", "largest_area_ha")
    text_fields = ("processing_mode", "provider_name", "workspace_role", "workspace_preference")

    for field in int_fields:
        value = raw_context.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            context[field] = int(value)

    for field in float_fields:
        value = raw_context.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            context[field] = round(float(value), 2)

    for field in text_fields:
        value = raw_context.get(field)
        if isinstance(value, str) and value.strip():
            context[field] = value.strip()[:80]

    return context


def _persist_submission_record(
    storage: Any,
    record: dict,
    user_id: str,
    submission_id: str,
) -> None:
    """Write a submission record to Cosmos (preferred) or blob storage."""
    if _cosmos_mod.cosmos_available():
        try:
            from treesight.storage import cosmos

            cosmos.upsert_item("runs", {"id": submission_id, **record})
            return
        except Exception:
            logger.warning(
                "Cosmos upsert failed for instance=%s user=%s, falling back to blob",
                submission_id,
                user_id,
                exc_info=True,
            )

    try:
        storage.upload_json(
            PIPELINE_PAYLOADS_CONTAINER,
            _analysis_submission_blob_name(user_id, submission_id),
            record,
        )
    except Exception:
        logger.warning(
            "Unable to persist analysis history record instance=%s user=%s",
            submission_id,
            user_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# History query helpers
# ---------------------------------------------------------------------------


def _parse_history_limit(raw_limit: str) -> int:
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return _DEFAULT_HISTORY_LIMIT
    return max(1, min(limit, _MAX_HISTORY_LIMIT))


def _parse_history_offset(raw_offset: str) -> int:
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        return 0
    return max(0, min(offset, _MAX_HISTORY_OFFSET))


def _fetch_submission_records(
    user_id: str, limit: int, *, offset: int = 0, max_results: int = 100
) -> list:
    # TODO: paginated Cosmos query — blob fallback is O(n) over all blobs
    """Retrieve submission records from Cosmos (preferred) or blob storage."""
    if _cosmos_mod.cosmos_available():
        try:
            from treesight.storage import cosmos

            query = (
                "SELECT * FROM c WHERE c.user_id = @uid"
                " ORDER BY c.submitted_at DESC OFFSET @off LIMIT @lim"
            )
            return cosmos.query_items(
                "runs",
                query,
                parameters=[
                    {"name": "@uid", "value": user_id},
                    {"name": "@off", "value": offset},
                    {"name": "@lim", "value": limit},
                ],
                partition_key=user_id,
            )
        except Exception:
            logger.warning(
                "Cosmos query failed for user=%s, falling back to blob",
                user_id,
                exc_info=True,
            )

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    blob_names = []
    prefix = _analysis_submission_prefix(user_id)

    try:
        blob_names = storage.list_blobs(PIPELINE_PAYLOADS_CONTAINER, prefix=prefix)
        if max_results:
            blob_names = blob_names[:max_results]
    except Exception:
        logger.info("No analysis history found for user=%s prefix=%s", user_id, prefix)

    records: list[dict[str, Any]] = []
    for blob_name in blob_names:
        try:
            record = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, blob_name)
        except Exception:
            logger.warning("Skipping unreadable analysis history blob=%s", blob_name)
            continue
        if record.get("user_id") != user_id:
            continue
        records.append(record)

    records.sort(key=lambda record: str(record.get("submitted_at", "")), reverse=True)
    return records[offset : offset + limit]


async def _build_analysis_history_response(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
    user_id: str,
) -> func.HttpResponse:
    """Build the signed-in history response for a single authenticated user."""
    limit = _parse_history_limit(req.params.get("limit", ""))
    offset = _parse_history_offset(req.params.get("offset", ""))
    records = _fetch_submission_records(user_id, limit, offset=offset)

    import asyncio

    runs = await asyncio.gather(
        *(_build_analysis_history_entry(record, client) for record in records)
    )
    active_run = next((run for run in runs if _history_run_is_active(run)), None)

    payload = {
        "runs": runs,
        "activeRun": active_run,
        "offset": offset,
        "limit": limit,
    }
    return func.HttpResponse(
        json.dumps(payload, default=str),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


async def _build_analysis_history_entry(
    record: dict[str, Any],
    client: df.DurableOrchestrationClient,
) -> dict[str, Any]:
    instance_id = str(record.get("instance_id") or record.get("submission_id") or "")
    status_payload: dict[str, Any] | None = None
    if instance_id:
        with contextlib.suppress(Exception):
            status = await client.get_status(instance_id)
            if status:
                status_payload = _durable_status_payload(status)

    runtime_status = record.get("status", "submitted")
    if status_payload and status_payload.get("runtimeStatus"):
        runtime_status = status_payload["runtimeStatus"]

    output = status_payload.get("output") if status_payload else None
    feature_count = output.get("featureCount") if output else record.get("feature_count")
    aoi_count = output.get("aoiCount") if output else record.get("aoi_count")
    artifacts = output.get("artifacts") if output else None

    return {
        "submissionId": record.get("submission_id", instance_id),
        "instanceId": instance_id,
        "submittedAt": record.get("submitted_at", ""),
        "submissionPrefix": record.get("submission_prefix", "analysis"),
        "providerName": record.get("provider_name", DEFAULT_PROVIDER),
        "featureCount": feature_count,
        "aoiCount": aoi_count,
        "processingMode": record.get("processing_mode"),
        "maxSpreadKm": record.get("max_spread_km"),
        "totalAreaHa": record.get("total_area_ha"),
        "largestAreaHa": record.get("largest_area_ha"),
        "workspaceRole": record.get("workspace_role"),
        "workspacePreference": record.get("workspace_preference"),
        "runtimeStatus": runtime_status,
        "createdTime": status_payload.get("createdTime")
        if status_payload
        else record.get("submitted_at", ""),
        "lastUpdatedTime": status_payload.get("lastUpdatedTime")
        if status_payload
        else record.get("submitted_at", ""),
        "customStatus": status_payload.get("customStatus") if status_payload else None,
        "output": output,
        "artifactCount": len(artifacts) if isinstance(artifacts, dict) else 0,
        "partialFailures": {
            "imagery": output.get("imageryFailed", 0) if output else 0,
            "downloads": output.get("downloadsFailed", 0) if output else 0,
            "postProcess": output.get("postProcessFailed", 0) if output else 0,
        },
        "kmlBlobName": record.get("kml_blob_name", ""),
        "kmlSizeBytes": record.get("kml_size_bytes", 0),
    }


def _history_run_is_active(run: dict[str, Any]) -> bool:
    runtime_status = str(run.get("runtimeStatus") or "").strip().lower()
    return runtime_status not in {"", "completed", "failed", "terminated", "canceled"}
