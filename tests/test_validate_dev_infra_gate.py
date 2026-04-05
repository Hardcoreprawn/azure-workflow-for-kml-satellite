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
