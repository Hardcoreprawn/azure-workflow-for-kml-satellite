"""Tests for the SWA managed API functions (§2B.2).

These tests verify the SWA API function logic — SAS token minting, status
polling, analysis history, and billing endpoints — without requiring the
Azure Functions runtime.  We import the module directly and call the helper
functions + route handlers.

Auth is handled by SWA built-in custom auth (x-ms-client-principal header).
"""

from __future__ import annotations

import base64
import datetime
import json
import sys
import typing
import unittest.mock
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add the SWA API directory to sys.path so we can import it
_api_dir = str(Path(__file__).resolve().parent.parent / "website" / "api")
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

# We import the SWA function_app under an alias to avoid collision
# with the root-level function_app.py.
_SWA_MODULE_NAME = "swa_function_app"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _swa_env(monkeypatch):
    """Set environment variables for the SWA API module."""
    monkeypatch.setenv("STORAGE_ACCOUNT_NAME", "teststorage")
    monkeypatch.setenv("INPUT_CONTAINER", "kml-input")
    monkeypatch.setenv("SAS_TOKEN_EXPIRY_MINUTES", "15")


@pytest.fixture()
def _reload_module(_swa_env):
    """Force re-import of the SWA API module to pick up env vars."""
    import importlib.util

    # Remove any previous cached version
    sys.modules.pop(_SWA_MODULE_NAME, None)
    spec = importlib.util.spec_from_file_location(
        _SWA_MODULE_NAME, Path(_api_dir) / "function_app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_SWA_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    mod._blob_service = None
    return mod


def _encode_principal(
    user_id: str = "user-123",
    user_details: str = "user@example.com",
    identity_provider: str = "aad",
    user_roles: list[str] | None = None,
) -> str:
    """Build a Base64-encoded x-ms-client-principal header value."""
    principal = {
        "identityProvider": identity_provider,
        "userId": user_id,
        "userDetails": user_details,
        "userRoles": user_roles or ["anonymous", "authenticated"],
    }
    return base64.b64encode(json.dumps(principal).encode()).decode()


def _mock_request(
    method: str = "POST",
    url: str = "https://example.com/api/upload/token",
    headers: dict | None = None,
    body: bytes | None = None,
    route_params: dict | None = None,
    params: dict | None = None,
) -> MagicMock:
    """Build a mock HttpRequest."""
    req = MagicMock()
    req.method = method
    req.url = url
    req.headers = headers or {}
    req.get_body.return_value = body or b""
    req.route_params = route_params or {}
    req.params = params or {}
    return req


def _auth_headers(user_id: str = "user-123", **kwargs) -> dict:
    """Build headers dict with a valid x-ms-client-principal."""
    return {"x-ms-client-principal": _encode_principal(user_id=user_id, **kwargs)}


# ---------------------------------------------------------------------------
# Client principal parsing
# ---------------------------------------------------------------------------


class TestClientPrincipalParsing:
    """Tests for ``_parse_client_principal``."""

    def test_rejects_missing_header(self, _reload_module):
        mod = _reload_module
        req = _mock_request(headers={})
        with pytest.raises(ValueError, match="Missing"):
            mod._parse_client_principal(req)

    def test_rejects_empty_header(self, _reload_module):
        mod = _reload_module
        req = _mock_request(headers={"x-ms-client-principal": ""})
        with pytest.raises(ValueError, match="Missing"):
            mod._parse_client_principal(req)

    def test_rejects_invalid_base64(self, _reload_module):
        mod = _reload_module
        req = _mock_request(headers={"x-ms-client-principal": "not-base64!!!"})
        with pytest.raises(ValueError, match="Malformed"):
            mod._parse_client_principal(req)

    def test_rejects_invalid_json(self, _reload_module):
        mod = _reload_module
        encoded = base64.b64encode(b"not json").decode()
        req = _mock_request(headers={"x-ms-client-principal": encoded})
        with pytest.raises(ValueError, match="Malformed"):
            mod._parse_client_principal(req)

    def test_rejects_missing_user_id(self, _reload_module):
        mod = _reload_module
        principal = {"identityProvider": "aad", "userId": "", "userDetails": "x"}
        encoded = base64.b64encode(json.dumps(principal).encode()).decode()
        req = _mock_request(headers={"x-ms-client-principal": encoded})
        with pytest.raises(ValueError, match="userId"):
            mod._parse_client_principal(req)

    def test_rejects_non_dict_payload(self, _reload_module):
        """Valid JSON that is not an object must be rejected (defence-in-depth)."""
        mod = _reload_module
        encoded = base64.b64encode(b'["hi"]').decode()
        req = _mock_request(headers={"x-ms-client-principal": encoded})
        with pytest.raises(ValueError, match="not a JSON object"):
            mod._parse_client_principal(req)

    def test_parses_valid_principal(self, _reload_module):
        mod = _reload_module
        req = _mock_request(headers=_auth_headers(user_id="user-abc"))
        result = mod._parse_client_principal(req)
        assert result["userId"] == "user-abc"
        assert result["sub"] == "user-abc"  # compatibility alias
        assert result["identityProvider"] == "aad"

    def test_preserves_user_roles(self, _reload_module):
        mod = _reload_module
        req = _mock_request(
            headers=_auth_headers(user_id="u1", user_roles=["authenticated", "admin"])
        )
        result = mod._parse_client_principal(req)
        assert "admin" in result["userRoles"]


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for the anonymous health probe endpoint."""

    def test_returns_200(self, _reload_module):
        mod = _reload_module
        req = _mock_request(method="GET", url="https://example.com/api/health", headers={})
        resp = mod.health(req)
        assert resp.status_code == 200

    def test_returns_json(self, _reload_module):
        mod = _reload_module
        req = _mock_request(method="GET", url="https://example.com/api/health", headers={})
        resp = mod.health(req)
        body = json.loads(resp.get_body())
        assert body["status"] == "ok"

    def test_no_auth_required(self, _reload_module):
        """Health endpoint must work without x-ms-client-principal."""
        mod = _reload_module
        req = _mock_request(method="GET", url="https://example.com/api/health", headers={})
        resp = mod.health(req)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/upload/token
# ---------------------------------------------------------------------------


class TestUploadToken:
    """Tests for the upload_token endpoint."""

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_returns_sas_url(self, mock_sas, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_sas.return_value = "sv=2024-01-01&sig=test"

        req = _mock_request(headers=_auth_headers())
        resp = mod.upload_token(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert "submission_id" in body
        assert "sas_url" in body
        assert body["container"] == "kml-input"
        assert body["max_bytes"] == 10_485_760
        assert body["expires_minutes"] == 15
        # SAS URL points to the correct storage account
        from urllib.parse import urlparse

        parsed = urlparse(body["sas_url"])
        assert parsed.hostname == "teststorage.blob.core.windows.net"
        assert "/kml-input/analysis/" in parsed.path

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_submission_id_is_uuid(self, mock_sas, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_sas.return_value = "sig=test"

        req = _mock_request(headers=_auth_headers())
        resp = mod.upload_token(req)
        body = json.loads(resp.get_body())
        # Should be a valid UUID
        uuid.UUID(body["submission_id"])

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_sas_permissions_write_only(self, mock_sas, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_sas.return_value = "sig=test"

        req = _mock_request(headers=_auth_headers())
        mod.upload_token(req)

        # Verify SAS was requested with write-only permissions
        call_kwargs = mock_sas.call_args[1]
        perms = call_kwargs["permission"]
        assert perms.create is True
        assert perms.write is True
        assert perms.read is not True
        assert perms.delete is not True
        # Must use user delegation key, not account key
        assert "user_delegation_key" in call_kwargs, (
            "SAS must be generated with user_delegation_key (managed identity)"
        )
        assert "account_key" not in call_kwargs, (
            "SAS must NOT use account_key — use managed identity delegation"
        )

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_sas_expiry_matches_config(self, mock_sas, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_sas.return_value = "sig=test"

        req = _mock_request(headers=_auth_headers())
        mod.upload_token(req)

        call_kwargs = mock_sas.call_args[1]
        expiry = call_kwargs["expiry"]
        now = datetime.datetime.now(datetime.UTC)
        # Expiry should be ~15 minutes from now
        delta = (expiry - now).total_seconds()
        assert 800 < delta < 1000  # roughly 14-16 min window

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_writes_ticket_blob(self, mock_sas, mock_blob_svc, _reload_module):
        """upload_token must write a ticket blob with user metadata."""
        mod = _reload_module
        mock_sas.return_value = "sig=test"

        req = _mock_request(
            headers=_auth_headers(user_id="user-456"),
            body=json.dumps(
                {
                    "provider_name": "planetary_computer",
                    "submission_context": {"feature_count": 5},
                }
            ).encode(),
        )
        resp = mod.upload_token(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        sid = body["submission_id"]

        # Verify ticket blob was written
        mock_blob_svc.return_value.get_blob_client.assert_called_once_with(
            "kml-input", f".tickets/{sid}.json"
        )
        upload_call = mock_blob_svc.return_value.get_blob_client.return_value.upload_blob
        upload_call.assert_called_once()
        ticket_data = json.loads(upload_call.call_args[0][0])
        assert ticket_data["user_id"] == "user-456"
        assert ticket_data["provider_name"] == "planetary_computer"
        assert ticket_data["submission_context"]["feature_count"] == 5
        assert "created_at" in ticket_data

    def test_rejects_missing_auth_header(self, _reload_module):
        mod = _reload_module
        req = _mock_request(headers={})
        resp = mod.upload_token(req)
        assert resp.status_code == 401

    def test_rejects_empty_user_id(self, _reload_module):
        """Principal with empty userId must be rejected."""
        mod = _reload_module
        principal = {"identityProvider": "aad", "userId": "", "userDetails": "x"}
        encoded = base64.b64encode(json.dumps(principal).encode()).decode()
        req = _mock_request(headers={"x-ms-client-principal": encoded})
        resp = mod.upload_token(req)
        assert resp.status_code == 401

    def test_returns_503_when_storage_not_configured(self, _reload_module, monkeypatch):
        mod = _reload_module
        monkeypatch.setattr(mod, "STORAGE_ACCOUNT_NAME", "")

        req = _mock_request(headers=_auth_headers())
        resp = mod.upload_token(req)
        assert resp.status_code == 503

    @patch("swa_function_app._get_blob_service")
    def test_returns_502_on_ticket_write_failure(self, mock_blob_svc, _reload_module):
        """When ticket blob write fails, return 502."""
        mod = _reload_module
        mock_blob_svc.return_value.get_blob_client.return_value.upload_blob.side_effect = (
            RuntimeError("storage down")
        )

        req = _mock_request(headers=_auth_headers())
        resp = mod.upload_token(req)
        assert resp.status_code == 502

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_returns_502_on_delegation_key_failure(self, mock_sas, mock_blob_svc, _reload_module):
        """When user delegation key request fails, return 502."""
        mod = _reload_module
        mock_blob_svc.return_value.get_user_delegation_key.side_effect = RuntimeError(
            "identity not ready"
        )

        req = _mock_request(headers=_auth_headers())
        resp = mod.upload_token(req)
        assert resp.status_code == 502

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app.generate_blob_sas")
    def test_sanitises_submission_context(self, mock_sas, mock_blob_svc, _reload_module):
        """submission_context is allow-list filtered, not passed through raw."""
        mod = _reload_module
        mock_sas.return_value = "sig=test"

        malicious_ctx = {
            "feature_count": 5,
            "evil_key": "should be dropped",
            "aoi_count": -1,  # negative — should be dropped
            "__proto__": "injection",
        }
        req = _mock_request(
            headers=_auth_headers(),
            body=json.dumps({"submission_context": malicious_ctx}).encode(),
        )
        resp = mod.upload_token(req)
        assert resp.status_code == 200

        upload_call = mock_blob_svc.return_value.get_blob_client.return_value.upload_blob
        ticket_data = json.loads(upload_call.call_args[0][0])
        ctx = ticket_data.get("submission_context", {})
        assert ctx.get("feature_count") == 5
        assert "evil_key" not in ctx
        assert "aoi_count" not in ctx  # negative filtered out
        assert "__proto__" not in ctx


# ---------------------------------------------------------------------------
# GET /api/upload/status/{submission_id}
# ---------------------------------------------------------------------------


class TestUploadStatus:
    """Tests for the upload_status endpoint."""

    def test_returns_status_for_valid_id(self, _reload_module):
        mod = _reload_module
        sub_id = str(uuid.uuid4())

        req = _mock_request(
            method="GET",
            url=f"https://example.com/api/upload/status/{sub_id}",
            headers=_auth_headers(),
            route_params={"submission_id": sub_id},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["submission_id"] == sub_id

    def test_rejects_invalid_uuid(self, _reload_module):
        mod = _reload_module

        req = _mock_request(
            method="GET",
            headers=_auth_headers(),
            route_params={"submission_id": "not-a-uuid"},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 400

    def test_rejects_path_traversal_in_id(self, _reload_module):
        mod = _reload_module

        req = _mock_request(
            method="GET",
            headers=_auth_headers(),
            route_params={"submission_id": "../../../etc/passwd"},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 400

    def test_rejects_missing_auth(self, _reload_module):
        mod = _reload_module
        req = _mock_request(
            method="GET", headers={}, route_params={"submission_id": str(uuid.uuid4())}
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 401

    def test_rejects_missing_submission_id(self, _reload_module):
        mod = _reload_module

        req = _mock_request(
            method="GET",
            headers=_auth_headers(),
            route_params={},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/analysis/history
# ---------------------------------------------------------------------------


class TestAnalysisHistory:
    """Tests for the SWA analysis_history endpoint."""

    @patch("swa_function_app._get_cosmos_container")
    def test_returns_empty_history(self, mock_cosmos, _reload_module):
        """User with no runs gets empty list."""
        mod = _reload_module

        container = MagicMock()
        container.query_items.return_value = []
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history",
            headers=_auth_headers(user_id="user-empty"),
        )
        resp = mod.analysis_history(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["runs"] == []
        assert body["activeRun"] is None
        assert body["offset"] == 0
        assert body["limit"] == 8

    @patch("swa_function_app._get_cosmos_container")
    def test_returns_completed_run(self, mock_cosmos, _reload_module):
        """Returns a completed run with correct field mapping."""
        mod = _reload_module

        container = MagicMock()
        container.query_items.return_value = [
            {
                "id": "sub-001",
                "user_id": "user-1",
                "submission_id": "sub-001",
                "instance_id": "inst-001",
                "submitted_at": "2026-04-07T10:00:00Z",
                "status": "Completed",
                "provider_name": "planetary-computer",
                "feature_count": 3,
                "aoi_count": 2,
            }
        ]
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history",
            headers=_auth_headers(user_id="user-1"),
        )
        resp = mod.analysis_history(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert len(body["runs"]) == 1
        run = body["runs"][0]
        assert run["submissionId"] == "sub-001"
        assert run["instanceId"] == "inst-001"
        assert run["runtimeStatus"] == "Completed"
        assert run["featureCount"] == 3
        assert run["aoiCount"] == 2
        assert body["activeRun"] is None

    @patch("swa_function_app._get_cosmos_container")
    def test_detects_active_run(self, mock_cosmos, _reload_module):
        """An in-progress run is flagged as activeRun."""
        mod = _reload_module

        container = MagicMock()
        container.query_items.return_value = [
            {
                "id": "sub-active",
                "user_id": "user-2",
                "submission_id": "sub-active",
                "instance_id": "inst-active",
                "submitted_at": "2026-04-07T12:00:00Z",
                "status": "Running",
            }
        ]
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history",
            headers=_auth_headers(user_id="user-2"),
        )
        resp = mod.analysis_history(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["activeRun"] is not None
        assert body["activeRun"]["instanceId"] == "inst-active"

    def test_rejects_unauthenticated(self, _reload_module):
        """Analysis history requires authentication."""
        mod = _reload_module
        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history",
            headers={},
        )
        resp = mod.analysis_history(req)
        assert resp.status_code == 401

    @patch("swa_function_app._get_cosmos_container")
    def test_respects_limit_param(self, mock_cosmos, _reload_module):
        """Limit query parameter is passed through to Cosmos."""
        mod = _reload_module

        container = MagicMock()
        container.query_items.return_value = []
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history?limit=3",
            headers=_auth_headers(user_id="user-3"),
            params={"limit": "3"},
        )
        resp = mod.analysis_history(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["limit"] == 3


# ---------------------------------------------------------------------------
# Contract tests — verify response shapes match what the frontend reads
# ---------------------------------------------------------------------------


class TestResponseContracts:
    """Ensure SWA endpoints return every field the frontend consumes."""

    # Fields read by normalizeAnalysisRun() in app-shell.js
    _HISTORY_RUN_REQUIRED: typing.ClassVar[set[str]] = {
        "submissionId",
        "instanceId",
        "submittedAt",
        "submissionPrefix",
        "providerName",
        "featureCount",
        "aoiCount",
        "runtimeStatus",
        "createdTime",
        "lastUpdatedTime",
        "output",
        "artifactCount",
        "partialFailures",
    }

    @patch("swa_function_app._get_cosmos_container")
    def test_analysis_history_shape(self, mock_cosmos, _reload_module):
        """analysis_history returns all fields the frontend reads per run."""
        mod = _reload_module
        container = MagicMock()
        container.query_items.return_value = [
            {
                "id": "sub-c",
                "user_id": "user-123",
                "submission_id": "sub-c",
                "instance_id": "inst-c",
                "submitted_at": "2026-04-07T10:00:00Z",
                "status": "Completed",
            }
        ]
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history",
            headers=_auth_headers(),
        )
        body = json.loads(mod.analysis_history(req).get_body())
        assert "runs" in body
        assert "activeRun" in body
        assert len(body["runs"]) == 1
        run = body["runs"][0]
        missing = self._HISTORY_RUN_REQUIRED - run.keys()
        assert not missing, f"Missing history run fields: {missing}"


# ---------------------------------------------------------------------------
# GET /api/billing/status
# ---------------------------------------------------------------------------


class TestSwaBillingStatus:
    """Tests for the SWA billing_status endpoint."""

    def test_rejects_unauthenticated(self, _reload_module):
        mod = _reload_module
        req = _mock_request(method="GET", url="/api/billing/status", headers={})
        resp = mod.billing_status(req)
        assert resp.status_code == 401

    @patch("swa_function_app._get_cosmos_container")
    def test_free_user_returns_default_status(self, mock_cosmos, _reload_module):
        """A new user with no subscription gets free-tier defaults."""
        mod = _reload_module
        container = MagicMock()
        # No subscription or user doc — all reads raise
        container.read_item.side_effect = Exception("Not found")
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="/api/billing/status",
            headers=_auth_headers(user_id="user-free"),
        )
        resp = mod.billing_status(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["tier"] == "free"
        assert body["status"] == "none"
        assert body["runs_remaining"] >= 0
        assert body["runs_used"] == 0
        assert body["billing_gated"] is True
        assert body["tier_source"] == "billing"
        assert "capabilities" in body
        assert body["capabilities"]["run_limit"] == 5
        assert body["emulation"]["available"] is False
        assert body["emulation"]["active"] is False

    @patch("swa_function_app._get_cosmos_container")
    def test_pro_user_returns_pro_status(self, mock_cosmos, _reload_module):
        """A subscribed Pro user gets pro-tier status."""
        mod = _reload_module

        def _read_item(item, partition_key):
            if item == "user-pro":
                return {
                    "id": "user-pro",
                    "user_id": "user-pro",
                    "tier": "pro",
                    "status": "active",
                    "stripe_customer_id": "cus_abc",
                }
            raise Exception("Not found")

        container = MagicMock()
        container.read_item.side_effect = _read_item
        mock_cosmos.return_value = container

        # Allow billing for this user
        mod.BILLING_ALLOWED_USERS = frozenset({"user-pro"})

        req = _mock_request(
            method="GET",
            url="/api/billing/status",
            headers=_auth_headers(user_id="user-pro"),
        )
        resp = mod.billing_status(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["tier"] == "pro"
        assert body["status"] == "active"
        assert body["capabilities"]["run_limit"] == 50
        assert body["billing_gated"] is False

    @patch("swa_function_app._get_cosmos_container")
    def test_local_origin_shows_emulation_available(self, mock_cosmos, _reload_module):
        """Emulation is only available from local origins."""
        mod = _reload_module
        container = MagicMock()
        container.read_item.side_effect = Exception("Not found")
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="/api/billing/status",
            headers={
                **_auth_headers(user_id="dev-user"),
                "Origin": "http://localhost:4280",
            },
        )
        resp = mod.billing_status(req)
        body = json.loads(resp.get_body())
        assert body["emulation"]["available"] is True
        assert body["emulation"]["tiers"] == list(mod.PLAN_CATALOG.keys())

    @patch("swa_function_app._get_cosmos_container")
    def test_gated_user_gets_price_labels(self, mock_cosmos, _reload_module):
        """Billing-gated users receive price labels for the paywall UI."""
        mod = _reload_module
        container = MagicMock()
        container.read_item.side_effect = Exception("Not found")
        mock_cosmos.return_value = container
        mod.BILLING_ALLOWED_USERS = frozenset()  # nobody allowed

        req = _mock_request(
            method="GET",
            url="/api/billing/status",
            headers=_auth_headers(user_id="gated-user"),
        )
        resp = mod.billing_status(req)
        body = json.loads(resp.get_body())
        assert body["billing_gated"] is True
        assert "price_labels" in body
        assert body["price_labels"]["pro"] == "$$"

    @patch("swa_function_app._get_cosmos_container")
    def test_usage_reflects_cosmos_quota(self, mock_cosmos, _reload_module):
        """runs_remaining reflects actual Cosmos usage data."""
        mod = _reload_module

        def _read_item(item, partition_key):
            if item == "user-used" and partition_key == "user-used":
                return {
                    "id": "user-used",
                    "user_id": "user-used",
                    "quota": {"used": 3},
                }
            raise Exception("Not found")

        container = MagicMock()
        container.read_item.side_effect = _read_item
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="/api/billing/status",
            headers=_auth_headers(user_id="user-used"),
        )
        resp = mod.billing_status(req)
        body = json.loads(resp.get_body())
        assert body["runs_used"] == 3
        assert body["runs_remaining"] == 2  # free tier: 5 - 3


# ---------------------------------------------------------------------------
# POST /api/billing/checkout
# ---------------------------------------------------------------------------


class TestSwaBillingCheckout:
    """Tests for the SWA billing_checkout endpoint."""

    def test_rejects_unauthenticated(self, _reload_module):
        mod = _reload_module
        req = _mock_request(method="POST", url="/api/billing/checkout", headers={})
        resp = mod.billing_checkout(req)
        assert resp.status_code == 401

    def test_rejects_gated_user(self, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset()  # nobody allowed

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers=_auth_headers(user_id="gated-user"),
        )
        resp = mod.billing_checkout(req)
        assert resp.status_code == 403

    def test_returns_503_when_stripe_not_configured(self, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = ""

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers=_auth_headers(user_id="test-user"),
        )
        resp = mod.billing_checkout(req)
        assert resp.status_code == 503

    @patch("stripe.checkout.Session.create")
    def test_creates_checkout_session(self, mock_create, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"
        mod.STRIPE_PRICE_ID_PRO_USD = "price_usd"
        mod.STRIPE_PRICE_ID_PRO_EUR = "price_eur"

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session/test"
        mock_create.return_value = mock_session

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers={
                **_auth_headers(user_id="test-user"),
                "Origin": "https://canopex.hrdcrprwn.com",
            },
            body=json.dumps({"currency": "GBP"}).encode(),
        )
        resp = mod.billing_checkout(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["checkout_url"] == "https://checkout.stripe.com/session/test"

        # Verify Stripe was called with the correct price
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["line_items"] == [{"price": "price_gbp", "quantity": 1}]
        assert call_kwargs["client_reference_id"] == "test-user"

    @patch("stripe.checkout.Session.create")
    def test_defaults_to_gbp_currency(self, mock_create, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session/test"
        mock_create.return_value = mock_session

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers=_auth_headers(user_id="test-user"),
        )
        resp = mod.billing_checkout(req)
        assert resp.status_code == 200
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["line_items"] == [{"price": "price_gbp", "quantity": 1}]

    def test_returns_503_when_currency_price_id_empty(self, _reload_module):
        """503 when Stripe is configured but the selected currency has no price."""
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"
        mod.STRIPE_PRICE_ID_PRO_USD = ""  # USD not configured

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers=_auth_headers(user_id="test-user"),
            body=json.dumps({"currency": "USD"}).encode(),
        )
        resp = mod.billing_checkout(req)
        assert resp.status_code == 503
        assert "USD" in json.loads(resp.get_body())["error"]


# ---------------------------------------------------------------------------
# POST /api/billing/portal
# ---------------------------------------------------------------------------


class TestSwaBillingPortal:
    """Tests for the SWA billing_portal endpoint."""

    def test_rejects_unauthenticated(self, _reload_module):
        mod = _reload_module
        req = _mock_request(method="POST", url="/api/billing/portal", headers={})
        resp = mod.billing_portal(req)
        assert resp.status_code == 401

    def test_rejects_gated_user(self, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset()

        req = _mock_request(
            method="POST",
            url="/api/billing/portal",
            headers=_auth_headers(user_id="gated-user"),
        )
        resp = mod.billing_portal(req)
        assert resp.status_code == 403

    @patch("swa_function_app._get_cosmos_container")
    def test_returns_404_when_no_subscription(self, mock_cosmos, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        container = MagicMock()
        container.read_item.side_effect = Exception("Not found")
        mock_cosmos.return_value = container

        req = _mock_request(
            method="POST",
            url="/api/billing/portal",
            headers=_auth_headers(user_id="test-user"),
        )
        resp = mod.billing_portal(req)
        assert resp.status_code == 404

    @patch("stripe.billing_portal.Session.create")
    @patch("swa_function_app._get_cosmos_container")
    def test_creates_portal_session(self, mock_cosmos, mock_create, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        container = MagicMock()
        container.read_item.return_value = {
            "id": "test-user",
            "tier": "pro",
            "status": "active",
            "stripe_customer_id": "cus_portal_test",
        }
        mock_cosmos.return_value = container

        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/session/test"
        mock_create.return_value = mock_session

        req = _mock_request(
            method="POST",
            url="/api/billing/portal",
            headers=_auth_headers(user_id="test-user"),
        )
        resp = mod.billing_portal(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["portal_url"] == "https://billing.stripe.com/session/test"
        mock_create.assert_called_once_with(
            customer="cus_portal_test",
            return_url=unittest.mock.ANY,
        )


# ---------------------------------------------------------------------------
# Contract tests — billing status response shape
# ---------------------------------------------------------------------------


class TestBillingStatusContract:
    """Ensure billing status response has all fields the frontend reads."""

    _REQUIRED_FIELDS: typing.ClassVar[set[str]] = {
        "tier",
        "status",
        "runs_remaining",
        "runs_used",
        "billing_configured",
        "billing_gated",
        "tier_source",
        "capabilities",
        "subscription",
        "emulation",
    }

    @patch("swa_function_app._get_cosmos_container")
    def test_response_shape(self, mock_cosmos, _reload_module):
        mod = _reload_module
        container = MagicMock()
        container.read_item.side_effect = Exception("Not found")
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="/api/billing/status",
            headers=_auth_headers(),
        )
        body = json.loads(mod.billing_status(req).get_body())
        missing = self._REQUIRED_FIELDS - body.keys()
        assert not missing, f"Missing billing status fields: {missing}"

    @patch("swa_function_app._get_cosmos_container")
    def test_plan_catalog_matches_treesight(self, mock_cosmos, _reload_module):
        """SWA PLAN_CATALOG tier keys match treesight PLAN_CATALOG."""
        mod = _reload_module
        from treesight.security.billing import PLAN_CATALOG as TS_CATALOG

        assert set(mod.PLAN_CATALOG.keys()) == set(TS_CATALOG.keys()), (
            "SWA PLAN_CATALOG tiers diverged from treesight"
        )
        # Verify run limits match
        for tier in TS_CATALOG:
            assert mod.PLAN_CATALOG[tier]["run_limit"] == TS_CATALOG[tier]["run_limit"], (
                f"Run limit mismatch for tier {tier}"
            )
            # Verify all capability keys match
            assert set(mod.PLAN_CATALOG[tier].keys()) == set(TS_CATALOG[tier].keys()), (
                f"Capability key mismatch for tier {tier}"
            )
            for key, value in TS_CATALOG[tier].items():
                assert mod.PLAN_CATALOG[tier][key] == value, (
                    f"Value mismatch for tier {tier}, key {key}: "
                    f"SWA={mod.PLAN_CATALOG[tier][key]!r} vs treesight={value!r}"
                )


# ---------------------------------------------------------------------------
# Origin validation — Stripe redirect URLs must use allowlisted origins
# ---------------------------------------------------------------------------


class TestOriginValidation:
    """Ensure Stripe redirect URLs use allow-listed origins only."""

    @patch("stripe.checkout.Session.create")
    def test_checkout_uses_allowed_origin(self, mock_create, _reload_module):
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session/test"
        mock_create.return_value = mock_session

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers={
                **_auth_headers(user_id="test-user"),
                "Origin": "https://canopex.hrdcrprwn.com",
            },
        )
        mod.billing_checkout(req)
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["success_url"] == "https://canopex.hrdcrprwn.com?billing=success"

    @patch("stripe.checkout.Session.create")
    def test_checkout_rejects_evil_origin(self, mock_create, _reload_module):
        """Attacker-controlled Origin must not appear in redirect URLs."""
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/session/test"
        mock_create.return_value = mock_session

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers={
                **_auth_headers(user_id="test-user"),
                "Origin": "https://evil.com",
            },
        )
        mod.billing_checkout(req)
        call_kwargs = mock_create.call_args[1]
        assert "evil.com" not in call_kwargs["success_url"]
        assert "evil.com" not in call_kwargs["cancel_url"]
        # Falls back to default production origin
        assert call_kwargs["success_url"] == "https://canopex.hrdcrprwn.com?billing=success"
        assert call_kwargs["cancel_url"] == "https://canopex.hrdcrprwn.com?billing=cancel"

    @patch("stripe.billing_portal.Session.create")
    @patch("swa_function_app._get_cosmos_container")
    def test_portal_rejects_evil_origin(self, mock_cosmos, mock_create, _reload_module):
        """Portal return_url must not use attacker-controlled origin."""
        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        container = MagicMock()
        container.read_item.return_value = {
            "id": "test-user",
            "tier": "pro",
            "status": "active",
            "stripe_customer_id": "cus_test",
        }
        mock_cosmos.return_value = container

        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/session/test"
        mock_create.return_value = mock_session

        req = _mock_request(
            method="POST",
            url="/api/billing/portal",
            headers={
                **_auth_headers(user_id="test-user"),
                "Origin": "https://evil.com",
            },
        )
        mod.billing_portal(req)
        call_kwargs = mock_create.call_args[1]
        assert "evil.com" not in call_kwargs["return_url"]
        assert call_kwargs["return_url"] == "https://canopex.hrdcrprwn.com?billing=portal-return"


# ---------------------------------------------------------------------------
# Stripe failure paths — 502 when Stripe SDK raises
# ---------------------------------------------------------------------------


class TestStripeFailurePaths:
    """Verify billing endpoints return 502 on Stripe SDK errors."""

    @patch("stripe.checkout.Session.create")
    def test_checkout_returns_502_on_stripe_error(self, mock_create, _reload_module):
        import stripe as stripe_mod

        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        mock_create.side_effect = stripe_mod.StripeError("Card declined")

        req = _mock_request(
            method="POST",
            url="/api/billing/checkout",
            headers=_auth_headers(user_id="test-user"),
        )
        resp = mod.billing_checkout(req)
        assert resp.status_code == 502

    @patch("stripe.billing_portal.Session.create")
    @patch("swa_function_app._get_cosmos_container")
    def test_portal_returns_502_on_stripe_error(self, mock_cosmos, mock_create, _reload_module):
        import stripe as stripe_mod

        mod = _reload_module
        mod.BILLING_ALLOWED_USERS = frozenset({"test-user"})
        mod.STRIPE_API_KEY = "sk_test_xxx"  # pragma: allowlist secret
        mod.STRIPE_PRICE_ID_PRO_GBP = "price_gbp"

        container = MagicMock()
        container.read_item.return_value = {
            "id": "test-user",
            "tier": "pro",
            "status": "active",
            "stripe_customer_id": "cus_test",
        }
        mock_cosmos.return_value = container

        mock_create.side_effect = stripe_mod.StripeError("Network error")

        req = _mock_request(
            method="POST",
            url="/api/billing/portal",
            headers=_auth_headers(user_id="test-user"),
        )
        resp = mod.billing_portal(req)
        assert resp.status_code == 502
