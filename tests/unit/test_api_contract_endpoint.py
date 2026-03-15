"""Tests for backend API contract version endpoint and wiring."""

from __future__ import annotations

from pathlib import Path


def test_api_contract_version_constant_exists() -> None:
    function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
    content = function_app_path.read_text(encoding="utf-8")

    assert '_API_CONTRACT_VERSION = "2026-03-15.1"' in content


def test_api_contract_endpoint_registered_in_function_app() -> None:
    function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
    content = function_app_path.read_text(encoding="utf-8")

    assert '@app.function_name("api_contract")' in content
    assert 'route="api-contract"' in content
    assert 'methods=["GET"]' in content
    assert "auth_level=func.AuthLevel.ANONYMOUS" in content
