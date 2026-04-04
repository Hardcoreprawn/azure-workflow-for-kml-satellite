"""Monitoring CRUD and alert evaluation (§3.1 — scheduled monitoring).

Provides helpers to create, query, and update monitoring subscriptions
in the ``monitors`` Cosmos container, plus alert evaluation logic that
compares pipeline enrichment results against user-configured thresholds.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from treesight.models.monitor import AlertThresholds, MonitorRecord

logger = logging.getLogger(__name__)

MONITORS_CONTAINER = "monitors"

# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def create_monitor(
    user_id: str,
    aoi_name: str,
    aoi_geometry: dict[str, Any],
    *,
    source_file: str = "",
    cadence_days: int = 30,
    alert_thresholds: dict[str, Any] | None = None,
    alert_email: str = "",
    baseline_run_id: str | None = None,
    baseline_ndvi_mean: float | None = None,
) -> MonitorRecord:
    """Create and persist a new monitoring subscription."""
    from treesight.storage.cosmos import upsert_item

    now = datetime.now(UTC)
    monitor = MonitorRecord(
        id=str(uuid.uuid4()),
        user_id=user_id,
        aoi_name=aoi_name,
        source_file=source_file,
        aoi_geometry=aoi_geometry,
        cadence_days=cadence_days,
        next_check_at=now + timedelta(days=cadence_days),
        alert_thresholds=AlertThresholds(**(alert_thresholds or {})),
        alert_email=alert_email,
        baseline_run_id=baseline_run_id,
        baseline_ndvi_mean=baseline_ndvi_mean,
        created_at=now,
        updated_at=now,
    )
    upsert_item(MONITORS_CONTAINER, monitor.to_cosmos())
    logger.info("Monitor created id=%s user=%s aoi=%s", monitor.id, user_id, aoi_name)
    return monitor


def get_monitor(monitor_id: str, user_id: str) -> MonitorRecord | None:
    """Read a single monitor by id and partition key."""
    from treesight.storage.cosmos import read_item

    doc = read_item(MONITORS_CONTAINER, monitor_id, user_id)
    if not doc:
        return None
    return MonitorRecord(**{k: v for k, v in doc.items() if not k.startswith("_")})


def list_monitors(user_id: str) -> list[MonitorRecord]:
    """List all monitors for a user."""
    from treesight.storage.cosmos import query_items

    docs = query_items(
        MONITORS_CONTAINER,
        "SELECT * FROM c WHERE c.user_id = @uid ORDER BY c.created_at DESC",
        parameters=[{"name": "@uid", "value": user_id}],
        partition_key=user_id,
    )
    results: list[MonitorRecord] = []
    for doc in docs:
        clean = {k: v for k, v in doc.items() if not k.startswith("_")}
        results.append(MonitorRecord(**clean))
    return results


def update_monitor(monitor: MonitorRecord) -> MonitorRecord:
    """Persist an updated monitor record."""
    from treesight.storage.cosmos import upsert_item

    monitor.updated_at = datetime.now(UTC)
    upsert_item(MONITORS_CONTAINER, monitor.to_cosmos())
    return monitor


def disable_monitor(monitor_id: str, user_id: str) -> bool:
    """Disable a monitor. Returns True if found and disabled."""
    monitor = get_monitor(monitor_id, user_id)
    if not monitor:
        return False
    monitor.enabled = False
    update_monitor(monitor)
    logger.info("Monitor disabled id=%s user=%s", monitor_id, user_id)
    return True


def delete_monitor(monitor_id: str, user_id: str) -> bool:
    """Delete a monitor. Returns True if found and deleted."""
    from treesight.storage.cosmos import delete_item

    try:
        delete_item(MONITORS_CONTAINER, monitor_id, user_id)
        logger.info("Monitor deleted id=%s user=%s", monitor_id, user_id)
        return True
    except Exception:
        logger.warning("Monitor delete failed id=%s user=%s", monitor_id, user_id, exc_info=True)
        return False


def get_due_monitors(batch_size: int = 50) -> list[MonitorRecord]:
    """Query all monitors that are enabled and due for a check.

    Cross-partition query — runs on the Timer Trigger schedule (not user-facing).
    """
    from treesight.storage.cosmos import query_items

    now_iso = datetime.now(UTC).isoformat()
    docs = query_items(
        MONITORS_CONTAINER,
        (
            "SELECT * FROM c"
            " WHERE c.enabled = true AND c.next_check_at <= @now"
            " ORDER BY c.next_check_at ASC"
            " OFFSET 0 LIMIT @limit"
        ),
        parameters=[
            {"name": "@now", "value": now_iso},
            {"name": "@limit", "value": batch_size},
        ],
    )
    results: list[MonitorRecord] = []
    for doc in docs:
        clean = {k: v for k, v in doc.items() if not k.startswith("_")}
        results.append(MonitorRecord(**clean))
    return results


def advance_schedule(monitor: MonitorRecord, run_id: str) -> MonitorRecord:
    """Advance the monitor's schedule after a successful run."""
    now = datetime.now(UTC)
    monitor.last_run_id = run_id
    monitor.last_run_at = now
    monitor.next_check_at = now + timedelta(days=monitor.cadence_days)
    return update_monitor(monitor)


# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------


def evaluate_alert(
    monitor: MonitorRecord,
    change_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Check change metrics against monitor thresholds.

    Returns an alert payload dict if a threshold is breached, else None.
    """
    if not change_result:
        return None

    thresholds = monitor.alert_thresholds
    breaches: list[str] = []

    loss_pct = change_result.get("loss_pct", 0.0)
    gain_pct = change_result.get("gain_pct", 0.0)
    ndvi_mean = change_result.get("mean_delta")

    if thresholds.loss_pct is not None and loss_pct >= thresholds.loss_pct:
        breaches.append(
            f"Vegetation loss {loss_pct:.1f}% exceeds threshold {thresholds.loss_pct:.1f}%"
        )

    if thresholds.gain_pct is not None and gain_pct >= thresholds.gain_pct:
        breaches.append(
            f"Vegetation gain {gain_pct:.1f}% exceeds threshold {thresholds.gain_pct:.1f}%"
        )

    if (
        thresholds.ndvi_mean_drop is not None
        and ndvi_mean is not None
        and ndvi_mean < -thresholds.ndvi_mean_drop
    ):
        breaches.append(
            f"Mean NDVI dropped by {abs(ndvi_mean):.3f} "
            f"(threshold: {thresholds.ndvi_mean_drop:.3f})"
        )

    if not breaches:
        return None

    return {
        "monitor_id": monitor.id,
        "user_id": monitor.user_id,
        "aoi_name": monitor.aoi_name,
        "breaches": breaches,
        "loss_pct": loss_pct,
        "gain_pct": gain_pct,
        "mean_delta": ndvi_mean,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def send_monitoring_alert(
    monitor: MonitorRecord,
    alert: dict[str, Any],
) -> bool:
    """Send an alert email for a breached monitoring threshold."""
    import html as html_mod

    from treesight.email import send_email

    if not monitor.alert_email:
        logger.info("No alert_email for monitor=%s — skipping", monitor.id)
        return False

    aoi = html_mod.escape(monitor.aoi_name)
    breach_lines = "".join(f"<li>{html_mod.escape(b)}</li>" for b in alert.get("breaches", []))
    subject = f"Canopex Alert: {monitor.aoi_name} — vegetation change detected"
    body_html = (
        f"<h2>Monitoring Alert: {aoi}</h2>"
        "<p>Canopex scheduled monitoring has detected vegetation changes "
        "that exceed your configured thresholds:</p>"
        f"<ul>{breach_lines}</ul>"
        "<p><strong>Details:</strong></p>"
        "<table>"
        f"<tr><td>Loss:</td><td>{alert.get('loss_pct', 0):.1f}%</td></tr>"
        f"<tr><td>Gain:</td><td>{alert.get('gain_pct', 0):.1f}%</td></tr>"
        f"<tr><td>Mean NDVI delta:</td><td>{alert.get('mean_delta', 'N/A')}</td></tr>"
        "</table>"
        "<p>Log in to Canopex to view the full analysis.</p>"
    )
    body_text = (
        f"Monitoring Alert: {monitor.aoi_name}\n\n"
        "Threshold breaches:\n"
        + "\n".join(f"  - {b}" for b in alert.get("breaches", []))
        + f"\n\nLoss: {alert.get('loss_pct', 0):.1f}%"
        f"\nGain: {alert.get('gain_pct', 0):.1f}%"
        f"\nMean NDVI delta: {alert.get('mean_delta', 'N/A')}"
    )

    sent = send_email(
        monitor.alert_email,
        subject,
        body_html,
        body_text,
        verified_recipients={monitor.alert_email},
    )
    if sent:
        monitor.alert_count += 1
        update_monitor(monitor)
        logger.info(
            "Alert sent monitor=%s user=%s email=%s",
            monitor.id,
            monitor.user_id,
            monitor.alert_email,
        )
    return sent
