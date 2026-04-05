from __future__ import annotations

from urllib import error

import pytest

from scripts import reconcile_eventgrid_subscription as reconcile


def test_select_eventgrid_key_prefers_eventgrid_system_key() -> None:
    payload = {
        "masterKey": "master",
        "systemKeys": {
            "eventgrid_extension": "event-grid-key",
            "eventgridextensionconfig_extension": "fallback-key",
        },
    }

    assert reconcile.select_eventgrid_key(payload) == "event-grid-key"


def test_select_eventgrid_key_falls_back_to_master_key() -> None:
    payload = {"masterKey": "master"}

    assert reconcile.select_eventgrid_key(payload) == "master"


def test_select_admin_key_uses_master_key() -> None:
    payload = {"masterKey": "master"}

    assert reconcile.select_admin_key(payload) == "master"


def test_find_first_value_recurses_nested_payloads() -> None:
    payload = {"properties": {"status": {"provisioningState": "Succeeded"}}}

    assert reconcile.find_first_value(payload, "provisioningState") == "Succeeded"


def test_build_eventgrid_endpoint_url_encodes_query_values() -> None:
    endpoint = reconcile.build_eventgrid_endpoint(
        hostname="func-kmlsat-dev.example.com",
        function_name="blob trigger/v1",
        function_key="abc+/=123",
    )

    assert endpoint == (
        "https://func-kmlsat-dev.example.com/runtime/webhooks/eventgrid"
        "?functionName=blob+trigger%2Fv1&code=abc%2B%2F%3D123"
    )


def test_build_subscription_command_includes_create_only_delivery_flags() -> None:
    command = reconcile.build_subscription_command(
        action="create",
        resource_group="rg-kmlsat-dev",
        system_topic_name="evgt-kmlsat-dev",
        subscription_name="evgs-kml-upload",
        endpoint="https://example.invalid/runtime/webhooks/eventgrid?functionName=blob_trigger&code=test",
    )

    assert "--max-delivery-attempts" in command
    assert "--event-ttl" in command
    assert "--max-events-per-batch" in command
    assert "--preferred-batch-size-in-kilobytes" in command
    assert "--only-show-errors" in command
    assert command[-2:] == ["-o", "none"]


def test_build_subscription_command_omits_create_only_delivery_flags_for_update() -> None:
    command = reconcile.build_subscription_command(
        action="update",
        resource_group="rg-kmlsat-dev",
        system_topic_name="evgt-kmlsat-dev",
        subscription_name="evgs-kml-upload",
        endpoint="https://example.invalid/runtime/webhooks/eventgrid?functionName=blob_trigger&code=test",
    )

    assert "--max-delivery-attempts" not in command
    assert "--event-ttl" not in command
    assert "--max-events-per-batch" not in command
    assert "--preferred-batch-size-in-kilobytes" not in command
    assert "--only-show-errors" in command
    assert command[-2:] == ["-o", "none"]


def test_wait_for_function_index_hits_admin_endpoint(monkeypatch) -> None:
    requests: list[tuple[str, str | None, int]] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout: int):
        requests.append((req.full_url, req.headers.get("X-functions-key"), timeout))
        return _Response()

    monkeypatch.setattr(reconcile.request, "urlopen", fake_urlopen)

    reconcile.wait_for_function_index(
        hostname="func-kmlsat-dev.example.com",
        function_name="blob_trigger",
        admin_key="master-key",
        timeout_seconds=5,
        poll_interval_seconds=1,
    )

    assert requests == [
        (
            "https://func-kmlsat-dev.example.com/admin/functions/blob_trigger",
            "master-key",
            10,
        )
    ]


def test_wait_for_function_index_retries_transient_not_found(monkeypatch) -> None:
    attempts = 0

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout: int):
        del timeout
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error.HTTPError(req.full_url, 404, "missing", hdrs=None, fp=None)
        return _Response()

    monkeypatch.setattr(reconcile.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(reconcile.time, "sleep", lambda _seconds: None)

    reconcile.wait_for_function_index(
        hostname="func-kmlsat-dev.example.com",
        function_name="blob_trigger",
        admin_key="master-key",
        timeout_seconds=5,
        poll_interval_seconds=1,
    )

    assert attempts == 2


def test_wait_for_function_index_times_out(monkeypatch) -> None:
    def fake_urlopen(req, timeout: int):
        del timeout
        raise error.HTTPError(req.full_url, 404, "missing", hdrs=None, fp=None)

    monkeypatch.setattr(reconcile.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(reconcile.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="Timed out waiting for the Functions host to index"):
        reconcile.wait_for_function_index(
            hostname="func-kmlsat-dev.example.com",
            function_name="blob_trigger",
            admin_key="master-key",
            timeout_seconds=0,
            poll_interval_seconds=1,
        )


def test_reconcile_subscription_requires_succeeded_provisioning_state(monkeypatch) -> None:
    def fake_run_az_json(args: list[str]):
        if args[:3] == ["functionapp", "keys", "list"]:
            return {"masterKey": "master", "systemKeys": {"eventgrid_extension": "eventgrid"}}
        if args[:4] == ["eventgrid", "system-topic", "event-subscription", "show"]:
            return {"properties": {"provisioningState": "Failed"}}
        raise AssertionError(args)

    monkeypatch.setattr(reconcile, "run_az_json", fake_run_az_json)
    monkeypatch.setattr(reconcile, "subscription_exists", lambda *_args: True)
    monkeypatch.setattr(reconcile, "wait_for_function_index", lambda **_kwargs: None)
    monkeypatch.setattr(reconcile.subprocess, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="provisioningState=Succeeded"):
        reconcile.reconcile_subscription(
            resource_group="rg-kmlsat-dev",
            function_app="func-kmlsat-dev",
            hostname="func-kmlsat-dev.example.com",
            system_topic_name="evgt-kmlsat-dev",
            subscription_name="evgs-kml-upload",
            function_name="blob_trigger",
        )
