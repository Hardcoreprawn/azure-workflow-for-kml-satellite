"""Fail-closed tests for the full role-owned route matrix."""

from __future__ import annotations

import httpx
import pytest
from validate_blueprint_parity import LOCAL_SMOKE_HOST, ROUTES, RouteCheck, RouteState, check_host, validate_hosts


@pytest.mark.parametrize("status", [301, 302, 307, 308, 500, 502, 503])
def test_redirects_and_server_errors_are_errors(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
        assert check_host(client, "http://worker", (RouteCheck("GET", "/api/x"),)) == {"GET /api/x": RouteState.ERROR}


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failure_cannot_prove_absence(error):
    def fail(request):
        raise error("unreachable", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        assert not validate_hosts(client, "http://worker", "http://admission")


@pytest.mark.parametrize("status", [200, 401, 403, 404])
def test_invalid_unknown_route_control_fails(status):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=b"not an empty 404"))
    ) as client:
        assert not validate_hosts(client, "http://worker", "http://admission")


def test_exact_method_route_coverage_has_no_overwrite():
    assert len({route.key for route in ROUTES}) == len(ROUTES)
    assert len(ROUTES) > 100
    assert RouteCheck("DELETE", "/api/user") in ROUTES
    assert RouteCheck("OPTIONS", "/api/analysis/submit") in ROUTES


def test_valid_matrix_and_positive_probes_pass():
    worker_routes = {"/api/health", "/api/readiness"}

    def respond(request):
        path = request.url.path
        if path.endswith("this-route-does-not-exist"):
            return httpx.Response(404)
        if request.url.host == "worker" and path not in worker_routes:
            return httpx.Response(404)
        return httpx.Response(200, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert validate_hosts(client, "http://worker", "http://admission")


def test_business_404_body_is_present_not_absent():
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "missing"}))
    ) as client:
        assert check_host(client, "http://worker", (RouteCheck("GET", "/api/x"),)) == {"GET /api/x": RouteState.PRESENT}


def test_guarded_smoke_uses_same_host_header_as_negative_control():
    def respond(request):
        assert request.headers["Host"] == LOCAL_SMOKE_HOST
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        check_host(client, "http://worker", (RouteCheck("GET", "/api/internal-smoke"),))
        assert not validate_hosts(client, "http://worker", "http://admission")


def test_unconfigured_webhook_requires_exact_application_response():
    routes = (RouteCheck("POST", "/api/billing/webhook"), RouteCheck("GET", "/api/health"))
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, content=b"Billing not configured"))
    ) as client:
        result = check_host(client, "http://worker", routes)
    assert result == {
        "POST /api/billing/webhook": RouteState.PRESENT,
        "GET /api/health": RouteState.ERROR,
    }
