from __future__ import annotations

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


def test_build_eventgrid_endpoint_url_encodes_key() -> None:
    endpoint = reconcile.build_eventgrid_endpoint(
        hostname="func-kmlsat-dev.example.com",
        function_name="blob_trigger",
        function_key="abc+/=123",
    )

    assert endpoint == (
        "https://func-kmlsat-dev.example.com/runtime/webhooks/eventgrid"
        "?functionName=blob_trigger&code=abc%2B%2F%3D123"
    )
