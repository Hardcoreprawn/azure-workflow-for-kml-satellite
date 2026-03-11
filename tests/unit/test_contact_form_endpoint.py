"""Tests for marketing contact form endpoint wiring and payload validation (#154)."""

from __future__ import annotations

from pathlib import Path

from function_app import _validate_marketing_interest_payload


def test_validate_marketing_interest_payload_accepts_valid_payload() -> None:
    payload = {
        "email": "hello@example.com",
        "organization": "TreeSight Labs",
        "use_case": "Track orchard health over seasons",
        "aoi_size": "500",
    }

    normalized, err = _validate_marketing_interest_payload(payload)

    assert err is None
    assert normalized is not None
    assert normalized["email"] == "hello@example.com"
    assert normalized["organization"] == "TreeSight Labs"
    assert normalized["use_case"] == "Track orchard health over seasons"


def test_validate_marketing_interest_payload_requires_required_fields() -> None:
    payload = {
        "email": "",
        "organization": "",
        "use_case": "",
    }

    normalized, err = _validate_marketing_interest_payload(payload)

    assert normalized is None
    assert err is not None


def test_validate_marketing_interest_payload_rejects_invalid_email() -> None:
    payload = {
        "email": "not-an-email",
        "organization": "TreeSight Labs",
        "use_case": "Track orchard health",
    }

    normalized, err = _validate_marketing_interest_payload(payload)

    assert normalized is None
    assert err == "Field 'email' must be a valid email address"


def test_contact_form_endpoint_registered_in_function_app() -> None:
    function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
    content = function_app_path.read_text(encoding="utf-8")

    assert '@app.function_name("marketing_interest")' in content
    assert 'route="contact-form"' in content
    assert 'methods=["POST", "OPTIONS"]' in content
    assert "auth_level=func.AuthLevel.ANONYMOUS" in content
