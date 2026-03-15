"""Tests for demo submission endpoint wiring and payload validation (#199)."""

from __future__ import annotations

from pathlib import Path

from function_app import _validate_demo_submission_payload


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
