"""Tests for SWA built-in auth (X-MS-CLIENT-PRINCIPAL header parsing)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from treesight.security.auth import (
    auth_enabled,
    get_user_id,
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
