"""Durable Functions status and output shaping helpers.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from treesight.config import MAX_JOB_DURATION_MINUTES

logger = logging.getLogger(__name__)

_ACTIVE_RUNTIME_STATUSES = {"running", "pending"}
_RECOVERY_QUERY_PHASES = {"", "queued", "submit", "ingestion"}
_RECOVERY_MIN_AGE = timedelta(minutes=5)
_MIN_RECOVERY_LOOKBACK_MINUTES = 1
_MAX_RECOVERY_LOOKBACK_MINUTES = 24 * 60
_VALID_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_telemetry_lock = threading.RLock()
_telemetry_client: Any = None
_telemetry_credential: Any = None
_PHASE_RANK = {
    "queued": 0,
    "submit": 0,
    "ingestion": 1,
    "acquisition": 2,
    "per_aoi_pipeline": 2,
    "fulfilment": 3,
    "enrichment": 4,
    "complete": 5,
}
_HISTORY_PHASE_HINTS = {
    "parse_kml": ("ingestion", "parsing_kml"),
    "load_offloaded_features": ("ingestion", "parsing_kml"),
    "prepare_aoi": ("ingestion", "preparing_aois"),
    "store_aoi_claims": ("ingestion", "storing_claims"),
    "write_metadata": ("ingestion", "writing_metadata"),
    "acquire_composite": ("acquisition", "searching"),
    "acquire_imagery": ("acquisition", "searching"),
    "poll_order": ("acquisition", "polling"),
    "aoi_pipeline": ("acquisition", "per_aoi_pipeline"),
    "download_assets": ("fulfilment", "downloading"),
    "batch_submit_downloads": ("fulfilment", "batch_submit"),
    "poll_batch_downloads": ("fulfilment", "batch_polling"),
    "post_process": ("fulfilment", "post_processing"),
    "enrich_data_sources": ("enrichment", "data_sources_and_imagery"),
    "enrich_imagery": ("enrichment", "data_sources_and_imagery"),
    "enrich_single_aoi_step": ("enrichment", "per_aoi"),
    "enrich_finalize": ("enrichment", "finalizing"),
}


def _coerce_custom_status(custom_status: Any) -> dict[str, Any] | None:
    if custom_status is None:
        return None
    if isinstance(custom_status, dict):
        return dict(custom_status)
    if isinstance(custom_status, str):
        try:
            parsed = json.loads(custom_status)
        except (json.JSONDecodeError, TypeError):
            return {"raw": custom_status}
        return parsed if isinstance(parsed, dict) else {"raw": custom_status}
    return {"raw": str(custom_status)}


def _history_attr(event: Any, *names: str) -> Any:
    for name in names:
        if isinstance(event, dict) and name in event:
            return event[name]
        if hasattr(event, name):
            return getattr(event, name)
    return None


def _infer_phase_from_history(history: list[Any] | None) -> tuple[str, str] | None:
    if not history:
        return None
    for event in reversed(history):
        name = _history_attr(
            event,
            "FunctionName",
            "functionName",
            "Name",
            "name",
            "TaskName",
            "taskName",
        )
        if not isinstance(name, str):
            continue
        hint = _HISTORY_PHASE_HINTS.get(name)
        if hint:
            return hint
    return None


def _is_stalled_runtime(runtime_status: str | None, last_updated_time: datetime | None) -> bool:
    if not runtime_status or not last_updated_time:
        return False
    if runtime_status.strip().lower() not in _ACTIVE_RUNTIME_STATUSES:
        return False
    now = datetime.now(UTC)
    cutoff = timedelta(minutes=MAX_JOB_DURATION_MINUTES)
    last_updated = last_updated_time
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=UTC)
    return now - last_updated >= cutoff


def _merge_history_hint(
    custom_status: dict[str, Any] | None,
    history: list[Any] | None,
) -> dict[str, Any] | None:
    inferred = _infer_phase_from_history(history)
    if not inferred:
        return custom_status

    phase, step = inferred
    merged = dict(custom_status or {})
    current_phase = str(merged.get("phase") or "").strip().lower()
    if _PHASE_RANK.get(phase, 0) >= _PHASE_RANK.get(current_phase, 0):
        merged["phase"] = phase
        merged["step"] = step
        merged.setdefault("source", "durable_history")
    return merged


def _normalize_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _telemetry_recently_active(telemetry_hint: dict[str, Any] | None) -> bool:
    if not telemetry_hint:
        return False
    if str(telemetry_hint.get("outcome") or "").strip().lower() != "active":
        return False
    observed_at = _normalize_datetime(telemetry_hint.get("observed_at"))
    if not observed_at:
        return False
    return datetime.now(UTC) - observed_at < timedelta(minutes=MAX_JOB_DURATION_MINUTES)


def _merge_telemetry_hint(
    runtime_status: str | None,
    custom_status: dict[str, Any] | None,
    telemetry_hint: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if not telemetry_hint:
        return runtime_status, custom_status
    merged = dict(custom_status or {})
    phase = str(telemetry_hint.get("phase") or "").strip().lower()
    step = str(telemetry_hint.get("step") or "").strip()
    if phase:
        current_phase = str(merged.get("phase") or "").strip().lower()
        if _PHASE_RANK.get(phase, 0) >= _PHASE_RANK.get(current_phase, 0):
            merged["phase"] = phase
            if step:
                merged["step"] = step
            merged.setdefault("source", str(telemetry_hint.get("source") or "app_insights"))

    outcome = str(telemetry_hint.get("outcome") or "").strip().lower()
    if outcome == "completed":
        runtime_status = "Completed"
    elif outcome == "failed":
        runtime_status = "Failed"
        merged["failed"] = True
        error = str(telemetry_hint.get("error") or "").strip()
        if error:
            merged.setdefault("error", error)
    elif outcome == "active" and runtime_status:
        runtime_status = "Running"

    return runtime_status, merged or None


def _normalize_runtime_status_payload(
    status: Any,
    *,
    telemetry_hint: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    runtime_status = status.runtime_status.value if status.runtime_status else None
    custom_status = _coerce_custom_status(status.custom_status)
    custom_status = _merge_history_hint(custom_status, getattr(status, "history", None))
    runtime_status, custom_status = _merge_telemetry_hint(runtime_status, custom_status, telemetry_hint)
    if _is_stalled_runtime(runtime_status, status.last_updated_time) and not _telemetry_recently_active(telemetry_hint):
        custom_status = dict(custom_status or {})
        custom_status["stalled"] = True
        # Fallback only — preserve any phase/step already set by the history
        # hint (which is more accurate than a bare "queued"). setdefault is
        # a no-op when the key is present, so a self-referential default
        # would be misleading; use plain literals.
        custom_status.setdefault("phase", "queued")
        custom_status.setdefault("step", "no_recent_updates")
        runtime_status = "Stalled"
    return runtime_status, custom_status


def _needs_telemetry_recovery(status: Any) -> bool:
    runtime_status = status.runtime_status.value if status.runtime_status else ""
    normalized_runtime = str(runtime_status).strip().lower()
    if normalized_runtime not in _ACTIVE_RUNTIME_STATUSES:
        return False
    custom_status = _coerce_custom_status(status.custom_status)
    phase = str((custom_status or {}).get("phase") or "").strip().lower()
    if _is_stalled_runtime(runtime_status, status.last_updated_time):
        return True
    if phase not in _RECOVERY_QUERY_PHASES:
        return False
    last_updated = _normalize_datetime(status.last_updated_time)
    if not last_updated:
        return True
    return datetime.now(UTC) - last_updated >= _RECOVERY_MIN_AGE


def _fetch_instance_telemetry_hint(instance_id: str) -> dict[str, Any] | None:
    safe_instance_id = instance_id.strip()
    if not safe_instance_id or not _VALID_INSTANCE_ID_RE.fullmatch(safe_instance_id):
        return None
    try:
        from treesight import config

        workspace_id = (
            str(getattr(config, "LOG_ANALYTICS_WORKSPACE_ID", "") or "")
            or str(getattr(config, "APPINSIGHTS_WORKSPACE_ID", "") or "")
        ).strip()
        configured_lookback = int(getattr(config, "STATUS_RECOVERY_LOOKBACK_MINUTES", 240))
    except Exception:
        return None
    if not workspace_id:
        return None
    lookback_minutes = max(
        _MIN_RECOVERY_LOOKBACK_MINUTES,
        min(configured_lookback, _MAX_RECOVERY_LOOKBACK_MINUTES),
    )

    query = f"""
traces
| where timestamp > ago({lookback_minutes}m)
| extend cd = todynamic(customDimensions)
| where tostring(cd.instance_id) == "{safe_instance_id}" or tostring(cd.instanceId) == "{safe_instance_id}"
| project timestamp, phase=tostring(cd.phase), step=tostring(cd.step), error=tostring(cd.error), source="trace"
| union (
    exceptions
    | where timestamp > ago({lookback_minutes}m)
    | extend cd = todynamic(customDimensions)
    | where tostring(cd.instance_id) == "{safe_instance_id}" or tostring(cd.instanceId) == "{safe_instance_id}"
    | project timestamp, phase=tostring(cd.phase), step=tostring(cd.step), error=tostring(outerMessage),
              source="exception"
)
| order by timestamp desc
| take 1
"""
    try:
        rows = _query_logs_workspace(workspace_id, query)
    except Exception:
        logger.debug("Telemetry query failed for instance=%s", safe_instance_id, exc_info=True)
        return None
    if not rows:
        return None
    row = rows[0]
    phase = str(row.get("phase") or "").strip().lower()
    step = str(row.get("step") or "").strip()
    error = str(row.get("error") or "").strip()
    source = str(row.get("source") or "").strip().lower()
    observed_at = _normalize_datetime(row.get("timestamp"))
    if not phase and not step and not error:
        return None
    outcome = "failed" if error and source == "exception" else "active"
    if phase == "complete":
        outcome = "completed"
    return {
        "phase": phase,
        "step": step,
        "error": error,
        "outcome": outcome,
        "observed_at": observed_at,
        "source": "app_insights",
    }


def _query_logs_workspace(workspace_id: str, query: str) -> list[dict[str, Any]]:
    global _telemetry_client, _telemetry_credential
    with _telemetry_lock:
        if _telemetry_client is None:
            from azure.identity import DefaultAzureCredential
            from azure.monitor.query import LogsQueryClient

            _telemetry_credential = DefaultAzureCredential()
            _telemetry_client = LogsQueryClient(_telemetry_credential)
        client = _telemetry_client

    result = client.query_workspace(workspace_id, query)
    tables = list(getattr(result, "tables", []) or [])
    if not tables:
        tables = list(getattr(result, "partial_data", []) or [])
    if not tables:
        return []
    table = tables[0]
    columns = [col.name for col in getattr(table, "columns", [])]
    values: list[dict[str, Any]] = []
    for row in getattr(table, "rows", []):
        values.append(dict(zip(columns, row, strict=False)))
    return values


def _durable_status_payload(status: Any, *, telemetry_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_status, custom_status = _normalize_runtime_status_payload(status, telemetry_hint=telemetry_hint)
    return {
        "instanceId": status.instance_id,
        "name": status.name,
        "runtimeStatus": runtime_status,
        "createdTime": str(status.created_time),
        "lastUpdatedTime": str(status.last_updated_time),
        "customStatus": custom_status,
        "output": _reshape_output(status.output) if status.output else None,
    }


def _reshape_output(output: dict[str, Any] | str) -> dict[str, Any]:
    """Reshape PipelineSummary to the diagnostics contract (§4.3).

    The Durable Functions SDK sometimes returns output as a JSON string
    instead of a parsed dict — handle both cases.
    """
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return {"status": "unknown", "message": output}
    if not isinstance(output, dict):
        return {"status": "unknown", "message": str(output)}
    result = {
        "status": output.get("status", ""),
        "message": output.get("message", ""),
        "blobName": output.get("blob_name", ""),
        "featureCount": output.get("feature_count", 0),
        "aoiCount": output.get("aoi_count", 0),
        "metadataCount": output.get("metadata_count", 0),
        "imageryReady": output.get("imagery_ready", 0),
        "imageryFailed": output.get("imagery_failed", 0),
        "downloadsCompleted": output.get("downloads_completed", 0),
        "downloadsFailed": output.get("downloads_failed", 0),
        "postProcessCompleted": output.get("post_process_completed", 0),
        "postProcessFailed": output.get("post_process_failed", 0),
        "artifacts": output.get("artifacts", {}),
    }
    if output.get("enrichment_manifest"):
        result["enrichmentManifest"] = output["enrichment_manifest"]
    if output.get("enrichment_duration"):
        result["enrichmentDuration"] = output["enrichment_duration"]
    return result
