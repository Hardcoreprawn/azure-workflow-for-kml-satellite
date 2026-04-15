"""Tests for HMAC session token auth verification (#534)."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from treesight.security.auth import (
    sign_session_token,
    verify_session_token,
)

SECRET = "test-secret-key-for-hmac-verification"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# sign_session_token
# ---------------------------------------------------------------------------


class TestSignSessionToken:
    def test_returns_token_and_expiry(self):
        result = sign_session_token("user-1", key=SECRET)
        assert "token" in result
        assert "expires_at" in result
        assert result["expires_at"] > time.time()
        assert "." in result["token"]

    def test_token_has_two_parts(self):
        result = sign_session_token("user-1", key=SECRET)
        parts = result["token"].split(".")
        assert len(parts) == 2

    def test_custom_ttl(self):
        result = sign_session_token("user-1", key=SECRET, ttl=60)
        assert result["expires_at"] <= time.time() + 61

    def test_payload_contains_uid(self):
        result = sign_session_token("user-42", key=SECRET)
        payload_b64 = result["token"].split(".")[0]
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        assert payload["uid"] == "user-42"


# ---------------------------------------------------------------------------
# verify_session_token
# ---------------------------------------------------------------------------


class TestVerifySessionToken:
    def test_valid_token_passes(self):
        result = sign_session_token("user-1", key=SECRET)
        # Should not raise
        verify_session_token(result["token"], "user-1", key=SECRET)

    def test_wrong_user_id_fails(self):
        result = sign_session_token("user-1", key=SECRET)
        with pytest.raises(ValueError, match="userId mismatch"):
            verify_session_token(result["token"], "user-2", key=SECRET)

    def test_wrong_key_fails(self):
        result = sign_session_token("user-1", key=SECRET)
        with pytest.raises(ValueError, match="Invalid session token signature"):
            verify_session_token(result["token"], "user-1", key="wrong-key")

    def test_expired_token_fails(self):
        result = sign_session_token("user-1", key=SECRET, ttl=-1)
        with pytest.raises(ValueError, match="expired"):
            verify_session_token(result["token"], "user-1", key=SECRET)

    def test_malformed_token_fails(self):
        with pytest.raises(ValueError, match="Malformed"):
            verify_session_token("no-dot-here", "user-1", key=SECRET)

    def test_tampered_payload_fails(self):
        result = sign_session_token("user-1", key=SECRET)
        # Replace payload with a different one but keep the original signature
        fake_payload = base64.urlsafe_b64encode(
            json.dumps({"uid": "admin", "exp": int(time.time()) + 3600}).encode()
        ).decode()
        tampered = fake_payload + "." + result["token"].split(".")[1]
        with pytest.raises(ValueError, match="Invalid session token signature"):
            verify_session_token(tampered, "admin", key=SECRET)


# ---------------------------------------------------------------------------
# require_auth HMAC enforcement
# ---------------------------------------------------------------------------


def _encode_principal(user_id="abc-123"):
    principal = {
        "identityProvider": "aad",
        "userId": user_id,
        "userDetails": "u@e.com",
        "userRoles": ["authenticated"],
    }
    return base64.b64encode(json.dumps(principal).encode()).decode()


class TestRequireAuthHmac:
    def test_hmac_not_enforced_when_key_absent(self):
        import azure.functions as func

        from blueprints._helpers import require_auth

        @require_auth
        def ep(req, auth_claims=None, user_id=None):
            return func.HttpResponse(json.dumps({"user": user_id}), mimetype="application/json")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": _encode_principal("u-1")}

        with patch("blueprints._helpers.AUTH_HMAC_KEY", ""):
            resp = ep(mock_req)
            assert resp.status_code == 200

    def test_hmac_enforced_rejects_missing_token(self):
        import azure.functions as func

        from blueprints._helpers import require_auth

        @require_auth
        def ep(req, auth_claims=None, user_id=None):
            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": _encode_principal("u-1")}

        with patch("blueprints._helpers.AUTH_HMAC_KEY", SECRET):
            resp = ep(mock_req)
            assert resp.status_code == 401

    def test_hmac_enforced_accepts_valid_token(self):
        import azure.functions as func

        from blueprints._helpers import require_auth

        token_data = sign_session_token("u-1", key=SECRET)

        @require_auth
        def ep(req, auth_claims=None, user_id=None):
            return func.HttpResponse(json.dumps({"user": user_id}), mimetype="application/json")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal("u-1"),
            "X-Auth-Session": token_data["token"],
        }

        with patch("blueprints._helpers.AUTH_HMAC_KEY", SECRET):
            resp = ep(mock_req)
            assert resp.status_code == 200
            body = json.loads(resp.get_body())
            assert body["user"] == "u-1"

    def test_hmac_enforced_rejects_wrong_user(self):
        import azure.functions as func

        from blueprints._helpers import require_auth

        token_data = sign_session_token("u-other", key=SECRET)

        @require_auth
        def ep(req, auth_claims=None, user_id=None):
            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal("u-1"),
            "X-Auth-Session": token_data["token"],
        }

        with patch("blueprints._helpers.AUTH_HMAC_KEY", SECRET):
            resp = ep(mock_req)
            assert resp.status_code == 401


class TestRequireAuthHmacExempt:
    def test_exempt_skips_hmac_check(self):
        import azure.functions as func

        from blueprints._helpers import require_auth_hmac_exempt

        @require_auth_hmac_exempt
        def ep(req, auth_claims=None, user_id=None):
            return func.HttpResponse(json.dumps({"user": user_id}), mimetype="application/json")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": _encode_principal("u-1")}

        with patch("blueprints._helpers.AUTH_HMAC_KEY", SECRET):
            resp = ep(mock_req)
            assert resp.status_code == 200
            body = json.loads(resp.get_body())
            assert body["user"] == "u-1"


# ---------------------------------------------------------------------------
# /api/auth/session endpoint
# ---------------------------------------------------------------------------


class TestAuthSessionEndpoint:
    def test_returns_token_when_hmac_enabled(self):
        from blueprints.auth import auth_session
        from tests.conftest import make_test_request

        req = make_test_request(
            url="/api/auth/session",
            method="POST",
            principal_user_id="u-1",
            auth_header=None,
        )

        with (
            patch("blueprints.auth.AUTH_HMAC_KEY", SECRET),
            patch("blueprints._helpers.AUTH_HMAC_KEY", ""),
        ):
            resp = auth_session(req)
            assert resp.status_code == 200
            body = json.loads(resp.get_body())
            assert body["hmac_enabled"] is True
            assert body["token"]
            assert body["expires_at"] > time.time()
            # Verify the token is valid
            verify_session_token(body["token"], "u-1", key=SECRET)

    def test_returns_empty_when_hmac_not_configured(self):
        from blueprints.auth import auth_session
        from tests.conftest import make_test_request

        req = make_test_request(
            url="/api/auth/session",
            method="POST",
            principal_user_id="u-1",
            auth_header=None,
        )

        with (
            patch("blueprints.auth.AUTH_HMAC_KEY", ""),
            patch("blueprints._helpers.AUTH_HMAC_KEY", ""),
        ):
            resp = auth_session(req)
            assert resp.status_code == 200
            body = json.loads(resp.get_body())
            assert body["hmac_enabled"] is False
            assert body["token"] == ""

    def test_rejects_anonymous_when_auth_required(self):
        from blueprints.auth import auth_session
        from tests.conftest import make_test_request

        req = make_test_request(
            url="/api/auth/session",
            method="POST",
            principal_user_id=None,
            auth_header=None,
        )

        with (
            patch("blueprints.auth.AUTH_HMAC_KEY", SECRET),
            patch("blueprints._helpers.AUTH_HMAC_KEY", ""),
            patch.dict("os.environ", {"REQUIRE_AUTH": "1"}),
        ):
            resp = auth_session(req)
            assert resp.status_code == 401
