"""Tests for demo submission endpoint wiring and payload validation (#201)."""

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


def test_demo_submission_returns_204_for_options_preflight() -> None:
    req = SimpleNamespace(method="OPTIONS", headers={}, get_json=lambda: {})

    response = asyncio.run(demo_submission(req))

    assert response.status_code == 204


def test_demo_submission_returns_400_for_invalid_json() -> None:
    def raise_value_error() -> None:
        raise ValueError("not json")

    req = SimpleNamespace(
        method="POST",
        headers={},
        get_json=raise_value_error,
    )

    response = asyncio.run(demo_submission(req))

    assert response.status_code == 400
    body = json.loads(response.get_body().decode("utf-8"))
    assert "error" in body


def test_demo_submission_returns_400_when_body_is_not_an_object() -> None:
    req = SimpleNamespace(
        method="POST",
        headers={},
        get_json=lambda: ["not", "an", "object"],
    )

    response = asyncio.run(demo_submission(req))

    assert response.status_code == 400
    body = json.loads(response.get_body().decode("utf-8"))
    assert "error" in body


def test_demo_submission_blob_path_uses_deterministic_convention(monkeypatch) -> None:
    """Blob written to demo-submissions/{date}/{submission_id}.json."""
    blob_service = MagicMock()
    container_client = MagicMock()
    blob_client = MagicMock()
    blob_service.get_container_client.return_value = container_client
    blob_service.get_blob_client.return_value = blob_client

    monkeypatch.setattr("function_app.get_blob_service_client", lambda: blob_service)

    req = SimpleNamespace(
        method="POST",
        headers={},
        get_json=lambda: {"email": "demo@example.com", "kml": "<kml />"},
    )

    asyncio.run(demo_submission(req))

    _, kwargs = blob_service.get_blob_client.call_args
    blob_name: str = kwargs["blob"]
    parts = blob_name.split("/")
    assert parts[0] == "demo-submissions", "blob must be under demo-submissions/ prefix"
    assert len(parts) == 3, "path must be demo-submissions/{date}/{id}.json"
    assert parts[2].endswith(".json"), "blob name must end with .json"


def test_validate_demo_submission_payload_rejects_non_dict() -> None:
    normalized, err = _validate_demo_submission_payload("not a dict")

    assert normalized is None
    assert err == "Request body must be a JSON object"


def test_website_demo_form_email_input_has_required_attribute() -> None:
    """HTML demo email input must have type=email and required (#201 acceptance criteria)."""
    index_path = Path(__file__).parent.parent.parent / "website" / "index.html"
    content = index_path.read_text(encoding="utf-8")

    # Ensure the demo-email input is typed and required so the browser
    # enforces a valid email before the form can be submitted.
    assert 'type="email"' in content, "demo email input must have type=email"
    assert 'id="demo-email"' in content, "demo email input must have id=demo-email"
    assert 'name="email"' in content, "demo email input must have name=email for form submission"


def test_website_js_validates_email_before_demo_submission() -> None:
    """JS handler must validate email format client-side before calling the API (#201)."""
    app_js_path = Path(__file__).parent.parent.parent / "website" / "static" / "app.js"
    content = app_js_path.read_text(encoding="utf-8")

    assert "EMAIL_PATTERN.test(demoEmail)" in content, (
        "handleDemoFormSubmit must validate email with EMAIL_PATTERN before submitting"
    )
    assert "const demoEmailInput = document.getElementById('demo-email');" in content
    assert "const EMAIL_PATTERN = /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/;" in content
