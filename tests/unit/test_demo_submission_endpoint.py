"""Tests for demo submission endpoint wiring and payload validation (#199)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from function_app import _validate_demo_submission_payload, demo_submission


def test_validate_demo_submission_payload_accepts_valid_payload() -> None:
    payload = {
        "email": "demo@example.com",
        "kml": "<kml><Document></Document></kml>",
    }

    normalized, err = _validate_demo_submission_payload(payload)

    assert err is None
    assert normalized is not None
    assert normalized["email"] == "demo@example.com"
    assert normalized["kml"] == "<kml><Document></Document></kml>"


def test_validate_demo_submission_payload_requires_email_and_kml() -> None:
    payload = {
        "email": "",
        "kml": "",
    }

    normalized, err = _validate_demo_submission_payload(payload)

    assert normalized is None
    assert err == "Field 'email' is required"


def test_validate_demo_submission_payload_rejects_invalid_email() -> None:
    payload = {
        "email": "not-an-email",
        "kml": "<kml />",
    }

    normalized, err = _validate_demo_submission_payload(payload)

    assert normalized is None
    assert err == "Field 'email' must be a valid email address"


def test_validate_demo_submission_payload_requires_kml() -> None:
    payload = {
        "email": "demo@example.com",
        "kml": "",
    }

    normalized, err = _validate_demo_submission_payload(payload)

    assert normalized is None
    assert err == "Field 'kml' is required"


def test_demo_submit_endpoint_registered_in_function_app() -> None:
    function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
    content = function_app_path.read_text(encoding="utf-8")

    assert '@app.function_name("demo_submission")' in content
    assert 'route="demo-submit"' in content
    assert 'methods=["POST", "OPTIONS"]' in content
    assert "auth_level=func.AuthLevel.ANONYMOUS" in content


def test_demo_submission_accepts_and_persists_payload(monkeypatch) -> None:
    blob_service = MagicMock()
    container_client = MagicMock()
    blob_client = MagicMock()
    blob_service.get_container_client.return_value = container_client
    blob_service.get_blob_client.return_value = blob_client

    monkeypatch.setattr("function_app.get_blob_service_client", lambda: blob_service)

    req = SimpleNamespace(
        method="POST",
        headers={"x-forwarded-for": "198.51.100.10", "user-agent": "pytest"},
        get_json=lambda: {"email": "demo@example.com", "kml": "<kml />"},
    )

    response = asyncio.run(demo_submission(req))

    assert response.status_code == 202
    body = json.loads(response.get_body().decode("utf-8"))
    assert body["status"] == "accepted"
    assert body["submission_id"]

    blob_service.get_container_client.assert_called_once()
    container_client.create_container.assert_called_once()
    blob_service.get_blob_client.assert_called_once()
    blob_client.upload_blob.assert_called_once()

    uploaded_payload = json.loads(blob_client.upload_blob.call_args.args[0])
    assert uploaded_payload["email"] == "demo@example.com"
    assert uploaded_payload["kml"] == "<kml />"
    assert uploaded_payload["status"] == "pending"
    assert uploaded_payload["source_ip"] == "198.51.100.10"


def test_demo_submission_returns_500_when_persistence_fails(monkeypatch) -> None:
    blob_service = MagicMock()
    container_client = MagicMock()
    blob_client = MagicMock()
    blob_client.upload_blob.side_effect = RuntimeError("storage unavailable")
    blob_service.get_container_client.return_value = container_client
    blob_service.get_blob_client.return_value = blob_client

    monkeypatch.setattr("function_app.get_blob_service_client", lambda: blob_service)

    req = SimpleNamespace(
        method="POST",
        headers={},
        get_json=lambda: {"email": "demo@example.com", "kml": "<kml />"},
    )

    response = asyncio.run(demo_submission(req))

    assert response.status_code == 500
    body = json.loads(response.get_body().decode("utf-8"))
    assert body["error"] == "Failed to capture demo request. Please try again."
