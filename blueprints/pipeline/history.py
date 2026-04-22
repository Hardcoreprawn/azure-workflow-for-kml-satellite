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
from treesight.security.orgs import get_user_org
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
_MAX_ORG_MEMBERS = 50


# ---------------------------------------------------------------------------
# Submission record helpers
# ---------------------------------------------------------------------------


def _analysis_submission_prefix(user_id: str) -> str:
    return f"{_SIGNED_IN_SUBMISSIONS_PREFIX}/{quote(user_id, safe='')}/"


def _analysis_submission_blob_name(user_id: str, submission_id: str) -> str:
    return f"{_analysis_submission_prefix(user_id)}{submission_id}.json"


# ---------------------------------------------------------------------------
# Run record lookup and write-access guard
# ---------------------------------------------------------------------------


def get_run_record_by_instance_id(instance_id: str) -> dict[str, Any] | None:
    """Fetch a single run record by instance ID using a cross-partition Cosmos query.

    Returns None when the record is not found or Cosmos is not available.
    Blob fallback is not supported for cross-user lookups (owner unknown).
    """
    if not _cosmos_mod.cosmos_available():
        return None
    try:
        from treesight.storage import cosmos

        results = cosmos.query_items(
            "runs",
            "SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": instance_id}],
        )
        return results[0] if results else None
    except Exception:
        logger.warning("Cosmos run lookup failed for instance=%s", instance_id, exc_info=True)
        return None


def assert_run_write_access(run_record: dict[str, Any], requesting_user_id: str) -> None:
    """Raise ValueError if *requesting_user_id* is not permitted to write to *run_record*.

    Permits the run owner directly, or any member of the owner's org.
    Raises ValueError with a generic message to avoid leaking run ownership
    to unauthorised callers.
    """
    owner_id = str(run_record.get("user_id", "")).strip()
    if owner_id and owner_id == requesting_user_id:
        return

    try:
        org = get_user_org(requesting_user_id)
        if org and isinstance(org, dict):
            member_ids = {
                str(m.get("user_id", "")).strip()
                for m in org.get("members", [])
                if isinstance(m, dict)
            }
            if owner_id in member_ids:
                return
    except Exception:
        logger.warning("Org lookup failed for user=%s", requesting_user_id, exc_info=True)

    raise ValueError("Run not found or you do not have permission to modify it")


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


def _fetch_portfolio_submission_records(
    user_id: str, limit: int, *, offset: int = 0
) -> tuple[list[dict[str, Any]], str, str | None, int]:
    """Retrieve history records for the signed-in user's org portfolio.

    Falls back to user scope when no org is configured.
    """
    org = get_user_org(user_id)
    if not org:
        return _fetch_submission_records(user_id, limit, offset=offset), "user", None, 1

    members = org.get("members", []) if isinstance(org, dict) else []
    member_ids = [
        str(member.get("user_id", "")).strip()
        for member in members
        if isinstance(member, dict) and str(member.get("user_id", "")).strip()
    ]
    if user_id not in member_ids:
        member_ids.append(user_id)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped_member_ids: list[str] = []
    for member_id in member_ids:
        if member_id in seen:
            continue
        seen.add(member_id)
        deduped_member_ids.append(member_id)

    fetch_limit = max(1, min(_MAX_HISTORY_LIMIT + _MAX_HISTORY_OFFSET, limit + offset + 20))
    records: list[dict[str, Any]] = []
    for member_id in deduped_member_ids[:_MAX_ORG_MEMBERS]:
        records.extend(
            _fetch_submission_records(member_id, fetch_limit, offset=0, max_results=fetch_limit)
        )

    records.sort(key=lambda record: str(record.get("submitted_at", "")), reverse=True)
    return (
        records[offset : offset + limit],
        "org",
        str(org.get("org_id", "")) or None,
        len(deduped_member_ids),
    )


def _history_stats_from_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    failed_statuses = {"failed", "terminated", "canceled"}
    completed = 0
    failed = 0
    active = 0
    total_parcels = 0
    for run in runs:
        runtime_status = str(run.get("runtimeStatus") or "").strip().lower()
        if runtime_status == "completed":
            completed += 1
        elif runtime_status in failed_statuses:
            failed += 1
        else:
            active += 1
        with contextlib.suppress(TypeError, ValueError):
            total_parcels += int(run.get("aoiCount") or 0)

    return {
        "totalRuns": len(runs),
        "activeRuns": active,
        "completedRuns": completed,
        "failedRuns": failed,
        "totalParcels": total_parcels,
        "lastSubmittedAt": (runs[0].get("submittedAt") if runs else ""),
    }


async def _build_analysis_history_response(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
    user_id: str,
) -> func.HttpResponse:
    """Build signed-in history response for user or org portfolio scope."""
    limit = _parse_history_limit(req.params.get("limit", ""))
    offset = _parse_history_offset(req.params.get("offset", ""))
    scope = str(req.params.get("scope", "user")).strip().lower()

    if scope == "org":
        records, resolved_scope, org_id, member_count = _fetch_portfolio_submission_records(
            user_id, limit, offset=offset
        )
    else:
        records = _fetch_submission_records(user_id, limit, offset=offset)
        resolved_scope = "user"
        org_id = None
        member_count = 1

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
        "scope": resolved_scope,
        "orgId": org_id,
        "memberCount": member_count,
        "stats": _history_stats_from_runs(runs),
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
