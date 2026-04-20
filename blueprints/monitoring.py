"""Monitoring blueprint — scheduled AOI re-analysis and change alerts (§3.1).

Provides:
- Timer Trigger (``monitoring_scheduler``) that runs every 6 hours,
  queries due monitors, and kicks off pipeline re-runs.
- HTTP endpoints to create, list, update, and delete monitors.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
The Azure Functions v2 runtime inspects binding parameter annotations
at import time.  PEP 563 causes FunctionLoadError.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import azure.functions as func

from blueprints._helpers import (
    cors_headers,
    cors_preflight,
    error_response,
    require_auth,
    sanitise,
)
from treesight.security.billing import get_effective_subscription, plan_capabilities

logger = logging.getLogger(__name__)

bp = func.Blueprint()

# --- Tier gating -------------------------------------------------------

_MONITORING_TIERS = {"pro", "team", "enterprise"}
_MAX_MONITORS_BY_TIER: dict[str, int] = {
    "pro": 10,
    "team": 50,
    "enterprise": 500,
}


def _check_monitoring_access(user_id: str) -> str | None:
    """Return an error message if the user cannot use monitoring, else None."""
    sub = get_effective_subscription(user_id)
    tier = sub.get("tier", "free")
    if tier not in _MONITORING_TIERS:
        return f"Scheduled monitoring requires a Pro or higher plan (current: {tier})"
    return None


def _check_monitor_limit(user_id: str) -> str | None:
    """Return an error message if the user has hit their monitor limit."""
    from treesight.monitoring import list_monitors

    sub = get_effective_subscription(user_id)
    tier = sub.get("tier", "free")
    limit = _MAX_MONITORS_BY_TIER.get(tier, 0)
    active = [m for m in list_monitors(user_id) if m.enabled]
    if len(active) >= limit:
        return f"Monitor limit reached ({limit} for {tier} plan)"
    return None


# --- Timer Trigger: scheduled monitoring check --------------------------


@bp.timer_trigger(schedule="0 0 */6 * * *", arg_name="timer", run_on_startup=False)
def monitoring_scheduler(timer: func.TimerRequest) -> None:
    """Run every 6 hours: find due monitors and kick off re-analysis."""
    from treesight.storage.cosmos import cosmos_available

    if not cosmos_available():
        logger.info("Cosmos not configured — monitoring scheduler skipped")
        return

    from treesight.monitoring import get_due_monitors

    due = get_due_monitors(batch_size=50)
    if not due:
        logger.info("Monitoring scheduler: no monitors due")
        return

    logger.info("Monitoring scheduler: %d monitors due for check", len(due))

    for monitor in due:
        try:
            _process_monitor(monitor)
        except Exception:
            logger.exception(
                "Monitoring scheduler failed for monitor=%s user=%s",
                monitor.id,
                monitor.user_id,
            )


def _process_monitor(monitor: Any) -> None:
    """Run enrichment for a single monitor and evaluate alerts.

    Uses the enrichment pipeline directly (NDVI + change detection)
    rather than launching a full Durable orchestration, since we
    already have the AOI geometry stored in the monitor record.
    """
    from treesight.monitoring import (
        advance_schedule,
        evaluate_alert,
        send_monitoring_alert,
    )
    from treesight.pipeline.enrichment import run_enrichment
    from treesight.storage.client import BlobStorageClient

    geometry = monitor.aoi_geometry
    centroid = geometry.get("centroid", [0.0, 0.0])

    if not centroid or centroid == [0.0, 0.0]:
        logger.warning("Monitor %s has no valid centroid — skipping", monitor.id)
        advance_schedule(monitor, run_id="skipped-no-centroid")
        return

    # run_enrichment expects coords as [[lon, lat], ...]
    coords = [centroid]
    storage = BlobStorageClient()

    now = datetime.now(UTC)
    run_ts = now.strftime("%Y%m%dT%H%M%SZ")

    # Delta fetch: only request scenes since the last successful monitoring
    # enrichment run so we do not re-download the full historical archive on
    # every 6-hourly check. Skip runs (for example, missing centroid) advance
    # schedule bookkeeping but must not narrow the first real enrichment
    # window.
    date_end = now.date().isoformat()
    last_run_id = getattr(monitor, "last_run_id", None)
    has_successful_monitoring_run = bool(
        monitor.last_run_at
        and isinstance(last_run_id, str)
        and last_run_id.startswith("monitoring-")
    )
    date_start = monitor.last_run_at.date().isoformat() if has_successful_monitoring_run else None

    enrichment_result = run_enrichment(
        coords=coords,
        project_name=f"monitor-{monitor.id}",
        timestamp=run_ts,
        output_container="kml-output",
        storage=storage,
        cadence="monthly",
        date_start=date_start,
        date_end=date_end,
    )

    # Extract change detection results
    change_result = enrichment_result.get("change_detection")

    # Evaluate alert thresholds
    alert = evaluate_alert(monitor, change_result)
    if alert:
        send_monitoring_alert(monitor, alert)

    # Persist the latest NDVI mean so the next delta run has an updated baseline.
    ndvi_stats: list[dict] = enrichment_result.get("ndvi_stats") or []
    valid_stats = [s for s in ndvi_stats if s and s.get("mean") is not None]
    if valid_stats:
        latest = max(valid_stats, key=lambda s: s.get("datetime", ""))
        monitor.baseline_ndvi_mean = latest["mean"]

    # Advance schedule regardless of alert
    advance_schedule(monitor, run_id=f"monitoring-{monitor.id}")
    logger.info("Monitor %s processed, alert=%s", monitor.id, alert is not None)


# --- HTTP endpoints: monitoring CRUD -----------------------------------


def list_monitors_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """GET /api/monitoring — list the user's monitors."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    from treesight.monitoring import list_monitors

    monitors = list_monitors(user_id)
    payload = [m.model_dump(mode="json") for m in monitors]
    return func.HttpResponse(
        json.dumps({"monitors": payload, "count": len(payload)}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


def create_monitor_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """POST /api/monitoring — create a new monitor for an AOI."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    # Tier check
    err = _check_monitoring_access(user_id)
    if err:
        return error_response(403, err, req=req)

    err = _check_monitor_limit(user_id)
    if err:
        return error_response(403, err, req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    aoi_name = sanitise(body.get("aoi_name", ""))
    if not aoi_name:
        return error_response(400, "aoi_name is required", req=req)

    aoi_geometry = body.get("aoi_geometry")
    if not isinstance(aoi_geometry, dict) or not aoi_geometry.get("centroid"):
        return error_response(400, "aoi_geometry with centroid is required", req=req)

    cadence_days = body.get("cadence_days", 30)
    if not isinstance(cadence_days, int) or cadence_days < 1 or cadence_days > 365:
        return error_response(400, "cadence_days must be 1–365", req=req)

    # Enforce minimum cadence based on tier
    sub = get_effective_subscription(user_id)
    tier = sub.get("tier", "free")
    caps = plan_capabilities(tier)
    if caps.get("temporal_cadence") == "seasonal" and cadence_days < 90:
        return error_response(
            403,
            "Seasonal-cadence plans require cadence_days >= 90",
            req=req,
        )

    alert_thresholds = body.get("alert_thresholds")
    if alert_thresholds is not None and not isinstance(alert_thresholds, dict):
        return error_response(400, "alert_thresholds must be a JSON object", req=req)

    # Extract email from SWA principal (userDetails holds the login email)
    alert_email = auth_claims.get("userDetails", "")

    from treesight.monitoring import create_monitor

    monitor = create_monitor(
        user_id=user_id,
        aoi_name=aoi_name,
        aoi_geometry=aoi_geometry,
        source_file=sanitise(body.get("source_file", "")),
        cadence_days=cadence_days,
        alert_thresholds=alert_thresholds,
        alert_email=alert_email,
        baseline_run_id=body.get("baseline_run_id"),
        baseline_ndvi_mean=body.get("baseline_ndvi_mean"),
    )

    return func.HttpResponse(
        json.dumps(monitor.model_dump(mode="json")),
        status_code=201,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="monitoring", methods=["GET", "POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS
)
@require_auth
def monitoring_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """Dispatch `/api/monitoring` reads and creates through one registered route."""
    if req.method == "OPTIONS":
        return cors_preflight(req)
    if req.method == "GET":
        return list_monitors_endpoint(req, auth_claims=auth_claims, user_id=user_id)
    if req.method == "POST":
        return create_monitor_endpoint(req, auth_claims=auth_claims, user_id=user_id)
    return error_response(405, "Method not allowed", req=req)


def _apply_patch(
    req: func.HttpRequest,
    monitor: Any,
    user_id: str,
) -> func.HttpResponse | None:
    """Apply PATCH fields to a monitor. Returns an error response or None on success."""
    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    if "cadence_days" in body:
        cd = body["cadence_days"]
        if not isinstance(cd, int) or cd < 1 or cd > 365:
            return error_response(400, "cadence_days must be 1\u2013365", req=req)

        sub = get_effective_subscription(user_id)
        tier = sub.get("tier", "free")
        caps = plan_capabilities(tier)
        if caps.get("temporal_cadence") == "seasonal" and cd < 90:
            return error_response(
                403,
                "Seasonal-cadence plans require cadence_days >= 90",
                req=req,
            )
        monitor.cadence_days = cd

    if "enabled" in body:
        enabled = body["enabled"]
        if not isinstance(enabled, bool):
            return error_response(400, "enabled must be a JSON boolean", req=req)
        monitor.enabled = enabled

    if "alert_thresholds" in body:
        at = body["alert_thresholds"]
        if not isinstance(at, dict):
            return error_response(400, "alert_thresholds must be a JSON object", req=req)
        from treesight.models.monitor import AlertThresholds

        monitor.alert_thresholds = AlertThresholds(**at)

    return None


@bp.route(
    route="monitoring/{monitor_id}",
    methods=["GET", "PATCH", "DELETE", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def monitor_detail_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """GET/PATCH/DELETE /api/monitoring/{monitor_id}."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    monitor_id = req.route_params.get("monitor_id", "")
    if not monitor_id:
        return error_response(400, "monitor_id is required", req=req)

    from treesight.monitoring import delete_monitor, get_monitor, update_monitor

    monitor = get_monitor(monitor_id, user_id)
    if not monitor:
        return error_response(404, "Monitor not found", req=req)

    if req.method == "GET":
        return func.HttpResponse(
            json.dumps(monitor.model_dump(mode="json")),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    if req.method == "DELETE":
        ok = delete_monitor(monitor_id, user_id)
        if not ok:
            return error_response(500, "Failed to delete monitor", req=req)
        return func.HttpResponse(
            json.dumps({"deleted": True}),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    # PATCH — update thresholds, cadence, enabled
    patch_err = _apply_patch(req, monitor, user_id)
    if patch_err:
        return patch_err

    update_monitor(monitor)
    return func.HttpResponse(
        json.dumps(monitor.model_dump(mode="json")),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
