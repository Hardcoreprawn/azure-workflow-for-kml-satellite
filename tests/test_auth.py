"""Tests for SWA built-in auth (X-MS-CLIENT-PRINCIPAL header parsing)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from treesight.security.auth import (
    auth_enabled,
    get_user_id,
    parse_bearer_token,
    parse_client_principal,
)


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


# ---------------------------------------------------------------------------
# parse_client_principal
# ---------------------------------------------------------------------------


class TestParseClientPrincipal:
    def test_decodes_valid_principal(self):
        header = _encode_principal(user_id="user-42", user_details="u@e.com")
        result = parse_client_principal(header)
        assert result["userId"] == "user-42"
        assert result["userDetails"] == "u@e.com"
        assert result["identityProvider"] == "aad"

    def test_raises_on_empty_header(self):
        with pytest.raises(ValueError, match="Missing X-MS-CLIENT-PRINCIPAL"):
            parse_client_principal("")

    def test_raises_on_invalid_base64(self):
        with pytest.raises(ValueError, match="Malformed"):
            parse_client_principal("not-valid-base64!!!")

    def test_raises_on_non_json(self):
        header = base64.b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Malformed"):
            parse_client_principal(header)

    def test_raises_when_user_id_missing(self):
        header = base64.b64encode(json.dumps({"identityProvider": "aad"}).encode()).decode()
        with pytest.raises(ValueError, match="missing userId"):
            parse_client_principal(header)

    def test_raises_when_user_id_empty(self):
        header = base64.b64encode(json.dumps({"userId": ""}).encode()).decode()
        with pytest.raises(ValueError, match="missing userId"):
            parse_client_principal(header)

    def test_preserves_all_fields(self):
        header = _encode_principal(
            user_id="u1",
            user_details="name",
            identity_provider="github",
            user_roles=["authenticated", "admin"],
        )
        result = parse_client_principal(header)
        assert result["identityProvider"] == "github"
        assert result["userRoles"] == ["authenticated", "admin"]


# ---------------------------------------------------------------------------
# get_user_id
# ---------------------------------------------------------------------------


class TestGetUserId:
    def test_extracts_user_id(self):
        assert get_user_id({"userId": "user-123"}) == "user-123"

    def test_returns_empty_when_missing(self):
        assert get_user_id({}) == ""


class TestParseBearerToken:
    def test_extracts_token(self):
        assert parse_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"

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
    def test_rejects_when_bearer_disabled(self):
        from treesight.security.auth import verify_bearer_token

        with patch("treesight.security.auth.CIAM_BEARER_AUTH_ENABLED", False):
            with pytest.raises(ValueError, match="not enabled"):
                verify_bearer_token("token")

    def test_rejects_when_config_missing(self):
        from treesight.security.auth import verify_bearer_token

        with patch("treesight.security.auth.CIAM_BEARER_AUTH_ENABLED", True):
            with patch("treesight.security.auth.CIAM_JWT_ISSUER", ""):
                with pytest.raises(ValueError, match="not configured"):
                    verify_bearer_token("token")

    def test_verifies_token_with_expected_claims(self):
        from treesight.security.auth import verify_bearer_token

        fake_key_client = MagicMock()
        fake_key_client.get_signing_key_from_jwt.return_value = MagicMock(key="public-key")

        with patch("treesight.security.auth.CIAM_BEARER_AUTH_ENABLED", True):
            with patch("treesight.security.auth.CIAM_JWT_ISSUER", "https://issuer.example"):
                with patch("treesight.security.auth.CIAM_JWT_AUDIENCE", "audience-id"):
                    with patch(
                        "treesight.security.auth.CIAM_JWKS_URL", "https://issuer.example/keys"
                    ):
                        with patch("treesight.security.auth.CIAM_JWT_LEEWAY_SECONDS", 60):
                            with patch(
                                "treesight.security.auth._jwks_client",
                                return_value=fake_key_client,
                            ):
                                with patch("jwt.decode") as decode:
                                    decode.return_value = {"sub": "user-sub"}

                                    claims = verify_bearer_token("abc.def.ghi")

        assert claims["sub"] == "user-sub"
        decode.assert_called_once_with(
            "abc.def.ghi",
            key="public-key",
            algorithms=["RS256"],
            audience="audience-id",
            issuer="https://issuer.example",
            leeway=60,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )

    def test_rejects_when_subject_missing(self):
        from treesight.security.auth import verify_bearer_token

        fake_key_client = MagicMock()
        fake_key_client.get_signing_key_from_jwt.return_value = MagicMock(key="public-key")

        with patch("treesight.security.auth.CIAM_BEARER_AUTH_ENABLED", True):
            with patch("treesight.security.auth.CIAM_JWT_ISSUER", "https://issuer.example"):
                with patch("treesight.security.auth.CIAM_JWT_AUDIENCE", "audience-id"):
                    with patch(
                        "treesight.security.auth.CIAM_JWKS_URL", "https://issuer.example/keys"
                    ):
                        with patch(
                            "treesight.security.auth._jwks_client",
                            return_value=fake_key_client,
                        ):
                            with patch(
                                "jwt.decode", return_value={"iss": "https://issuer.example"}
                            ):
                                with pytest.raises(ValueError, match="missing subject"):
                                    verify_bearer_token("abc.def.ghi")


# ---------------------------------------------------------------------------
# check_auth helper (from _helpers.py)
# ---------------------------------------------------------------------------


class TestCheckAuth:
    @pytest.fixture(autouse=True)
    def _no_hmac(self):
        """Ensure AUTH_HMAC_KEY is unset for non-HMAC tests (#572 review)."""
        with patch("blueprints._helpers.AUTH_HMAC_KEY", ""):
            yield

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

    def test_returns_principal_and_user_id(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-99")}

        principal, user_id = check_auth(mock_req)
        assert principal["userId"] == "u-99"
        assert user_id == "u-99"

    def test_raises_on_malformed_header(self):
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": "garbage"}

        with pytest.raises(ValueError, match="Malformed"):
            check_auth(mock_req)

    def test_verifies_hmac_when_key_configured(self):
        """check_auth must verify HMAC when AUTH_HMAC_KEY is set (#572)."""
        from blueprints._helpers import check_auth
        from treesight.security.auth import sign_session_token

        key = "test-hmac-key-32chars-minimum!!!"
        session = sign_session_token("u-99", key=key)
        mock_req = MagicMock()
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-99"),
            "X-Auth-Session": session["token"],
        }

        with patch("blueprints._helpers.AUTH_HMAC_KEY", key):
            _principal, user_id = check_auth(mock_req)
            assert user_id == "u-99"

    def test_rejects_missing_hmac_when_key_configured(self):
        """check_auth must reject requests without HMAC when key is set (#572)."""
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-99"),
        }

        with patch("blueprints._helpers.AUTH_HMAC_KEY", "some-key"):
            with pytest.raises(ValueError, match="X-Auth-Session"):
                check_auth(mock_req)

    def test_rejects_forged_hmac_when_key_configured(self):
        """check_auth must reject forged HMAC tokens (#572)."""
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-99"),
            "X-Auth-Session": "forged-token-value",
        }

        with patch("blueprints._helpers.AUTH_HMAC_KEY", "some-key"):
            with pytest.raises(ValueError):
                check_auth(mock_req)

    def test_accepts_valid_bearer_token(self):
        """check_auth accepts bearer JWT when verification succeeds (#709)."""
        from blueprints._helpers import check_auth

        mock_req = MagicMock()
        mock_req.headers = {
            "Authorization": "Bearer valid.jwt.token",
        }

        with patch("blueprints._helpers.verify_bearer_token") as verify:
            verify.return_value = {"sub": "jwt-user", "iss": "https://issuer.example"}
            claims, user_id = check_auth(mock_req)

        assert claims["sub"] == "jwt-user"
        assert user_id == "jwt-user"

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

    def test_returns_401_on_malformed_principal(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse("OK")

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {"X-MS-CLIENT-PRINCIPAL": "bad-data"}

        resp = my_endpoint(mock_req)
        assert resp.status_code == 401

    def test_injects_auth_kwargs_on_valid_principal(self):
        from blueprints._helpers import require_auth

        @require_auth
        def my_endpoint(req, auth_claims=None, user_id=None):
            import azure.functions as func

            return func.HttpResponse(
                json.dumps({"user": user_id, "provider": auth_claims.get("identityProvider")}),
                mimetype="application/json",
            )

        mock_req = MagicMock()
        mock_req.method = "POST"
        mock_req.headers = {
            "X-MS-CLIENT-PRINCIPAL": _encode_principal(user_id="u-1", identity_provider="github")
        }

        resp = my_endpoint(mock_req)
        body = json.loads(resp.get_body())
        assert body["user"] == "u-1"
        assert body["provider"] == "github"

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
            verify.return_value = {"sub": "jwt-user"}
            resp = my_endpoint(mock_req)

        body = json.loads(resp.get_body())
        assert body["user"] == "jwt-user"
        assert body["subject"] == "jwt-user"

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
