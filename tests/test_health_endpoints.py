"""Tests for health, readiness, and contract endpoints (blueprints/health.py).

Covers:
- Response status codes and JSON bodies
- CORS headers on GET responses (cross-origin API discovery)
- OPTIONS preflight handling
- Unknown origins are rejected
"""

import json

from blueprints.health import contract, health, readiness
from tests.conftest import TEST_LOCAL_ORIGIN, TEST_ORIGIN, make_test_request
from treesight import __git_sha__, __version__
from treesight.constants import API_CONTRACT_VERSION

_ALLOWED_ORIGIN = TEST_LOCAL_ORIGIN
_CUSTOM_DOMAIN_ORIGIN = TEST_ORIGIN
_UNKNOWN_ORIGIN = "https://evil.example.com"


def _make_req(method="GET", origin=_ALLOWED_ORIGIN):
    return make_test_request(
        url="/api/health",
        method=method,
        origin=origin,
        auth_header=None,
    )


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_200(self):
        resp = health(_make_req())
        assert resp.status_code == 200

    def test_body_is_healthy(self):
        resp = health(_make_req())
        body = json.loads(resp.get_body())
        assert body["status"] == "healthy"
        assert body["version"] == __version__
        assert body["commit"] == __git_sha__

    def test_cors_header_for_allowed_origin(self):
        resp = health(_make_req())
        assert resp.headers.get("Access-Control-Allow-Origin") == _ALLOWED_ORIGIN

    def test_cors_header_for_custom_domain(self):
        resp = health(_make_req(origin=_CUSTOM_DOMAIN_ORIGIN))
        assert resp.headers.get("Access-Control-Allow-Origin") == _CUSTOM_DOMAIN_ORIGIN

    def test_no_cors_header_for_unknown_origin(self):
        resp = health(_make_req(origin=_UNKNOWN_ORIGIN))
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_options_returns_204(self):
        resp = health(_make_req(method="OPTIONS"))
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# /api/readiness
# ---------------------------------------------------------------------------


class TestReadiness:
    def test_returns_200(self):
        resp = readiness(_make_req())
        assert resp.status_code == 200

    def test_body_contains_status_and_version(self):
        resp = readiness(_make_req())
        body = json.loads(resp.get_body())
        assert body["status"] == "ready"
        assert body["api_version"] == API_CONTRACT_VERSION
        assert body["version"] == __version__
        assert body["commit"] == __git_sha__

    def test_cors_header_for_allowed_origin(self):
        resp = readiness(_make_req())
        assert resp.headers.get("Access-Control-Allow-Origin") == _ALLOWED_ORIGIN

    def test_no_cors_header_for_unknown_origin(self):
        resp = readiness(_make_req(origin=_UNKNOWN_ORIGIN))
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_options_returns_204(self):
        resp = readiness(_make_req(method="OPTIONS"))
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# /api/contract
# ---------------------------------------------------------------------------


class TestContract:
    def test_returns_200(self):
        resp = contract(_make_req())
        assert resp.status_code == 200

    def test_body_contains_version(self):
        resp = contract(_make_req())
        body = json.loads(resp.get_body())
        assert body["api_version"] == API_CONTRACT_VERSION

    def test_cors_header_for_allowed_origin(self):
        resp = contract(_make_req())
        assert resp.headers.get("Access-Control-Allow-Origin") == _ALLOWED_ORIGIN

    def test_no_cors_header_for_unknown_origin(self):
        resp = contract(_make_req(origin=_UNKNOWN_ORIGIN))
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_options_returns_204(self):
        resp = contract(_make_req(method="OPTIONS"))
        assert resp.status_code == 204
