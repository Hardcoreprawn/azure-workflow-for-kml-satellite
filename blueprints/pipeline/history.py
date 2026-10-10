"""Submission record persistence and analysis history queries.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import cors_headers, error_response
from treesight.constants import DEFAULT_PROVIDER
from treesight.pipeline import run_access as _run_access
from treesight.storage import cosmos as _cosmos_mod

from ._status import (
    _durable_status_payload,
    _fetch_instance_telemetry_hint,
    _needs_telemetry_recovery,
)

RunRecordLookupError = _run_access.RunRecordLookupError
assert_run_write_access = _run_access.assert_run_write_access
get_run_record_by_instance_id = _run_access.get_run_record_by_instance_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_HISTORY_LIMIT = 8
_MAX_HISTORY_LIMIT = 20
_MAX_HISTORY_OFFSET = 200


# ---------------------------------------------------------------------------
# Submission record helpers
# ---------------------------------------------------------------------------


class RunRecordPersistenceError(RuntimeError):
    """Raised when an authoritative submission record cannot be stored."""


# ---------------------------------------------------------------------------
# Run record lookup and write-access guard
# ---------------------------------------------------------------------------


class AnalysisHistoryUnavailableError(RuntimeError):
    """Raised when history cannot be read authoritatively from Cosmos."""


def get_authorized_run_record(instance_id: str, user_id: str, *, active_org: dict[str, Any] | None) -> dict[str, Any]:
    """Load authoritative origin ownership and require current selected-org membership."""
    record = get_run_record_by_instance_id(instance_id, raise_on_error=True)
    if not record:
        raise ValueError("Run not found")
    assert_run_write_access(record, user_id, active_org=active_org)
    return record


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
    record: dict,
    user_id: str,
    submission_id: str,
    *,
    reuse_existing: bool = False,
) -> None:
    """Persist the authoritative run record before a submission is published."""
    if not _cosmos_mod.cosmos_available():
        raise RunRecordPersistenceError("Cosmos unavailable")
    if not isinstance(record.get("org_id"), str) or not record["org_id"].strip():
        raise RunRecordPersistenceError("Originating organisation required")
    if reuse_existing:
        try:
            stored_record = _cosmos_mod.read_item("runs", submission_id, user_id)
        except Exception as exc:
            raise RunRecordPersistenceError("Previous submission history could not be verified") from exc
        if (
            stored_record
            and stored_record.get("id") == submission_id
            and stored_record.get("user_id") == user_id
            and stored_record.get("org_id") == record["org_id"]
            and str(stored_record.get("status", "")).lower() not in {"failed", "terminated", "canceled"}
        ):
            return
        raise RunRecordPersistenceError("Previous submission history is not reusable")
    expected_record = {"id": submission_id, **record}
    try:
        _cosmos_mod.upsert_item("runs", expected_record)
    except Exception as exc:
        logger.warning(
            "Cosmos upsert failed for instance=%s user=%s",
            submission_id,
            user_id,
            exc_info=True,
        )
        try:
            stored_record = _cosmos_mod.read_item("runs", submission_id, user_id)
        except Exception:
            logger.warning(
                "Unable to verify Cosmos run record after upsert failure instance=%s user=%s",
                submission_id,
                user_id,
                exc_info=True,
            )
            raise RunRecordPersistenceError("Run record persistence could not be verified") from exc
        if stored_record and all(
            field in stored_record and stored_record[field] == value for field, value in expected_record.items()
        ):
            logger.info("Recovered ambiguous Cosmos upsert instance=%s user=%s", submission_id, user_id)
            return
        raise RunRecordPersistenceError("Run record persistence failed") from exc


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


def _fetch_submission_records(user_id: str | None, limit: int, *, offset: int = 0, org_id: str | None = None) -> list:
    """Retrieve submission records from Cosmos using server-side pagination."""
    if not _cosmos_mod.cosmos_available():
        logger.warning("Cosmos unavailable — history query skipped for user=%s", user_id)
        raise AnalysisHistoryUnavailableError("Cosmos unavailable")
    if not org_id:
        raise AnalysisHistoryUnavailableError("Originating organisation required")
    try:
        from treesight.storage import cosmos

        query = "SELECT * FROM c WHERE c.org_id = @org"
        if user_id:
            query += " AND c.user_id = @uid"
        query += " ORDER BY c.submitted_at DESC OFFSET @off LIMIT @lim"
        parameters = [
            {"name": "@org", "value": org_id},
            {"name": "@off", "value": offset},
            {"name": "@lim", "value": limit},
        ]
        if user_id:
            parameters.append({"name": "@uid", "value": user_id})
        return cosmos.query_items(
            "runs",
            query,
            parameters=parameters,
            partition_key=user_id,
        )
    except Exception as exc:
        logger.warning(
            "Cosmos query failed for user=%s",
            user_id,
            exc_info=True,
        )
        raise AnalysisHistoryUnavailableError("History query failed") from exc


def _fetch_portfolio_submission_records(
    user_id: str, limit: int, *, offset: int = 0, active_org: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], str, str | None, int]:
    """Retrieve origin-owned portfolio history from an authenticated org snapshot.

    Requires current membership; absent/mismatched org raises ValueError rather
    than falling back to creator scope. Origin filtering precedes pagination.
    """
    org_id = active_org.get("org_id") if active_org else None
    assert_run_write_access({"org_id": org_id}, user_id, active_org=active_org)
    members = active_org.get("members", []) if active_org else []
    member_ids = {member["user_id"] for member in members if isinstance(member, dict) and member.get("user_id")}
    records = _fetch_submission_records(None, limit, offset=offset, org_id=org_id)
    return records, "org", org_id, len(member_ids)


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
    *,
    active_org: dict[str, Any] | None = None,
) -> func.HttpResponse:
    """Build signed-in history response for user or org portfolio scope."""
    limit = _parse_history_limit(req.params.get("limit", ""))
    offset = _parse_history_offset(req.params.get("offset", ""))
    scope = str(req.params.get("scope", "user")).strip().lower()

    try:
        org_id = active_org.get("org_id") if active_org else None
        assert_run_write_access({"org_id": org_id}, user_id, active_org=active_org)
        if scope == "org":
            records, resolved_scope, org_id, member_count = _fetch_portfolio_submission_records(
                user_id, limit, offset=offset, active_org=active_org
            )
        else:
            records = _fetch_submission_records(user_id, limit, offset=offset, org_id=org_id)
            resolved_scope = "user"
            member_count = 1
    except ValueError as exc:
        return error_response(403, str(exc), req=req)
    except AnalysisHistoryUnavailableError:
        return error_response(503, "Analysis history is temporarily unavailable. Please retry.", req=req)

    records = [record for record in records if record.get("org_id") == org_id]
    runs = await asyncio.gather(*(_build_analysis_history_entry(record, client) for record in records))
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
        try:
            status = await client.get_status(instance_id)
            if status:
                telemetry_hint = None
                if _needs_telemetry_recovery(status):
                    telemetry_hint = await asyncio.to_thread(_fetch_instance_telemetry_hint, instance_id)
                status_payload = _durable_status_payload(status, telemetry_hint=telemetry_hint)
        except Exception:
            logger.warning("Unable to fetch durable/telemetry status for instance=%s", instance_id, exc_info=True)

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
        "createdTime": status_payload.get("createdTime") if status_payload else record.get("submitted_at", ""),
        "lastUpdatedTime": status_payload.get("lastUpdatedTime") if status_payload else record.get("submitted_at", ""),
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
    if runtime_status in {"", "completed", "failed", "terminated", "canceled", "stalled"}:
        return False
    custom_status = run.get("customStatus")
    return not (isinstance(custom_status, dict) and custom_status.get("stalled") is True)
