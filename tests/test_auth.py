"""Tests for auth helpers (bearer JWT and legacy principal parsing utils)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from treesight.security.auth import auth_enabled, parse_bearer_token


def _encode_principal(
    user_id: str = "abc-123",
    user_details: str = "user@example.com",
    identity_provider: str = "aad",
    user_roles: list[str] | None = None,
) -> str:
    """Build a Base64-encoded X-MS-CLIENT-PRINCIPAL value."""
    principal = {
        "identityProvider": identity_provider,
        "userId": user_id,
        "userDetails": user_details,
        "userRoles": user_roles or ["anonymous", "authenticated"],
    }
    return base64.b64encode(json.dumps(principal).encode()).decode()


# ---------------------------------------------------------------------------
# auth_enabled
# ---------------------------------------------------------------------------


class TestAuthEnabled:
    def test_always_returns_true(self):
        assert auth_enabled() is True


class TestParseBearerToken:
    def test_extracts_token(self):
        assert parse_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"

    def test_extracts_token_with_lowercase_scheme(self):
        assert parse_bearer_token("bearer abc.def.ghi") == "abc.def.ghi"

    def test_returns_none_when_missing(self):
        assert parse_bearer_token("") is None

    def test_returns_none_on_non_bearer(self):
        assert parse_bearer_token("Basic abc123") is None

    def test_returns_none_on_non_string_header(self):
        assert parse_bearer_token(None) is None

    def test_raises_on_empty_bearer_value(self):
        with pytest.raises(ValueError, match="Missing bearer token"):
            parse_bearer_token("Bearer   ")


class TestVerifyBearerToken:
    def test_rejects_when_config_missing(self):
        from treesight.security.auth import verify_bearer_token

        with patch("treesight.security.auth.CIAM_AUTHORITY", ""):
            with pytest.raises(ValueError, match="not configured"):
                verify_bearer_token("token")

    def test_verifies_token_with_expected_claims(self):
        from treesight.security.auth import verify_bearer_token

        fake_key_client = MagicMock()
        fake_key_client.get_signing_key_from_jwt.return_value = MagicMock(key="public-key")

        metadata = {"issuer": "https://issuer.example", "jwks_uri": "https://issuer.example/keys"}

        with patch("treesight.security.auth.CIAM_AUTHORITY", "https://issuer.example"):
            with patch("treesight.security.auth.CIAM_TENANT_ID", "tenant-id"):
                with patch("treesight.security.auth.CIAM_API_AUDIENCE", "audience-id"):
                    with patch("treesight.security.auth.CIAM_JWT_LEEWAY_SECONDS", 60):
                        with patch(
                            "treesight.security.auth._oidc_metadata",
                            return_value=metadata,
                        ):
                            with patch(
                                "treesight.security.auth._jwks_client",
                                return_value=fake_key_client,
                            ):
                                with patch("jwt.decode") as decode:
                                    decode.return_value = {
                                        "tid": "tenant-id",
                                        "oid": "object-id",
                                        "ver": "2.0",
                                        "nbf": 1,
                                        "exp": 2,
                                        "iss": "https://issuer.example",
                                        "aud": "audience-id",
                                    }

                                    claims = verify_bearer_token("abc.def.ghi")

        assert claims["oid"] == "object-id"
        decode.assert_called_once_with(
            "abc.def.ghi",
            key="public-key",
            algorithms=["RS256"],
            audience="audience-id",
            issuer="https://issuer.example",
            leeway=60,
            options={"require": ["exp", "iss", "aud", "nbf", "tid", "oid", "ver"]},
        )

    def test_rejects_when_subject_missing(self):
        from treesight.security.auth import verify_bearer_token

        fake_key_client = MagicMock()
        fake_key_client.get_signing_key_from_jwt.return_value = MagicMock(key="public-key")

        metadata = {"issuer": "https://issuer.example", "jwks_uri": "https://issuer.example/keys"}

        with patch("treesight.security.auth.CIAM_AUTHORITY", "https://issuer.example"):
            with patch("treesight.security.auth.CIAM_TENANT_ID", "tenant-id"):
                with patch("treesight.security.auth.CIAM_API_AUDIENCE", "audience-id"):
                    with patch("treesight.security.auth._oidc_metadata", return_value=metadata):
                        with patch(
                            "treesight.security.auth._jwks_client",
                            return_value=fake_key_client,
                        ):
                            with patch(
                                "jwt.decode",
                                return_value={
                                    "ver": "2.0",
                                    "nbf": 1,
                                    "exp": 2,
                                    "iss": "https://issuer.example",
                                    "aud": "audience-id",
                                },
                            ):
                                with pytest.raises(ValueError, match="missing subject"):
                                    verify_bearer_token("abc.def.ghi")


# ---------------------------------------------------------------------------
# check_auth helper (from _helpers.py)
# ---------------------------------------------------------------------------


class TestCheckAuth:
    def test_returns_anonymous_when_no_header_and_auth_not_required(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {}

        with patch.dict("os.environ", {}, clear=False):
            # Ensure REQUIRE_AUTH is not set
            import os

            os.environ.pop("REQUIRE_AUTH", None)
            claims, user_id = check_auth(mock_req)
            assert claims == {}
            assert user_id == "anonymous"

    def test_raises_when_no_header_and_auth_required(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {}

        with patch.dict("os.environ", {"REQUIRE_AUTH": "1"}):
            with pytest.raises(ValueError, match="Authentication required"):
                check_auth(mock_req)

    def test_accepts_valid_bearer_token(self):
        """check_auth accepts bearer JWT when verification succeeds (#709)."""
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {
            "Authorization": "Bearer valid.jwt.token",
        }

        with patch("blueprints._helpers.verify_bearer_token") as verify:
            verify.return_value = {"tid": "tenant-id", "oid": "object-id", "ver": "2.0"}
            claims, user_id = check_auth(mock_req)

        assert claims["oid"] == "object-id"
        assert user_id == "tenant-id:object-id"

    def test_rejects_invalid_bearer_token(self):
        """check_auth rejects invalid bearer JWT with a user-safe message (#709)."""
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {
            "Authorization": "Bearer invalid.jwt.token",
        }

        with patch("blueprints._helpers.verify_bearer_token") as verify:
            verify.side_effect = ValueError("Invalid bearer token")
            with pytest.raises(ValueError, match="Invalid bearer token"):
                check_auth(mock_req)

    def test_rejects_legacy_principal_only_request_when_auth_required(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-99"),
        }

        with patch.dict("os.environ", {"REQUIRE_AUTH": "1"}):
            with pytest.raises(ValueError, match="Authentication required"):
                check_auth(mock_req)


# ---------------------------------------------------------------------------
# require_auth decorator
# ---------------------------------------------------------------------------


class TestRequireAuth:
    def test_passes_through_when_no_header_and_auth_not_required(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse(json.dumps({"user": user_id}), mimetype="application/json")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {}

        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("REQUIRE_AUTH", None)
            resp = my_endpoint(mock_req)
            body = json.loads(resp.get_body())
            assert body["user"] == "anonymous"

    def test_returns_401_when_no_header_and_auth_required(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {}

        with patch.dict("os.environ", {"REQUIRE_AUTH": "1"}):
            resp = my_endpoint(mock_req)
            assert resp.status_code == 401

    def test_returns_401_on_legacy_principal_only_request_when_auth_required(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": "bad-data"}

        with patch.dict("os.environ", {"REQUIRE_AUTH": "1"}):
            resp = my_endpoint(mock_req)
        assert resp.status_code == 401

    def test_handles_options_preflight(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "OPTIONS"

        resp = my_endpoint(mock_req)
        assert resp.status_code == 204

    def test_accepts_valid_bearer_token(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse(
                json.dumps({"user": user_id, "subject": auth_claims.get("sub")}),
                mimetype="application/json",
            )

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {
            "Authorization": "Bearer valid.jwt.token",
        }

        with patch("blueprints._helpers.verify_bearer_token") as verify:
            verify.return_value = {"tid": "tenant-id", "oid": "object-id", "ver": "2.0"}
            resp = my_endpoint(mock_req)

        body = json.loads(resp.get_body())
        assert body["user"] == "tenant-id:object-id"
        assert body["subject"] is None

    def test_rejects_invalid_bearer_token(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {
            "Authorization": "Bearer invalid.jwt.token",
        }

        with patch("blueprints._helpers.verify_bearer_token") as verify:
            verify.side_effect = ValueError("Invalid bearer token")
            resp = my_endpoint(mock_req)

        assert resp.status_code == 401

    def test_rejects_legacy_principal_when_auth_required(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-1")}

        with patch.dict("os.environ", {"REQUIRE_AUTH": "1"}):
            resp = my_endpoint(mock_req)

        assert resp.status_code == 401


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
            headers={"Origin": "https://canopex.hrdcrprwn.com"},
            body=b"",
        )
        headers = cors_headers(req)
        assert "Authorization" in headers["Access-Control-Allow-Headers"]
