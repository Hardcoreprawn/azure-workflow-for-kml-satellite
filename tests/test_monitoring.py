"""Tests for scheduled monitoring (§3.1) — model, CRUD, alerts, and endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import azure.functions as func
import pytest

from tests.conftest import TEST_ORIGIN, encode_test_principal, make_test_request

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_GEOMETRY: dict[str, Any] = {
    "centroid": [36.805, -1.305],
    "bbox": [36.8, -1.31, 36.81, -1.3],
    "exterior_coords": [
        [36.8, -1.3],
        [36.81, -1.3],
        [36.81, -1.31],
        [36.8, -1.31],
        [36.8, -1.3],
    ],
}


@pytest.fixture()
def _mock_cosmos():
    """Patch Cosmos CRUD with in-memory dicts."""
    store: dict[str, dict[str, Any]] = {}

    def _upsert(container: str, item: dict[str, Any]) -> dict[str, Any]:
        key = f"{container}:{item['id']}"
        store[key] = dict(item)
        return item

    def _read(container: str, item_id: str, partition_key: str) -> dict[str, Any] | None:
        return store.get(f"{container}:{item_id}")

    def _query(
        container: str,
        query: str,
        parameters: list | None = None,
        partition_key: str | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        for k, v in store.items():
            if not k.startswith(f"{container}:"):
                continue
            # simple filter by user_id if present in params
            if parameters:
                uid = next((p["value"] for p in parameters if p["name"] == "@uid"), None)
                if uid and v.get("user_id") != uid:
                    continue
            results.append(v)
        return results

    def _delete(container: str, item_id: str, partition_key: str) -> None:
        store.pop(f"{container}:{item_id}", None)

    with (
        patch("treesight.storage.cosmos.upsert_item", side_effect=_upsert),
        patch("treesight.storage.cosmos.read_item", side_effect=_read),
        patch("treesight.storage.cosmos.query_items", side_effect=_query),
        patch("treesight.storage.cosmos.delete_item", side_effect=_delete),
        patch("treesight.storage.cosmos.cosmos_available", return_value=True),
    ):
        yield store


@pytest.fixture()
def _mock_auth():
    """Bypass auth for endpoint tests — SWA header parsing is exercised via request headers."""
    yield


@pytest.fixture()
def _mock_pro_subscription():
    """Make the test user appear as a Pro subscriber."""
    sub = {"tier": "pro", "status": "active", "emulated": False}
    with patch(
        "blueprints.monitoring.get_effective_subscription",
        return_value=sub,
    ):
        yield


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestMonitorRecord:
    def test_create_with_defaults(self):
        from treesight.models.monitor import MonitorRecord

        m = MonitorRecord(id="m1", user_id="u1", aoi_name="Forest A")
        assert m.enabled is True
        assert m.cadence_days == 30
        assert m.alert_thresholds.loss_pct == 5.0

    def test_to_cosmos_serialisation(self):
        from treesight.models.monitor import MonitorRecord

        now = datetime.now(UTC)
        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="Forest A",
            created_at=now,
            updated_at=now,
        )
        doc = m.to_cosmos()
        assert isinstance(doc, dict)
        assert doc["id"] == "m1"
        assert doc["aoi_name"] == "Forest A"
        # datetime serialised as ISO string
        assert isinstance(doc["created_at"], str)

    def test_custom_thresholds(self):
        from treesight.models.monitor import AlertThresholds, MonitorRecord

        m = MonitorRecord(
            id="m2",
            user_id="u1",
            aoi_name="Block B",
            alert_thresholds=AlertThresholds(loss_pct=10.0, ndvi_mean_drop=0.2),
        )
        assert m.alert_thresholds.loss_pct == 10.0
        assert m.alert_thresholds.ndvi_mean_drop == 0.2
        assert m.alert_thresholds.gain_pct is None


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestMonitoringCRUD:
    def test_create_monitor(self, _mock_cosmos):
        from treesight.monitoring import create_monitor

        m = create_monitor(
            user_id="user-1",
            aoi_name="Test AOI",
            aoi_geometry=_SAMPLE_GEOMETRY,
            cadence_days=30,
            alert_email="user@example.com",
        )
        assert m.user_id == "user-1"
        assert m.aoi_name == "Test AOI"
        assert m.enabled is True
        assert m.cadence_days == 30
        assert m.next_check_at is not None
        assert m.created_at is not None

    def test_get_monitor(self, _mock_cosmos):
        from treesight.monitoring import create_monitor, get_monitor

        created = create_monitor(
            user_id="user-1",
            aoi_name="AOI X",
            aoi_geometry=_SAMPLE_GEOMETRY,
        )
        fetched = get_monitor(created.id, "user-1")
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.aoi_name == "AOI X"

    def test_get_nonexistent_monitor(self, _mock_cosmos):
        from treesight.monitoring import get_monitor

        assert get_monitor("nonexistent", "user-1") is None

    def test_list_monitors(self, _mock_cosmos):
        from treesight.monitoring import create_monitor, list_monitors

        create_monitor(user_id="user-1", aoi_name="AOI A", aoi_geometry=_SAMPLE_GEOMETRY)
        create_monitor(user_id="user-1", aoi_name="AOI B", aoi_geometry=_SAMPLE_GEOMETRY)
        create_monitor(user_id="user-2", aoi_name="AOI C", aoi_geometry=_SAMPLE_GEOMETRY)

        monitors = list_monitors("user-1")
        assert len(monitors) == 2
        names = {m.aoi_name for m in monitors}
        assert names == {"AOI A", "AOI B"}

    def test_disable_monitor(self, _mock_cosmos):
        from treesight.monitoring import create_monitor, disable_monitor, get_monitor

        created = create_monitor(
            user_id="user-1",
            aoi_name="AOI D",
            aoi_geometry=_SAMPLE_GEOMETRY,
        )
        assert disable_monitor(created.id, "user-1") is True
        fetched = get_monitor(created.id, "user-1")
        assert fetched is not None
        assert fetched.enabled is False

    def test_disable_nonexistent_monitor(self, _mock_cosmos):
        from treesight.monitoring import disable_monitor

        assert disable_monitor("nonexistent", "user-1") is False

    def test_delete_monitor(self, _mock_cosmos):
        from treesight.monitoring import create_monitor, delete_monitor, get_monitor

        created = create_monitor(
            user_id="user-1",
            aoi_name="AOI E",
            aoi_geometry=_SAMPLE_GEOMETRY,
        )
        assert delete_monitor(created.id, "user-1") is True
        assert get_monitor(created.id, "user-1") is None

    def test_advance_schedule(self, _mock_cosmos):
        from treesight.monitoring import advance_schedule, create_monitor

        created = create_monitor(
            user_id="user-1",
            aoi_name="AOI F",
            aoi_geometry=_SAMPLE_GEOMETRY,
            cadence_days=7,
        )
        old_next = created.next_check_at
        updated = advance_schedule(created, run_id="run-123")
        assert updated.last_run_id == "run-123"
        assert updated.last_run_at is not None
        assert updated.next_check_at > old_next

    def test_get_due_monitors(self, _mock_cosmos):
        from treesight.monitoring import create_monitor, get_due_monitors

        # Create a monitor with next_check_at in the past
        m = create_monitor(
            user_id="user-1",
            aoi_name="AOI Past Due",
            aoi_geometry=_SAMPLE_GEOMETRY,
        )
        # Manually set next_check_at to the past
        m.next_check_at = datetime.now(UTC) - timedelta(hours=1)
        from treesight.monitoring import update_monitor

        update_monitor(m)

        # The simple mock query returns all enabled — real Cosmos filters by next_check_at
        due = get_due_monitors()
        assert len(due) >= 1


# ---------------------------------------------------------------------------
# Alert evaluation tests
# ---------------------------------------------------------------------------


class TestAlertEvaluation:
    def test_no_change_result(self):
        from treesight.models.monitor import MonitorRecord
        from treesight.monitoring import evaluate_alert

        m = MonitorRecord(id="m1", user_id="u1", aoi_name="AOI")
        assert evaluate_alert(m, None) is None

    def test_below_threshold_no_alert(self):
        from treesight.models.monitor import AlertThresholds, MonitorRecord
        from treesight.monitoring import evaluate_alert

        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="AOI",
            alert_thresholds=AlertThresholds(loss_pct=5.0),
        )
        change = {"loss_pct": 2.0, "gain_pct": 1.0, "mean_delta": -0.02}
        assert evaluate_alert(m, change) is None

    def test_loss_threshold_breach(self):
        from treesight.models.monitor import AlertThresholds, MonitorRecord
        from treesight.monitoring import evaluate_alert

        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="AOI",
            alert_thresholds=AlertThresholds(loss_pct=5.0),
        )
        change = {"loss_pct": 8.3, "gain_pct": 0.5, "mean_delta": -0.05}
        alert = evaluate_alert(m, change)
        assert alert is not None
        assert len(alert["breaches"]) == 1
        assert "8.3%" in alert["breaches"][0]

    def test_ndvi_mean_drop_breach(self):
        from treesight.models.monitor import AlertThresholds, MonitorRecord
        from treesight.monitoring import evaluate_alert

        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="AOI",
            alert_thresholds=AlertThresholds(loss_pct=50.0, ndvi_mean_drop=0.1),
        )
        change = {"loss_pct": 2.0, "gain_pct": 0.5, "mean_delta": -0.15}
        alert = evaluate_alert(m, change)
        assert alert is not None
        assert any("NDVI" in b for b in alert["breaches"])

    def test_multiple_breaches(self):
        from treesight.models.monitor import AlertThresholds, MonitorRecord
        from treesight.monitoring import evaluate_alert

        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="AOI",
            alert_thresholds=AlertThresholds(loss_pct=5.0, gain_pct=10.0, ndvi_mean_drop=0.05),
        )
        change = {"loss_pct": 7.0, "gain_pct": 12.0, "mean_delta": -0.08}
        alert = evaluate_alert(m, change)
        assert alert is not None
        assert len(alert["breaches"]) == 3

    def test_gain_only_breach(self):
        from treesight.models.monitor import AlertThresholds, MonitorRecord
        from treesight.monitoring import evaluate_alert

        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="AOI",
            alert_thresholds=AlertThresholds(loss_pct=50.0, gain_pct=5.0),
        )
        change = {"loss_pct": 1.0, "gain_pct": 8.0, "mean_delta": 0.03}
        alert = evaluate_alert(m, change)
        assert alert is not None
        assert len(alert["breaches"]) == 1
        assert "gain" in alert["breaches"][0].lower()


# ---------------------------------------------------------------------------
# Alert sending tests
# ---------------------------------------------------------------------------


class TestAlertSending:
    def test_send_alert_no_email(self, _mock_cosmos):
        from treesight.models.monitor import MonitorRecord
        from treesight.monitoring import send_monitoring_alert

        m = MonitorRecord(id="m1", user_id="u1", aoi_name="AOI", alert_email="")
        alert = {"breaches": ["Loss 8%"], "loss_pct": 8.0, "gain_pct": 0.0, "mean_delta": -0.05}
        assert send_monitoring_alert(m, alert) is False

    def test_send_alert_success(self, _mock_cosmos):
        from treesight.models.monitor import MonitorRecord
        from treesight.monitoring import send_monitoring_alert

        m = MonitorRecord(
            id="m1",
            user_id="u1",
            aoi_name="Forest Block A",
            alert_email="user@test.com",
        )
        alert = {
            "breaches": ["Vegetation loss 8.3% exceeds threshold 5.0%"],
            "loss_pct": 8.3,
            "gain_pct": 0.5,
            "mean_delta": -0.05,
        }

        with patch("treesight.email.send_email", return_value=True) as mock_send:
            result = send_monitoring_alert(m, alert)

        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "user@test.com"  # to
        assert "Forest Block A" in call_args[0][1]  # subject
        assert "8.3%" in call_args[0][2]  # body_html


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestMonitoringEndpoints:
    def test_list_monitors_empty(self, _mock_cosmos, _mock_auth):
        from blueprints.monitoring import monitoring_endpoint

        req = make_test_request("/api/monitoring", method="GET")
        resp = monitoring_endpoint(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["count"] == 0
        assert data["monitors"] == []

    def test_create_monitor_success(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitoring_endpoint

        body = {
            "aoi_name": "Test Forest",
            "aoi_geometry": _SAMPLE_GEOMETRY,
            "cadence_days": 30,
        }
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        assert resp.status_code == 201
        data = json.loads(resp.get_body())
        assert data["aoi_name"] == "Test Forest"
        assert data["cadence_days"] == 30
        assert data["enabled"] is True

    def test_create_monitor_no_aoi_name(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitoring_endpoint

        body = {"aoi_geometry": _SAMPLE_GEOMETRY}
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        assert resp.status_code == 400

    def test_create_monitor_no_geometry(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitoring_endpoint

        body = {"aoi_name": "Test"}
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        assert resp.status_code == 400

    def test_create_monitor_invalid_cadence(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitoring_endpoint

        body = {
            "aoi_name": "Test",
            "aoi_geometry": _SAMPLE_GEOMETRY,
            "cadence_days": 0,
        }
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        assert resp.status_code == 400

    def test_create_monitor_free_tier_rejected(self, _mock_cosmos, _mock_auth):
        from blueprints.monitoring import monitoring_endpoint

        with patch(
            "blueprints.monitoring.get_effective_subscription",
            return_value={"tier": "free", "status": "active"},
        ):
            body = {
                "aoi_name": "Test",
                "aoi_geometry": _SAMPLE_GEOMETRY,
            }
            req = make_test_request("/api/monitoring", method="POST", body=body)
            resp = monitoring_endpoint(req)
            assert resp.status_code == 403

    def test_get_monitor_detail(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitor_detail_endpoint, monitoring_endpoint

        # Create first
        body = {
            "aoi_name": "Detail Test",
            "aoi_geometry": _SAMPLE_GEOMETRY,
        }
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        data = json.loads(resp.get_body())
        monitor_id = data["id"]

        # Get detail
        req2 = func.HttpRequest(
            method="GET",
            url=f"/api/monitoring/{monitor_id}",
            headers={
                "Origin": TEST_ORIGIN,
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(),
            },
            params={},
            route_params={"monitor_id": monitor_id},
            body=b"",
        )
        resp2 = monitor_detail_endpoint(req2)
        assert resp2.status_code == 200
        detail = json.loads(resp2.get_body())
        assert detail["aoi_name"] == "Detail Test"

    def test_patch_monitor(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitor_detail_endpoint, monitoring_endpoint

        # Create
        body = {"aoi_name": "Patch Test", "aoi_geometry": _SAMPLE_GEOMETRY}
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        data = json.loads(resp.get_body())
        monitor_id = data["id"]

        # Patch
        patch_body = json.dumps({"cadence_days": 14, "enabled": False}).encode()
        req2 = func.HttpRequest(
            method="PATCH",
            url=f"/api/monitoring/{monitor_id}",
            headers={
                "Origin": TEST_ORIGIN,
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(),
                "Content-Type": "application/json",
            },
            params={},
            route_params={"monitor_id": monitor_id},
            body=patch_body,
        )
        resp2 = monitor_detail_endpoint(req2)
        assert resp2.status_code == 200
        updated = json.loads(resp2.get_body())
        assert updated["cadence_days"] == 14
        assert updated["enabled"] is False

    def test_delete_monitor(self, _mock_cosmos, _mock_auth, _mock_pro_subscription):
        from blueprints.monitoring import monitor_detail_endpoint, monitoring_endpoint

        # Create
        body = {"aoi_name": "Delete Test", "aoi_geometry": _SAMPLE_GEOMETRY}
        req = make_test_request("/api/monitoring", method="POST", body=body)
        resp = monitoring_endpoint(req)
        data = json.loads(resp.get_body())
        monitor_id = data["id"]

        # Delete
        req2 = func.HttpRequest(
            method="DELETE",
            url=f"/api/monitoring/{monitor_id}",
            headers={
                "Origin": TEST_ORIGIN,
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(),
            },
            params={},
            route_params={"monitor_id": monitor_id},
            body=b"",
        )
        resp2 = monitor_detail_endpoint(req2)
        assert resp2.status_code == 200
        assert json.loads(resp2.get_body())["deleted"] is True

    def test_get_nonexistent_monitor_404(self, _mock_cosmos, _mock_auth):
        from blueprints.monitoring import monitor_detail_endpoint

        req = func.HttpRequest(
            method="GET",
            url="/api/monitoring/nonexistent",
            headers={
                "Origin": TEST_ORIGIN,
                "X-MS-CLIENT-PRINCIPAL": encode_test_principal(),
            },
            params={},
            route_params={"monitor_id": "nonexistent"},
            body=b"",
        )
        resp = monitor_detail_endpoint(req)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Timer Trigger tests
# ---------------------------------------------------------------------------


class TestMonitoringScheduler:
    def test_scheduler_no_cosmos(self):
        from blueprints.monitoring import monitoring_scheduler

        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            timer = MagicMock(spec=func.TimerRequest)
            timer.past_due = False
            monitoring_scheduler(timer)  # should return without error

    def test_scheduler_no_due_monitors(self, _mock_cosmos):
        from blueprints.monitoring import monitoring_scheduler

        timer = MagicMock(spec=func.TimerRequest)
        timer.past_due = False
        monitoring_scheduler(timer)  # empty store, nothing due

    def test_process_monitor_no_centroid(self, _mock_cosmos):
        from treesight.monitoring import create_monitor

        m = create_monitor(
            user_id="user-1",
            aoi_name="No Centroid",
            aoi_geometry={"centroid": [0.0, 0.0]},
        )

        from blueprints.monitoring import _process_monitor

        with patch("treesight.monitoring.advance_schedule") as mock_advance:
            _process_monitor(m)
            mock_advance.assert_called_once()
            assert mock_advance.call_args[1]["run_id"] == "skipped-no-centroid"

    def test_process_monitor_with_enrichment(self, _mock_cosmos):
        from treesight.monitoring import create_monitor

        m = create_monitor(
            user_id="user-1",
            aoi_name="Enrichment Test",
            aoi_geometry=_SAMPLE_GEOMETRY,
            alert_email="test@example.com",
        )

        mock_enrichment = {
            "change_detection": {
                "loss_pct": 8.0,
                "gain_pct": 1.0,
                "mean_delta": -0.12,
            }
        }

        from blueprints.monitoring import _process_monitor

        with (
            patch(
                "treesight.pipeline.enrichment.run_enrichment",
                return_value=mock_enrichment,
            ),
            patch("treesight.storage.client.BlobStorageClient"),
            patch("treesight.email.send_email", return_value=True),
        ):
            _process_monitor(m)

    def test_cors_preflight_monitoring(self, _mock_auth):
        from blueprints.monitoring import monitoring_endpoint

        req = make_test_request("/api/monitoring", method="OPTIONS")
        resp = monitoring_endpoint(req)
        assert resp.status_code == 204
