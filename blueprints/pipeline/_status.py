"""Durable Functions status and output shaping helpers.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from treesight.config import MAX_JOB_DURATION_MINUTES

_ACTIVE_RUNTIME_STATUSES = {"running", "pending"}
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


def _normalize_runtime_status_payload(status: Any) -> tuple[str | None, dict[str, Any] | None]:
    runtime_status = status.runtime_status.value if status.runtime_status else None
    custom_status = _coerce_custom_status(status.custom_status)
    custom_status = _merge_history_hint(custom_status, getattr(status, "history", None))
    if _is_stalled_runtime(runtime_status, status.last_updated_time):
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


def _durable_status_payload(status: Any) -> dict[str, Any]:
    runtime_status, custom_status = _normalize_runtime_status_payload(status)
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
        import json

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
