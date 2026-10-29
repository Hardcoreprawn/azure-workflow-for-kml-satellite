"""Fail-closed tests for the full role-owned route matrix."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import azure.functions as func
import httpx
import pytest
from azure.core.exceptions import ResourceNotFoundError
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
        return httpx.Response(200 if request.method in {"GET", "OPTIONS"} else 400, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert validate_hosts(client, "http://worker", "http://admission")


def test_required_admission_method_rejection_fails_whole_matrix():
    def respond(request):
        path = request.url.path
        if path.endswith("this-route-does-not-exist"):
            return httpx.Response(404)
        if request.url.host == "worker" and path not in {"/api/health", "/api/readiness"}:
            return httpx.Response(404)
        if request.url.host == "admission" and request.method == "POST" and path == "/api/analysis/submit":
            return httpx.Response(405)
        return httpx.Response(200 if request.method in {"GET", "OPTIONS"} else 400, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert not validate_hosts(client, "http://worker", "http://admission")


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


@pytest.fixture(scope="module")
def mutation_handlers():
    from function_registration import register_function_blueprints

    application = func.FunctionApp()
    with patch.dict(os.environ, {"PIPELINE_ROLE": "orchestrator"}):
        register_function_blueprints(application, role="orchestrator")
    handlers = {}
    for function in application.get_functions():
        for binding in json.loads(function.get_function_json())["bindings"]:
            if binding["type"] != "httpTrigger":
                continue
            parameters = dict.fromkeys(re.findall(r"\{([^}]+)\}", binding["route"]), "role-boundary-missing")
            parameters.update({"format": "eudr-pdf", "aoi_index": "0"})
            path = "/api/" + binding["route"].format_map(parameters)
            for method in set(binding["methods"]) & {"POST", "PUT", "PATCH", "DELETE"}:
                handlers[RouteCheck(method, path)] = (function.get_user_function(), parameters)
    return handlers


@pytest.mark.parametrize("require_auth", ["false", "true"])
def test_mutating_probes_use_real_wrappers_without_domain_writes(monkeypatch, mutation_handlers, require_auth):
    """Malformed credentials reject even with auth disabled; public JSON handlers reject the body."""
    monkeypatch.setenv("REQUIRE_AUTH", require_auth)
    monkeypatch.delenv("OPS_DASHBOARD_KEY", raising=False)
    mutations = tuple(
        sorted(
            (route for route in ROUTES if route.method in {"POST", "PUT", "PATCH", "DELETE"}),
            key=lambda route: (route.path not in {"/api/org", "/api/user"}, route.key),
        )
    )
    assert set(mutations) == set(mutation_handlers)
    statuses = {}
    domain_boundaries = (
        "treesight.security.orgs.create_org",
        "treesight.security.users.delete_user",
        "treesight.security.users.update_user_profile",
        "treesight.storage.cosmos.upsert_item",
        "treesight.storage.cosmos.delete_item",
        "blueprints.billing._record_user_profile",
        "blueprints.billing._handle_event",
        "treesight.security.billing.save_subscription_emulation",
        "treesight.security.billing.clear_subscription_emulation",
        "blueprints.pipeline.submission.reserve_run",
        "blueprints.pipeline.submission.reserve_admission_slot",
        "blueprints.upload.UploadTokenHandler",
        "blueprints.contact.submit_contact",
    )
    with ExitStack() as stack:
        spies = {name: stack.enter_context(patch(name)) for name in domain_boundaries}
        stack.enter_context(patch("treesight.security.orgs.get_user_org", return_value=None))
        stack.enter_context(patch("treesight.security.users.get_user", return_value=None))
        # Exercise the configured webhook's real Stripe signature/JSON validation, not just its 503 shortcut.
        stack.enter_context(patch("blueprints.billing._stripe_configured", return_value=True))

        def respond(request):
            route = RouteCheck(request.method, request.url.path)
            handler, parameters = mutation_handlers[route]
            azure_request = func.HttpRequest(
                method=request.method,
                url=str(request.url),
                headers=dict(request.headers),
                route_params=parameters,
                body=request.content,
            )
            response = handler(azure_request)
            if inspect.isawaitable(response):
                response = asyncio.run(response)
            statuses[route.key] = response.status_code
            assert response.status_code in {400, 401}, (route.key, response.status_code)
            return httpx.Response(response.status_code, content=response.get_body())

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            results = check_host(client, "http://admission", mutations)
        assert all(state == RouteState.PRESENT for state in results.values())
        assert all(status in {400, 401} for status in statuses.values()), statuses
        for spy in spies.values():
            spy.assert_not_called()


def test_probe_credentials_cannot_be_overridden_by_client_defaults():
    def respond(request):
        assert request.headers["Authorization"] == "Bearer"
        assert not request.headers["X-MS-CLIENT-PRINCIPAL"]
        assert request.content == b"{"
        assert request.headers["Content-Type"] == "application/json"
        return httpx.Response(400)

    with httpx.Client(
        transport=httpx.MockTransport(respond),
        headers={"Authorization": "Bearer valid-user-token", "X-MS-CLIENT-PRINCIPAL": "test-principal"},
        auth=("user", "password"),
    ) as client:
        check_host(client, "http://admission", (RouteCheck("POST", "/api/org"),))


@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_accepted_mutating_probe_fails_whole_matrix(status):
    def respond(request):
        if request.url.path.endswith("this-route-does-not-exist"):
            return httpx.Response(404)
        if request.url.host == "worker" and request.url.path not in {"/api/health", "/api/readiness"}:
            return httpx.Response(404)
        if request.url.path == "/api/org" and request.method == "POST":
            return httpx.Response(status)
        return httpx.Response(200 if request.method in {"GET", "OPTIONS"} else 400)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert not validate_hosts(client, "http://worker", "http://admission")


@pytest.mark.parametrize("require_auth", ["false", "true"])
def test_probe_preserves_bounded_operational_rate_accounting(monkeypatch, mutation_handlers, require_auth):
    from treesight.security.rate_limit import TableRateLimiter

    monkeypatch.setenv("REQUIRE_AUTH", require_auth)
    service = MagicMock()
    table = service.get_table_client.return_value
    table.get_entity.side_effect = ResourceNotFoundError("new counter")
    limiter = TableRateLimiter(1, 60, "pipeline", table_service_client=service)
    monkeypatch.setattr("blueprints.eudr.get_pipeline_limiter", lambda: limiter)
    route = RouteCheck("POST", "/api/convert-coordinates")
    handler, _ = mutation_handlers[route]
    statuses = []

    def respond(request):
        response = handler(
            func.HttpRequest(
                method=request.method,
                url=str(request.url),
                headers=dict(request.headers),
                body=request.content,
            )
        )
        statuses.append(response.status_code)
        return httpx.Response(response.status_code, content=response.get_body())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert check_host(client, "http://admission", (route,))[route.key] == RouteState.PRESENT
        table.create_entity.assert_called_once()
        counter = table.create_entity.call_args.args[0]
        assert counter["count"] == 1
        table.get_entity.side_effect = None
        table.get_entity.return_value = counter
        assert check_host(client, "http://admission", (route,))[route.key] == RouteState.PRESENT
    assert statuses == [401, 429]
    table.create_entity.assert_called_once()
    table.update_entity.assert_not_called()
