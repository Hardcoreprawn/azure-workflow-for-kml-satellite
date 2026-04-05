from __future__ import annotations

from scripts import validate_dev_infra_gate as validate


def test_find_first_value_recurses_nested_payloads() -> None:
    payload = {
        "properties": {
            "destination": {
                "properties": {"endpointUrl": "https://example.invalid/runtime/webhooks/eventgrid"}
            }
        }
    }

    assert validate.find_first_value(payload, "endpointUrl") == (
        "https://example.invalid/runtime/webhooks/eventgrid"
    )


def test_find_first_value_returns_none_when_absent() -> None:
    assert validate.find_first_value({"properties": {}}, "endpointUrl") is None


def test_validate_gate_requests_full_eventgrid_endpoint_url(monkeypatch) -> None:
    calls: list[list[str]] = []
    function_key = "test-eventgrid-key"
    expected_endpoint = validate.reconcile.build_eventgrid_endpoint(
        hostname="example.invalid",
        function_name=validate.reconcile.DEFAULT_FUNCTION_NAME,
        function_key=function_key,
    )

    def fake_fetch_json(url: str) -> dict[str, str]:
        if url.endswith("/api/health"):
            return {"status": "healthy"}
        if url.endswith("/api/readiness"):
            return {"status": "ready"}
        raise AssertionError(url)

    def fake_run_az_json(args: list[str]):
        calls.append(args)
        if args[:3] == ["functionapp", "keys", "list"]:
            return {"systemKeys": {"eventgrid_extension": function_key}}
        if args[:4] == ["eventgrid", "system-topic", "event-subscription", "show"]:
            return {"destination": {"endpointUrl": expected_endpoint}}
        if args[:4] == ["monitor", "log-analytics", "workspace", "show"]:
            return {"workspaceCapping": {"dailyQuotaGb": 0.1}}
        raise AssertionError(args)

    def fake_resolve_workspace_name(resource_group: str, workspace_name: str | None) -> str:
        del resource_group, workspace_name
        return "log-kmlsat-dev"

    monkeypatch.setattr(validate, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(validate, "run_az_json", fake_run_az_json)
    monkeypatch.setattr(validate, "resolve_workspace_name", fake_resolve_workspace_name)

    validate.validate_gate(
        resource_group="rg-kmlsat-dev",
        function_app="func-kmlsat-dev",
        hostname="example.invalid",
        system_topic_name="evgt-kmlsat-dev",
        subscription_name=validate.reconcile.DEFAULT_SUBSCRIPTION_NAME,
        function_name=validate.reconcile.DEFAULT_FUNCTION_NAME,
        expected_daily_cap_gb=0.1,
        workspace_name=None,
    )

    show_call = next(
        args
        for args in calls
        if args[:4] == ["eventgrid", "system-topic", "event-subscription", "show"]
    )
    assert "--include-full-endpoint-url" in show_call


def test_validate_gate_reports_redacted_endpoint_details_on_mismatch(monkeypatch) -> None:
    function_key = "expected-secret"

    def fake_fetch_json(url: str) -> dict[str, str]:
        if url.endswith("/api/health"):
            return {"status": "healthy"}
        if url.endswith("/api/readiness"):
            return {"status": "ready"}
        raise AssertionError(url)

    def fake_run_az_json(args: list[str]):
        if args[:3] == ["functionapp", "keys", "list"]:
            return {"systemKeys": {"eventgrid_extension": function_key}}
        if args[:4] == ["eventgrid", "system-topic", "event-subscription", "show"]:
            return {
                "destination": {
                    "endpointUrl": (
                        "https://example.invalid/runtime/webhooks/eventgrid"
                        "?functionName=blob_trigger&code=actual-secret"
                    )
                }
            }
        if args[:4] == ["monitor", "log-analytics", "workspace", "show"]:
            return {"workspaceCapping": {"dailyQuotaGb": 0.1}}
        raise AssertionError(args)

    monkeypatch.setattr(validate, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(validate, "run_az_json", fake_run_az_json)
    monkeypatch.setattr(validate, "resolve_workspace_name", lambda *_: "log-kmlsat-dev")

    try:
        validate.validate_gate(
            resource_group="rg-kmlsat-dev",
            function_app="func-kmlsat-dev",
            hostname="example.invalid",
            system_topic_name="evgt-kmlsat-dev",
            subscription_name=validate.reconcile.DEFAULT_SUBSCRIPTION_NAME,
            function_name=validate.reconcile.DEFAULT_FUNCTION_NAME,
            expected_daily_cap_gb=0.1,
            workspace_name=None,
        )
    except RuntimeError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("validate_gate should have raised on endpoint mismatch")

    assert "expected-secret" not in message
    assert "actual-secret" not in message
    assert "code=%2A%2A%2AREDACTED%2A%2A%2A" in message
    assert "functionName=blob_trigger" in message


def test_validate_gate_can_skip_eventgrid_subscription_checks(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_fetch_json(url: str) -> dict[str, str]:
        if url.endswith("/api/health"):
            return {"status": "healthy"}
        if url.endswith("/api/readiness"):
            return {"status": "ready"}
        raise AssertionError(url)

    def fake_run_az_json(args: list[str]):
        calls.append(args)
        if args[:4] == ["monitor", "log-analytics", "workspace", "show"]:
            return {"workspaceCapping": {"dailyQuotaGb": 0.1}}
        raise AssertionError(args)

    monkeypatch.setattr(validate, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(validate, "run_az_json", fake_run_az_json)
    monkeypatch.setattr(validate, "resolve_workspace_name", lambda *_: "log-kmlsat-dev")

    validate.validate_gate(
        resource_group="rg-kmlsat-dev",
        function_app="func-kmlsat-dev",
        hostname="example.invalid",
        system_topic_name="evgt-kmlsat-dev",
        subscription_name=validate.reconcile.DEFAULT_SUBSCRIPTION_NAME,
        function_name=validate.reconcile.DEFAULT_FUNCTION_NAME,
        expected_daily_cap_gb=0.1,
        workspace_name=None,
        validate_eventgrid_subscription=False,
    )

    assert calls == [
        [
            "monitor",
            "log-analytics",
            "workspace",
            "show",
            "--resource-group",
            "rg-kmlsat-dev",
            "--workspace-name",
            "log-kmlsat-dev",
        ]
    ]
