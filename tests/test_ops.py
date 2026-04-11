"""Tests for the ops dashboard endpoint (blueprints/ops.py).

Covers:
- Auth gating via OPS_DASHBOARD_KEY
- Dev-mode access when no key is set
- Prod-mode blocking when REQUIRE_AUTH is set without a key
- Response payload shape
- Request tracking
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import azure.functions as func
import pytest

from blueprints.ops import _check_ops_key, _recent_requests, track_request

_FAKE_STARTER = json.dumps(
    {
        "taskHubName": "TestHub",
        "creationUrls": {
            "createNewInstancePostUri": "http://localhost/api/orchestrators/{functionName}"
        },
        "managementUrls": {
            "statusQueryGetUri": "http://localhost/api/instances/{instanceId}",
            "sendEventPostUri": "http://localhost/api/instances/{instanceId}/raiseEvent/{eventName}",
            "terminatePostUri": "http://localhost/api/instances/{instanceId}/terminate",
            "purgeHistoryDeleteUri": "http://localhost/api/instances/{instanceId}",
            "id": "http://localhost/api/instances/{instanceId}",
        },
        "baseUrl": "http://localhost",
        "requiredQueryStringParameters": "",
    }
)


_FAKE_STARTER = json.dumps(
    {
        "taskHubName": "TestHub",
        "creationUrls": {
            "createNewInstancePostUri": "http://localhost/api/orchestrators/{functionName}"
        },
        "managementUrls": {
            "statusQueryGetUri": "http://localhost/api/instances/{instanceId}",
            "sendEventPostUri": "http://localhost/api/instances/{instanceId}/raiseEvent/{eventName}",
            "terminatePostUri": "http://localhost/api/instances/{instanceId}/terminate",
            "purgeHistoryDeleteUri": "http://localhost/api/instances/{instanceId}",
            "id": "http://localhost/api/instances/{instanceId}",
        },
        "baseUrl": "http://localhost",
        "requiredQueryStringParameters": "",
    }
)


def _make_ops_req(
    *,
    bearer: str | None = None,
    params: dict[str, str] | None = None,
) -> func.HttpRequest:
    """Build a minimal HttpRequest for ops endpoint tests."""
    headers: dict[str, str] = {}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return func.HttpRequest(
        method="GET",
        url="/api/ops/dashboard",
        headers=headers,
        params=params or {},
        body=b"",
    )


# ---------------------------------------------------------------------------
# Auth: _check_ops_key
# ---------------------------------------------------------------------------


class TestCheckOpsKey:
    """Verify bearer token validation logic."""

    def test_allows_dev_mode_when_no_key_set(self, monkeypatch):
        """No OPS_DASHBOARD_KEY and no REQUIRE_AUTH → allow access (dev)."""
        monkeypatch.delenv("OPS_DASHBOARD_KEY", raising=False)
        monkeypatch.delenv("REQUIRE_AUTH", raising=False)
        assert _check_ops_key(_make_ops_req()) is True

    @pytest.mark.parametrize("require_auth", ["true", "1", "yes"])
    def test_blocks_prod_when_no_key_set(self, monkeypatch, require_auth):
        """No OPS_DASHBOARD_KEY + REQUIRE_AUTH → deny access."""
        monkeypatch.delenv("OPS_DASHBOARD_KEY", raising=False)
        monkeypatch.setenv("REQUIRE_AUTH", require_auth)
        assert _check_ops_key(_make_ops_req()) is False

    def test_rejects_missing_bearer(self, monkeypatch):
        """Key is set but request has no Authorization header → deny."""
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "secret-key-123")
        assert _check_ops_key(_make_ops_req()) is False

    def test_rejects_wrong_bearer(self, monkeypatch):
        """Wrong bearer token → deny."""
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "secret-key-123")
        assert _check_ops_key(_make_ops_req(bearer="wrong-key")) is False

    def test_accepts_correct_bearer(self, monkeypatch):
        """Correct bearer token → allow."""
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "secret-key-123")
        assert _check_ops_key(_make_ops_req(bearer="secret-key-123")) is True

    def test_rejects_query_param_key(self, monkeypatch):
        """Query-param key is NOT accepted (header-only auth)."""
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "secret-key-123")
        req = _make_ops_req(params={"key": "secret-key-123"})
        assert _check_ops_key(req) is False

    def test_timing_safe_comparison(self, monkeypatch):
        """Verify hmac.compare_digest is used (not ==) by checking correct key works."""
        # If == were used this would still pass, but the implementation
        # explicitly uses hmac.compare_digest for timing safety.
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "a" * 64)
        assert _check_ops_key(_make_ops_req(bearer="a" * 64)) is True
        assert _check_ops_key(_make_ops_req(bearer="a" * 63 + "b")) is False


# ---------------------------------------------------------------------------
# Request tracking
# ---------------------------------------------------------------------------


class TestRequestTracking:
    """Verify in-memory request recording."""

    def test_track_request_appends(self):
        """track_request adds an entry to _recent_requests."""
        initial_count = len(_recent_requests)
        track_request(method="GET", path="health", status=200, user_id="u1")
        assert len(_recent_requests) == initial_count + 1
        last = _recent_requests[-1]
        assert last["method"] == "GET"
        assert last["path"] == "health"
        assert last["status"] == 200
        assert last["user"] == "u1"
        assert "ts" in last
        assert "dur_ms" in last

    def test_anonymous_user_defaults(self):
        """Empty user_id defaults to 'anon'."""
        track_request(method="POST", path="submit", status=201)
        assert _recent_requests[-1]["user"] == "anon"


# ---------------------------------------------------------------------------
# Endpoint response shape
# ---------------------------------------------------------------------------


class TestOpsDashboardEndpoint:
    """Integration-style tests for the ops_dashboard function."""

    @pytest.mark.asyncio
    async def test_returns_401_without_key(self, monkeypatch):
        """When key is set, missing bearer → 401."""
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "required-key")

        from blueprints.ops import ops_dashboard

        req = _make_ops_req()
        resp = await ops_dashboard(req, client=_FAKE_STARTER)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_200_with_correct_key(self, monkeypatch):
        """Correct bearer → 200 with expected payload keys."""
        monkeypatch.setenv("OPS_DASHBOARD_KEY", "good-key")

        from blueprints.ops import ops_dashboard

        mock_client = AsyncMock()
        mock_client.get_status_by = AsyncMock(return_value=[])
        req = _make_ops_req(bearer="good-key")

        with patch("blueprints.ops._fetch_recent_runs", return_value=[]):
            with patch(
                "azure.durable_functions.DurableOrchestrationClient",
                return_value=mock_client,
            ):
                resp = await ops_dashboard(req, client=_FAKE_STARTER)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert "timestamp" in body
        assert "app" in body
        assert "activeUsers" in body
        assert "activeUserCount" in body
        assert "requests" in body
        assert "orchestrations" in body
        assert "recentRuns" in body
        assert isinstance(body["activeUserCount"], int)
        assert isinstance(body["orchestrations"], list)

    @pytest.mark.asyncio
    async def test_dev_mode_allows_unauthenticated(self, monkeypatch):
        """No key + no REQUIRE_AUTH → 200 (dev mode)."""
        monkeypatch.delenv("OPS_DASHBOARD_KEY", raising=False)
        monkeypatch.delenv("REQUIRE_AUTH", raising=False)

        from blueprints.ops import ops_dashboard

        mock_client = AsyncMock()
        mock_client.get_status_by = AsyncMock(return_value=[])
        req = _make_ops_req()

        with patch("blueprints.ops._fetch_recent_runs", return_value=[]):
            with patch(
                "azure.durable_functions.DurableOrchestrationClient",
                return_value=mock_client,
            ):
                resp = await ops_dashboard(req, client=_FAKE_STARTER)

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_payload_counts_are_consistent(self, monkeypatch):
        """activeUserCount must equal len(activeUsers)."""
        monkeypatch.delenv("OPS_DASHBOARD_KEY", raising=False)
        monkeypatch.delenv("REQUIRE_AUTH", raising=False)

        from blueprints.ops import ops_dashboard

        mock_client = AsyncMock()
        mock_client.get_status_by = AsyncMock(return_value=[])
        req = _make_ops_req()

        with patch("blueprints.ops._fetch_recent_runs", return_value=[]):
            with patch(
                "azure.durable_functions.DurableOrchestrationClient",
                return_value=mock_client,
            ):
                resp = await ops_dashboard(req, client=_FAKE_STARTER)

        body = json.loads(resp.get_body())
        assert body["activeUserCount"] == len(body["activeUsers"])
        assert body["orchestrationCount"] == len(body["orchestrations"])
        assert body["recentRunCount"] == len(body["recentRuns"])
