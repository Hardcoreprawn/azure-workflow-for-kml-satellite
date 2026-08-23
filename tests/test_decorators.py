"""Tests for blueprints._decorators — rate_limit, validate_body_size, authenticated_http_route.

Covers the four acceptance-criteria scenarios:
    - OPTIONS → 204 CORS preflight (via require_auth)
    - Missing auth → 401
    - Rate-limited → 429
    - Body too large → 400

Also covers the composable and unified decorator paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import azure.functions as func
import pytest

from blueprints._decorators import authenticated_http_route, rate_limit, validate_body_size
from blueprints._helpers import require_auth
from tests.conftest import TEST_ORIGIN, make_test_request

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_req(
    method: str = "GET",
    body: bytes = b"",
    *,
    with_auth: bool = True,
    origin: str | None = TEST_ORIGIN,
) -> func.HttpRequest:
    return make_test_request(
        url="/api/test",
        method=method,
        body=body,
        origin=origin,
        auth_header="******" if with_auth else None,
        principal_user_id="test-user" if with_auth else None,
    )


def _echo_handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
    """Minimal handler that echoes the request method as a 200."""
    return func.HttpResponse("ok", status_code=200)


def _echo_with_user(req: func.HttpRequest, *, user_id: str, auth_claims: dict, **kwargs) -> func.HttpResponse:
    return func.HttpResponse(user_id, status_code=200)


_REQUIRE_AUTH_ON = patch.dict("os.environ", {"REQUIRE_AUTH": "1"})


# ---------------------------------------------------------------------------
# rate_limit decorator
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_allows_request_when_limiter_permits(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @rate_limit(limiter)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 200

    def test_accepts_callable_factory_resolved_per_request(self):
        """rate_limit(factory) resolves the limiter on every request."""
        inner = MagicMock()
        inner.is_allowed.return_value = True
        call_count = [0]

        def factory():
            call_count[0] += 1
            return inner

        @rate_limit(factory)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        handler(_make_req())
        handler(_make_req())
        assert call_count[0] == 2  # resolved per-request

    def test_returns_429_when_limiter_rejects(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = False

        @rate_limit(limiter)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 429

    def test_429_body_contains_message(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = False

        @rate_limit(limiter)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        resp = handler(_make_req())
        assert "Too many requests" in resp.get_body().decode()

    def test_passes_kwargs_through_to_handler(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True
        received: dict = {}

        @rate_limit(limiter)
        def handler(req: func.HttpRequest, *, user_id: str, **kwargs) -> func.HttpResponse:
            received["user_id"] = user_id
            return func.HttpResponse("ok", status_code=200)

        handler(_make_req(), user_id="alice")
        assert received["user_id"] == "alice"

    def test_preserves_function_name(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @rate_limit(limiter)
        def my_handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        assert my_handler.__name__ == "my_handler"


# ---------------------------------------------------------------------------
# validate_body_size decorator
# ---------------------------------------------------------------------------


class TestValidateBodySize:
    def test_allows_request_within_limit(self):
        @validate_body_size(100)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req(body=b"x" * 50)
        resp = handler(req)
        assert resp.status_code == 200

    def test_allows_request_at_exact_limit(self):
        @validate_body_size(100)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req(body=b"x" * 100)
        resp = handler(req)
        assert resp.status_code == 200

    def test_returns_400_when_body_exceeds_limit(self):
        @validate_body_size(100)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req(body=b"x" * 101)
        resp = handler(req)
        assert resp.status_code == 400

    def test_400_body_contains_max_bytes(self):
        @validate_body_size(100)
        def handler(req: func.HttpRequest, **kwargs) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        resp = handler(_make_req(body=b"x" * 200))
        body = resp.get_body().decode()
        assert "100" in body
        assert "too large" in body.lower() or "body" in body.lower()

    def test_passes_kwargs_through_to_handler(self):
        received: dict = {}

        @validate_body_size(1000)
        def handler(req: func.HttpRequest, *, user_id: str, **kwargs) -> func.HttpResponse:
            received["user_id"] = user_id
            return func.HttpResponse("ok", status_code=200)

        handler(_make_req(body=b"small"), user_id="bob")
        assert received["user_id"] == "bob"


# ---------------------------------------------------------------------------
# Composable stack: @require_auth @rate_limit @validate_body_size
# ---------------------------------------------------------------------------


class TestComposableStack:
    def test_options_returns_cors_preflight(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @require_auth
        @rate_limit(limiter)
        @validate_body_size(1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = make_test_request(method="OPTIONS", origin=TEST_ORIGIN, auth_header=None, principal_user_id=None)
        resp = handler(req)
        assert resp.status_code == 204

    @_REQUIRE_AUTH_ON
    def test_missing_auth_returns_401(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @require_auth
        @rate_limit(limiter)
        @validate_body_size(1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = make_test_request(method="GET", origin=TEST_ORIGIN, auth_header=None, principal_user_id=None)
        resp = handler(req)
        assert resp.status_code == 401

    def test_rate_limited_returns_429(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = False

        @require_auth
        @rate_limit(limiter)
        @validate_body_size(1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 429

    def test_body_too_large_returns_400(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @require_auth
        @rate_limit(limiter)
        @validate_body_size(10)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req(body=b"x" * 100)
        resp = handler(req)
        assert resp.status_code == 400

    def test_valid_request_reaches_handler(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @require_auth
        @rate_limit(limiter)
        @validate_body_size(1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse(f"uid={user_id}", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 200
        assert "test-user" in resp.get_body().decode()


# ---------------------------------------------------------------------------
# authenticated_http_route unified decorator
# ---------------------------------------------------------------------------


class TestAuthenticatedHttpRoute:
    def test_options_returns_cors_preflight(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @authenticated_http_route(rate_limiter=limiter, max_body_bytes=1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = make_test_request(method="OPTIONS", origin=TEST_ORIGIN, auth_header=None, principal_user_id=None)
        resp = handler(req)
        assert resp.status_code == 204

    @_REQUIRE_AUTH_ON
    def test_missing_auth_returns_401(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @authenticated_http_route(rate_limiter=limiter, max_body_bytes=1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = make_test_request(method="GET", origin=TEST_ORIGIN, auth_header=None, principal_user_id=None)
        resp = handler(req)
        assert resp.status_code == 401

    def test_rate_limited_returns_429(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = False

        @authenticated_http_route(rate_limiter=limiter, max_body_bytes=1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 429

    def test_body_too_large_returns_400(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @authenticated_http_route(rate_limiter=limiter, max_body_bytes=10)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req(body=b"x" * 100)
        resp = handler(req)
        assert resp.status_code == 400

    def test_valid_request_reaches_handler(self):
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @authenticated_http_route(rate_limiter=limiter, max_body_bytes=1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse(f"uid={user_id}", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 200
        assert "test-user" in resp.get_body().decode()

    def test_no_rate_limiter_skips_rate_check(self):
        """Endpoints that pass rate_limiter=None should never see 429."""

        @authenticated_http_route(max_body_bytes=1000)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req()
        resp = handler(req)
        assert resp.status_code == 200

    def test_no_max_body_skips_body_check(self):
        """Endpoints that pass max_body_bytes=None accept any body size."""
        limiter = MagicMock()
        limiter.is_allowed.return_value = True

        @authenticated_http_route(rate_limiter=limiter)
        def handler(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        req = _make_req(body=b"x" * 1_000_000)
        resp = handler(req)
        assert resp.status_code == 200

    def test_preserves_function_name(self):
        @authenticated_http_route()
        def my_endpoint(req: func.HttpRequest, *, user_id: str, auth_claims: dict) -> func.HttpResponse:
            return func.HttpResponse("ok", status_code=200)

        assert my_endpoint.__name__ == "my_endpoint"
