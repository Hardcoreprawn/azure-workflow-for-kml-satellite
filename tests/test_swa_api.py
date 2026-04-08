"""Tests for the SWA managed API functions (§2B.2).

These tests verify the SWA API function logic — SAS token minting and
status polling — without requiring the Azure Functions runtime.  We
import the module directly and call the helper functions + route handlers.

Auth is handled by SWA built-in custom auth (x-ms-client-principal header).
"""

from __future__ import annotations

import base64
import datetime
import json
import sys
import typing
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
