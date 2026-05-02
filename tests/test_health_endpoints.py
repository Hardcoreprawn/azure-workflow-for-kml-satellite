"""Tests for health, readiness, and contract endpoints (blueprints/health.py).

Covers:
- Response status codes and JSON bodies
- CORS headers on GET responses (cross-origin API discovery)
- OPTIONS preflight handling
- Unknown origins are rejected
- /api/health/deep (#760) component checks and status derivation
"""

import json
from unittest.mock import patch

from blueprints.health import contract, health, health_deep, internal_smoke, readiness
from tests.conftest import TEST_LOCAL_ORIGIN, TEST_ORIGIN, make_test_request
from treesight import __git_sha__, __version__
from treesight.constants import API_CONTRACT_VERSION

_ALLOWED_ORIGIN = TEST_LOCAL_ORIGIN
_CUSTOM_DOMAIN_ORIGIN = TEST_ORIGIN
_UNKNOWN_ORIGIN = "https://evil.example.com"


def _make_req(method="GET", origin=_ALLOWED_ORIGIN, url="/api/health"):
    return make_test_request(
        url=url,
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


# ---------------------------------------------------------------------------
# /api/internal-smoke
# ---------------------------------------------------------------------------


class TestInternalSmoke:
    def test_returns_200_for_dev_orchestrator_host(self):
        resp = internal_smoke(
            _make_req(
                url="https://func-kmlsat-dev-orch.example.uksouth.azurecontainerapps.io/api/internal-smoke"
            )
        )
        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["status"] == "ok"
        assert body["scope"] == "internal-deploy-smoke"

    def test_returns_200_for_prd_orchestrator_host(self):
        resp = internal_smoke(
            _make_req(
                url="https://func-kmlsat-prd-orch.example.uksouth.azurecontainerapps.io/api/internal-smoke"
            )
        )
        assert resp.status_code == 200

    def test_returns_404_for_non_dev_hosts(self):
        resp = internal_smoke(_make_req(url="https://api.canopex.com/api/internal-smoke"))
        assert resp.status_code == 404

    def test_options_returns_204_for_dev_orchestrator_host(self):
        resp = internal_smoke(
            _make_req(
                method="OPTIONS",
                url="https://func-kmlsat-dev-orch.example.uksouth.azurecontainerapps.io/api/internal-smoke",
            )
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# /api/health/deep (#760) — pre-demo infra smoke check
# ---------------------------------------------------------------------------

_CIAM_OK = {"status": "ok"}
_BLOB_OK = {"status": "ok"}
_PIPELINE_OK = {"status": "ok", "recent_completed": 1}
_CIAM_DOWN = {"status": "unreachable", "error": "timeout"}
_BLOB_DOWN = {"status": "unreachable", "error": "conn refused"}
_PIPELINE_NO_RUN = {"status": "no_recent_run"}


def _make_deep_req(method="GET", origin=_ALLOWED_ORIGIN):
    return _make_req(method=method, origin=origin, url="/api/health/deep")


class TestDeepHealth:
    def _call(
        self,
        ciam=_CIAM_OK,
        blob=_BLOB_OK,
        pipeline=_PIPELINE_OK,
        active=0,
        safe_mode=False,
        max_jobs=2,
    ):
        with (
            patch("blueprints.health._check_ciam", return_value=ciam),
            patch("blueprints.health._check_blob", return_value=blob),
            patch("blueprints.health._check_recent_pipeline", return_value=pipeline),
            patch("treesight.pipeline.concurrency.count_active_runs", return_value=active),
            patch("treesight.config.SAFE_MODE", safe_mode),
            patch("treesight.config.MAX_CONCURRENT_JOBS", max_jobs),
        ):
            return health_deep(_make_deep_req())

    def test_returns_200_always(self):
        resp = self._call(ciam=_CIAM_DOWN, blob=_BLOB_DOWN)
        assert resp.status_code == 200

    def test_body_healthy_when_all_ok(self):
        resp = self._call()
        body = json.loads(resp.get_body())
        assert body["status"] == "healthy"

    def test_body_failing_when_ciam_unreachable(self):
        resp = self._call(ciam=_CIAM_DOWN)
        body = json.loads(resp.get_body())
        assert body["status"] == "failing"

    def test_body_failing_when_blob_unreachable(self):
        resp = self._call(blob=_BLOB_DOWN)
        body = json.loads(resp.get_body())
        assert body["status"] == "failing"

    def test_body_degraded_when_no_recent_pipeline(self):
        resp = self._call(pipeline=_PIPELINE_NO_RUN)
        body = json.loads(resp.get_body())
        assert body["status"] == "degraded"

    def test_body_includes_config(self):
        resp = self._call(active=1, max_jobs=2, safe_mode=False)
        body = json.loads(resp.get_body())
        assert body["config"]["max_concurrent_jobs"] == 2
        assert body["config"]["active_runs"] == 1
        assert body["config"]["safe_mode"] is False

    def test_safe_mode_reflected_in_config(self):
        resp = self._call(safe_mode=True)
        body = json.loads(resp.get_body())
        assert body["config"]["safe_mode"] is True

    def test_components_returned_in_body(self):
        resp = self._call()
        body = json.loads(resp.get_body())
        assert "ciam" in body["components"]
        assert "blob" in body["components"]
        assert "recent_pipeline" in body["components"]

    def test_cors_header_for_allowed_origin(self):
        resp = self._call()
        assert resp.headers.get("Access-Control-Allow-Origin") == _ALLOWED_ORIGIN

    def test_no_cors_header_for_unknown_origin(self):
        with (
            patch("blueprints.health._check_ciam", return_value=_CIAM_OK),
            patch("blueprints.health._check_blob", return_value=_BLOB_OK),
            patch("blueprints.health._check_recent_pipeline", return_value=_PIPELINE_OK),
            patch("treesight.pipeline.concurrency.count_active_runs", return_value=0),
        ):
            resp = health_deep(_make_deep_req(origin=_UNKNOWN_ORIGIN))
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_options_returns_204(self):
        resp = health_deep(_make_deep_req(method="OPTIONS"))
        assert resp.status_code == 204
