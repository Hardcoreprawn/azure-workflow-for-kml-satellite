"""Tests for the SWA managed API functions (§2B.2).

These tests verify the SWA API function logic — SAS token minting and
status polling — without requiring the Azure Functions runtime.  We
import the module directly and call the helper functions + route handlers.
"""

from __future__ import annotations

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
    monkeypatch.setenv("CIAM_TENANT_NAME", "treesightauth")
    monkeypatch.setenv("CIAM_CLIENT_ID", "test-client-id")
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
    mod._jwks_client = None
    mod._blob_service = None
    mod._cached_issuer = ""
    mod._issuer_fetch_failed_at = 0.0
    return mod


def _make_claims(sub: str = "user-123", aud: str = "test-client-id") -> dict:
    """Build a minimal valid JWT claims dict."""
    return {
        "sub": sub,
        "aud": aud,
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    }


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


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


class TestTokenValidation:
    """Tests for ``_validate_token``."""

    def test_rejects_missing_bearer(self, _reload_module):
        mod = _reload_module
        with pytest.raises(ValueError, match="Bearer"):
            mod._validate_token("")

    def test_rejects_non_bearer(self, _reload_module):
        mod = _reload_module
        with pytest.raises(ValueError, match="Bearer"):
            mod._validate_token("Basic abc123")

    @patch("swa_function_app._get_jwks_client")
    def test_accepts_valid_token(self, mock_jwks, _reload_module):
        mod = _reload_module
        mock_key = MagicMock()
        mock_key.key = "test-key"
        mock_jwks.return_value.get_signing_key_from_jwt.return_value = mock_key

        with patch("swa_function_app.jwt.decode", return_value=_make_claims()):
            claims = mod._validate_token("Bearer valid-token")
            assert claims["sub"] == "user-123"

    @patch("swa_function_app._get_jwks_client")
    @patch("swa_function_app._get_issuer")
    def test_passes_issuer_to_jwt_decode(self, mock_issuer, mock_jwks, _reload_module):
        """When OIDC issuer is available, _validate_token must pass it to jwt.decode."""
        mod = _reload_module
        mock_key = MagicMock()
        mock_key.key = "test-key"
        mock_jwks.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_issuer.return_value = "https://92001438.ciamlogin.com/92001438/v2.0"

        with patch("swa_function_app.jwt.decode", return_value=_make_claims()) as mock_decode:
            mod._validate_token("Bearer valid-token")
            _, kwargs = mock_decode.call_args
            assert kwargs["issuer"] == "https://92001438.ciamlogin.com/92001438/v2.0"
            assert "iss" in kwargs["options"]["require"]

    @patch("swa_function_app._get_jwks_client")
    @patch("swa_function_app._get_issuer")
    def test_skips_issuer_check_when_unavailable(
        self,
        mock_issuer,
        mock_jwks,
        _reload_module,
        caplog,
    ):
        """When OIDC issuer is empty, _validate_token decodes without issuer and logs a warning."""
        mod = _reload_module
        mock_key = MagicMock()
        mock_key.key = "test-key"
        mock_jwks.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_issuer.return_value = ""

        with patch("swa_function_app.jwt.decode", return_value=_make_claims()) as mock_decode:
            mod._validate_token("Bearer valid-token")
            _, kwargs = mock_decode.call_args
            assert "issuer" not in kwargs
        assert "issuer" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Issuer fetching
# ---------------------------------------------------------------------------


class TestIssuerFetch:
    """Tests for ``_get_issuer``."""

    def test_returns_cached_issuer(self, _reload_module):
        mod = _reload_module
        mod._cached_issuer = "https://example.com/v2.0"
        assert mod._get_issuer() == "https://example.com/v2.0"

    @patch("swa_function_app.urllib.request.urlopen")
    def test_fetches_from_oidc_discovery(self, mock_urlopen, _reload_module):
        mod = _reload_module
        mod._cached_issuer = ""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"issuer": "https://tenant.ciamlogin.com/tenant/v2.0"}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = mod._get_issuer()
        assert result == "https://tenant.ciamlogin.com/tenant/v2.0"
        assert mod._cached_issuer == result

    @patch("swa_function_app.urllib.request.urlopen")
    def test_returns_empty_on_fetch_failure(self, mock_urlopen, _reload_module):
        mod = _reload_module
        mod._cached_issuer = ""
        mod._issuer_fetch_failed_at = 0.0
        mock_urlopen.side_effect = Exception("network error")

        result = mod._get_issuer()
        assert result == ""
        assert mod._issuer_fetch_failed_at > 0

    @patch("swa_function_app.urllib.request.urlopen")
    def test_skips_retry_during_cooldown(self, mock_urlopen, _reload_module):
        """After a failed fetch, _get_issuer skips retries within the cooldown window."""
        import time

        mod = _reload_module
        mod._cached_issuer = ""
        mod._issuer_fetch_failed_at = time.monotonic()  # just failed

        result = mod._get_issuer()
        assert result == ""
        mock_urlopen.assert_not_called()

    def test_raises_when_ciam_not_configured(self, _reload_module, monkeypatch):
        mod = _reload_module
        mod._cached_issuer = ""
        mod._OIDC_CONFIG_URL = ""
        with pytest.raises(RuntimeError, match="CIAM_TENANT_NAME"):
            mod._get_issuer()


class TestOidcConfigUrls:
    """Verify OIDC discovery and JWKS URIs use the tenant-qualified path."""

    def test_jwks_uri_includes_tenant_domain(self, _reload_module):
        mod = _reload_module
        expected_prefix = "https://treesightauth.ciamlogin.com/treesightauth.onmicrosoft.com/"
        assert mod._JWKS_URI.startswith(expected_prefix)
        assert mod._JWKS_URI.endswith("/discovery/v2.0/keys")

    def test_oidc_config_includes_tenant_domain(self, _reload_module):
        mod = _reload_module
        expected_prefix = "https://treesightauth.ciamlogin.com/treesightauth.onmicrosoft.com/"
        assert mod._OIDC_CONFIG_URL.startswith(expected_prefix)
        assert mod._OIDC_CONFIG_URL.endswith("/v2.0/.well-known/openid-configuration")


# ---------------------------------------------------------------------------
# POST /api/upload/token
# ---------------------------------------------------------------------------


class TestUploadToken:
    """Tests for the upload_token endpoint."""

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_returns_sas_url(self, mock_sas, mock_auth, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_sas.return_value = "sv=2024-01-01&sig=test"

        req = _mock_request(headers={"Authorization": "Bearer valid"})
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
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_submission_id_is_uuid(self, mock_sas, mock_auth, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_sas.return_value = "sig=test"

        req = _mock_request(headers={"Authorization": "Bearer valid"})
        resp = mod.upload_token(req)
        body = json.loads(resp.get_body())
        # Should be a valid UUID
        uuid.UUID(body["submission_id"])

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_sas_permissions_write_only(self, mock_sas, mock_auth, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_sas.return_value = "sig=test"

        req = _mock_request(headers={"Authorization": "Bearer valid"})
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
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_sas_expiry_matches_config(self, mock_sas, mock_auth, mock_blob_svc, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_sas.return_value = "sig=test"

        req = _mock_request(headers={"Authorization": "Bearer valid"})
        mod.upload_token(req)

        call_kwargs = mock_sas.call_args[1]
        expiry = call_kwargs["expiry"]
        now = datetime.datetime.now(datetime.UTC)
        # Expiry should be ~15 minutes from now
        delta = (expiry - now).total_seconds()
        assert 800 < delta < 1000  # roughly 14-16 min window

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_writes_ticket_blob(self, mock_sas, mock_auth, mock_blob_svc, _reload_module):
        """upload_token must write a ticket blob with user metadata."""
        mod = _reload_module
        mock_auth.return_value = _make_claims(sub="user-456")
        mock_sas.return_value = "sig=test"

        req = _mock_request(
            headers={"Authorization": "Bearer valid"},
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

    @patch("swa_function_app._validate_token")
    def test_expired_token_returns_reason(self, mock_auth, _reload_module):
        """401 for expired tokens must include reason=token_expired so the
        frontend can distinguish genuine expiry from config errors."""
        import jwt as _jwt

        mod = _reload_module
        mock_auth.side_effect = _jwt.ExpiredSignatureError("Signature has expired")
        req = _mock_request(headers={"Authorization": "Bearer expired-token"})
        resp = mod.upload_token(req)
        assert resp.status_code == 401
        body = json.loads(resp.get_body())
        assert body["reason"] == "token_expired"

    @patch("swa_function_app._validate_token")
    def test_rejects_empty_subject(self, mock_auth, _reload_module):
        mod = _reload_module
        mock_auth.return_value = {"sub": "", "aud": "test", "exp": 0}
        req = _mock_request(headers={"Authorization": "Bearer valid"})
        resp = mod.upload_token(req)
        assert resp.status_code == 401

    @patch("swa_function_app._validate_token")
    def test_returns_503_when_storage_not_configured(self, mock_auth, _reload_module, monkeypatch):
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        monkeypatch.setattr(mod, "STORAGE_ACCOUNT_NAME", "")

        req = _mock_request(headers={"Authorization": "Bearer valid"})
        resp = mod.upload_token(req)
        assert resp.status_code == 503

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_returns_502_on_ticket_write_failure(
        self, mock_sas, mock_auth, mock_blob_svc, _reload_module
    ):
        """When ticket blob write fails, return 502."""
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_blob_svc.return_value.get_blob_client.return_value.upload_blob.side_effect = (
            RuntimeError("storage down")
        )

        req = _mock_request(headers={"Authorization": "Bearer valid"})
        resp = mod.upload_token(req)
        assert resp.status_code == 502

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_returns_502_on_delegation_key_failure(
        self, mock_sas, mock_auth, mock_blob_svc, _reload_module
    ):
        """When user delegation key request fails, return 502."""
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_blob_svc.return_value.get_user_delegation_key.side_effect = RuntimeError(
            "identity not ready"
        )

        req = _mock_request(headers={"Authorization": "Bearer valid"})
        resp = mod.upload_token(req)
        assert resp.status_code == 502

    @patch("swa_function_app._get_blob_service")
    @patch("swa_function_app._validate_token")
    @patch("swa_function_app.generate_blob_sas")
    def test_sanitises_submission_context(self, mock_sas, mock_auth, mock_blob_svc, _reload_module):
        """submission_context is allow-list filtered, not passed through raw."""
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        mock_sas.return_value = "sig=test"

        malicious_ctx = {
            "feature_count": 5,
            "evil_key": "should be dropped",
            "aoi_count": -1,  # negative — should be dropped
            "__proto__": "injection",
        }
        req = _mock_request(
            headers={"Authorization": "Bearer valid"},
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

    @patch("swa_function_app._validate_token")
    def test_returns_status_for_valid_id(self, mock_auth, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()
        sub_id = str(uuid.uuid4())

        req = _mock_request(
            method="GET",
            url=f"https://example.com/api/upload/status/{sub_id}",
            headers={"Authorization": "Bearer valid"},
            route_params={"submission_id": sub_id},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["submission_id"] == sub_id

    @patch("swa_function_app._validate_token")
    def test_rejects_invalid_uuid(self, mock_auth, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()

        req = _mock_request(
            method="GET",
            headers={"Authorization": "Bearer valid"},
            route_params={"submission_id": "not-a-uuid"},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 400

    @patch("swa_function_app._validate_token")
    def test_rejects_path_traversal_in_id(self, mock_auth, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()

        req = _mock_request(
            method="GET",
            headers={"Authorization": "Bearer valid"},
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

    @patch("swa_function_app._validate_token")
    def test_expired_token_returns_reason(self, mock_auth, _reload_module):
        """401 for expired tokens must include reason=token_expired (mirrors upload_token)."""
        import jwt as _jwt

        mod = _reload_module
        mock_auth.side_effect = _jwt.ExpiredSignatureError("Signature has expired")
        req = _mock_request(
            method="GET",
            headers={"Authorization": "Bearer expired"},
            route_params={"submission_id": str(uuid.uuid4())},
        )
        resp = mod.upload_status(req)
        assert resp.status_code == 401
        body = json.loads(resp.get_body())
        assert body["reason"] == "token_expired"

    @patch("swa_function_app._validate_token")
    def test_rejects_missing_submission_id(self, mock_auth, _reload_module):
        mod = _reload_module
        mock_auth.return_value = _make_claims()

        req = _mock_request(
            method="GET",
            headers={"Authorization": "Bearer valid"},
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
    @patch("swa_function_app._validate_token")
    def test_returns_empty_history(self, mock_auth, mock_cosmos, _reload_module):
        """User with no runs gets empty list."""
        mod = _reload_module
        mock_auth.return_value = _make_claims(sub="user-empty")

        container = MagicMock()
        container.query_items.return_value = []
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history",
            headers={"Authorization": "Bearer valid"},
        )
        resp = mod.analysis_history(req)
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["runs"] == []
        assert body["activeRun"] is None
        assert body["offset"] == 0
        assert body["limit"] == 8

    @patch("swa_function_app._get_cosmos_container")
    @patch("swa_function_app._validate_token")
    def test_returns_completed_run(self, mock_auth, mock_cosmos, _reload_module):
        """Returns a completed run with correct field mapping."""
        mod = _reload_module
        mock_auth.return_value = _make_claims(sub="user-1")

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
            headers={"Authorization": "Bearer valid"},
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
    @patch("swa_function_app._validate_token")
    def test_detects_active_run(self, mock_auth, mock_cosmos, _reload_module):
        """An in-progress run is flagged as activeRun."""
        mod = _reload_module
        mock_auth.return_value = _make_claims(sub="user-2")

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
            headers={"Authorization": "Bearer valid"},
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
    @patch("swa_function_app._validate_token")
    def test_respects_limit_param(self, mock_auth, mock_cosmos, _reload_module):
        """Limit query parameter is passed through to Cosmos."""
        mod = _reload_module
        mock_auth.return_value = _make_claims(sub="user-3")

        container = MagicMock()
        container.query_items.return_value = []
        mock_cosmos.return_value = container

        req = _mock_request(
            method="GET",
            url="https://example.com/api/analysis/history?limit=3",
            headers={"Authorization": "Bearer valid"},
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
    @patch("swa_function_app._validate_token")
    def test_analysis_history_shape(self, mock_auth, mock_cosmos, _reload_module):
        """analysis_history returns all fields the frontend reads per run."""
        mod = _reload_module
        mock_auth.return_value = _make_claims()
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
            headers={"Authorization": "Bearer valid"},
        )
        body = json.loads(mod.analysis_history(req).get_body())
        assert "runs" in body
        assert "activeRun" in body
        assert len(body["runs"]) == 1
        run = body["runs"][0]
        missing = self._HISTORY_RUN_REQUIRED - run.keys()
        assert not missing, f"Missing history run fields: {missing}"
