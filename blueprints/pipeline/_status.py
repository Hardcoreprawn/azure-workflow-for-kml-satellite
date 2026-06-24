"""Durable Functions status and output shaping helpers.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from typing import Any


def _durable_status_payload(status: Any) -> dict[str, Any]:
    return {
        "instanceId": status.instance_id,
        "name": status.name,
        "runtimeStatus": status.runtime_status.value if status.runtime_status else None,
        "createdTime": str(status.created_time),
        "lastUpdatedTime": str(status.last_updated_time),
        "customStatus": status.custom_status,
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
