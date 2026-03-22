"""Tests for Entra External ID (CIAM) JWT authentication (treesight.security.auth)."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from treesight.security.auth import (
    _fetch_jwks,
    _jwks_cache,
    _oidc_config_url,
    auth_enabled,
    get_user_id,
    validate_token,
)

# ---------------------------------------------------------------------------
# auth_enabled
# ---------------------------------------------------------------------------


class TestAuthEnabled:
    def test_disabled_when_no_config(self):
        with (
            patch("treesight.security.auth.CIAM_TENANT_NAME", ""),
            patch("treesight.security.auth.CIAM_CLIENT_ID", ""),
            patch("treesight.security.auth.REQUIRE_AUTH", False),
        ):
            assert auth_enabled() is False

    def test_disabled_when_partial_config(self):
        with (
            patch("treesight.security.auth.CIAM_TENANT_NAME", "mytenant"),
            patch("treesight.security.auth.CIAM_CLIENT_ID", ""),
            patch("treesight.security.auth.REQUIRE_AUTH", False),
        ):
            assert auth_enabled() is False

    def test_enabled_when_fully_configured(self):
        with (
            patch("treesight.security.auth.CIAM_TENANT_NAME", "mytenant"),
            patch("treesight.security.auth.CIAM_CLIENT_ID", "abc-123"),
        ):
            assert auth_enabled() is True

    def test_require_auth_raises_when_ciam_missing(self):
        with (
            patch("treesight.security.auth.CIAM_TENANT_NAME", ""),
            patch("treesight.security.auth.CIAM_CLIENT_ID", ""),
            patch("treesight.security.auth.REQUIRE_AUTH", True),
        ):
            with pytest.raises(RuntimeError, match="REQUIRE_AUTH"):
                auth_enabled()


# ---------------------------------------------------------------------------
# _oidc_config_url
# ---------------------------------------------------------------------------


class TestOidcConfigUrl:
    def test_url_format(self):
        with patch("treesight.security.auth.CIAM_TENANT_NAME", "mytenant"):
            url = _oidc_config_url()
            assert "mytenant.ciamlogin.com" in url
            assert "mytenant.onmicrosoft.com" in url
            assert url.endswith("/v2.0/.well-known/openid-configuration")


# ---------------------------------------------------------------------------
# get_user_id
# ---------------------------------------------------------------------------


class TestGetUserId:
    def test_prefers_sub(self):
        assert get_user_id({"sub": "user-123", "oid": "oid-456"}) == "user-123"

    def test_falls_back_to_oid(self):
        assert get_user_id({"oid": "oid-456"}) == "oid-456"

    def test_returns_empty_when_no_id(self):
        assert get_user_id({}) == ""


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------


class TestValidateToken:
    def test_raises_when_not_configured(self):
        with patch("treesight.security.auth.auth_enabled", return_value=False):
            with pytest.raises(ValueError, match="not configured"):
                validate_token("Bearer xxx")

    def test_raises_on_missing_header(self):
        with patch("treesight.security.auth.auth_enabled", return_value=True):
            with pytest.raises(ValueError, match="Missing or malformed"):
                validate_token("")

    def test_raises_on_malformed_header(self):
        with patch("treesight.security.auth.auth_enabled", return_value=True):
            with pytest.raises(ValueError, match="Missing or malformed"):
                validate_token("Basic abc")

    def test_raises_on_invalid_token_format(self):
        with (
            patch("treesight.security.auth.auth_enabled", return_value=True),
            patch("treesight.security.auth._fetch_jwks", return_value={"keys": []}),
        ):
            with pytest.raises(ValueError, match="Invalid token format"):
                validate_token("Bearer not-a-jwt")

    def test_raises_when_jwks_empty(self):
        with (
            patch("treesight.security.auth.auth_enabled", return_value=True),
            patch("treesight.security.auth._fetch_jwks", return_value={}),
        ):
            with pytest.raises(ValueError, match="Could not retrieve signing keys"):
                validate_token("Bearer xxx")


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------


class TestJwksCache:
    def test_cache_hit_returns_cached_keys(self):
        fake_keys = {"keys": [{"kid": "k1", "kty": "RSA"}]}
        _jwks_cache.clear()
        _jwks_cache["keys"] = fake_keys
        _jwks_cache["fetched_at"] = time.monotonic()

        with patch("treesight.security.auth.CIAM_TENANT_NAME", "t"):
            result = _fetch_jwks()
            assert result == fake_keys

    def test_cache_expired_refetches(self):
        _jwks_cache.clear()
        _jwks_cache["keys"] = {"keys": [{"kid": "old"}]}
        _jwks_cache["fetched_at"] = time.monotonic() - 100000  # expired

        mock_oidc = {"jwks_uri": "https://example.com/jwks", "issuer": "https://example.com"}
        mock_jwks = {"keys": [{"kid": "new"}]}

        with (
            patch("treesight.security.auth.CIAM_TENANT_NAME", "t"),
            patch("treesight.security.auth.requests.get") as mock_get,
        ):
            mock_get.return_value.json.side_effect = [mock_oidc, mock_jwks]
            result = _fetch_jwks()
            assert result == mock_jwks

    def test_fetch_failure_returns_stale_cache(self):
        _jwks_cache.clear()
        stale_keys = {"keys": [{"kid": "stale"}]}
        _jwks_cache["keys"] = stale_keys
        _jwks_cache["fetched_at"] = time.monotonic() - 100000  # expired

        with (
            patch("treesight.security.auth.CIAM_TENANT_NAME", "t"),
            patch("treesight.security.auth.requests.get", side_effect=Exception("network")),
        ):
            result = _fetch_jwks()
            assert result == stale_keys


# ---------------------------------------------------------------------------
# check_auth helper (from _helpers.py)
# ---------------------------------------------------------------------------


class TestCheckAuth:
    def test_returns_anonymous_when_auth_disabled(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        with patch("blueprints._helpers.auth_enabled", return_value=False):
            claims, user_id = check_auth(mock_req)
            assert claims == {}
            assert user_id == "anonymous"

    def test_raises_on_invalid_token(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {"Authorization": "Bearer bad"}

        with (
            patch("blueprints._helpers.auth_enabled", return_value=True),
            patch("blueprints._helpers.validate_token", side_effect=ValueError("Invalid token")),
        ):
            with pytest.raises(ValueError, match="Invalid token"):
                check_auth(mock_req)

    def test_passes_valid_token(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {"Authorization": "Bearer good-token"}

        fake_claims = {"sub": "user-1", "name": "Test User"}
        with (
            patch("blueprints._helpers.auth_enabled", return_value=True),
            patch("blueprints._helpers.validate_token", return_value=fake_claims),
            patch("blueprints._helpers.get_user_id", return_value="user-1"),
        ):
            claims, user_id = check_auth(mock_req)
            assert claims == fake_claims
            assert user_id == "user-1"


# ---------------------------------------------------------------------------
# require_auth decorator
# ---------------------------------------------------------------------------


class TestRequireAuth:
    def test_passes_through_when_auth_disabled(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse(json.dumps({"user": user_id}), mimetype="application/json")

        mock_req = MagicMock()
        mock_req.method = "POST"

        with patch("blueprints._helpers.auth_enabled", return_value=False):
            resp = my_endpoint(mock_req)
            body = json.loads(resp.get_body())
            assert body["user"] == "anonymous"

    def test_returns_401_on_bad_token(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"Authorization": "Bearer bad"}

        with (
            patch("blueprints._helpers.auth_enabled", return_value=True),
            patch("blueprints._helpers.validate_token", side_effect=ValueError("Token expired")),
        ):
            resp = my_endpoint(mock_req)
            assert resp.status_code == 401
            body = json.loads(resp.get_body())
            assert "expired" in body["error"]

    def test_handles_options_preflight(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "OPTIONS"

        with patch("blueprints._helpers.auth_enabled", return_value=True):
            resp = my_endpoint(mock_req)
            assert resp.status_code == 204


# ---------------------------------------------------------------------------
# CORS headers include Authorization
# ---------------------------------------------------------------------------


class TestCorsHeaders:
    def test_authorization_in_allowed_headers(self):
        import azure.functions as func

        from blueprints._helpers import cors_headers

        req = func.HttpRequest(
            method="OPTIONS",
            url="/api/test",
            headers={"Origin": "https://polite-glacier-0d6885003.4.azurestaticapps.net"},
            body=b"",
        )
        headers = cors_headers(req)
        assert "Authorization" in headers["Access-Control-Allow-Headers"]
