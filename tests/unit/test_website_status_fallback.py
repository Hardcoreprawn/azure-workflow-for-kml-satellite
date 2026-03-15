"""Regression guardrails for website backend status wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def website_app_source() -> str:
    path = WORKSPACE_ROOT / "website" / "static" / "app.js"
    assert path.exists(), f"website app missing at {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def website_index_source() -> str:
    path = WORKSPACE_ROOT / "website" / "index.html"
    assert path.exists(), f"website index missing at {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def website_deploy_workflow() -> dict[str, Any]:
    path = WORKSPACE_ROOT / ".github" / "workflows" / "deploy-website-swapp.yml"
    assert path.exists(), f"deploy-website-swapp.yml missing at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _get_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return workflow.get("jobs", {}).get("deploy", {}).get("steps", [])


def _find_step(steps: list[dict[str, Any]], name_fragment: str) -> dict[str, Any] | None:
    fragment = name_fragment.lower()
    return next((step for step in steps if fragment in step.get("name", "").lower()), None)


def test_website_app_uses_backend_fallback_for_status_contact_and_demo(
    website_app_source: str,
) -> None:
    assert "const REQUIRED_API_CONTRACT_VERSION = '2026-03-15.1';" in website_app_source
    assert "const API_CONTRACT_ENDPOINT = '/api/api-contract';" in website_app_source
    assert (
        "const API_CONTRACT_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${API_CONTRACT_ENDPOINT}`;"
        in website_app_source
    )
    assert "async function enforceApiContractCompatibility()" in website_app_source
    assert "const DEPLOYMENT_FALLBACK_ORIGIN = '__FUNCTION_APP_ORIGIN__';" in website_app_source
    assert (
        "const READINESS_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${API_ENDPOINT}`;"
        in website_app_source
    )
    assert (
        "const CONTACT_FORM_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${CONTACT_FORM_ENDPOINT}`;"
        in website_app_source
    )
    assert "const DEMO_SUBMIT_ENDPOINT = '/api/demo-submit';" in website_app_source
    assert (
        "const DEMO_SUBMIT_FALLBACK_ENDPOINT = `${FALLBACK_API_ORIGIN}${DEMO_SUBMIT_ENDPOINT}`;"
        in website_app_source
    )
    assert (
        "for (const endpoint of [API_ENDPOINT, READINESS_FALLBACK_ENDPOINT])" in website_app_source
    )
    assert "Expected JSON but received" in website_app_source
    assert "const note = document.getElementById('demo-message');" in website_app_source
    assert "const demoEmailInput = document.getElementById('demo-email');" in website_app_source
    assert "function initDemoTimelapse()" in website_app_source
    assert "timelapseState.frames = generateTimelapseFrames(24);" in website_app_source


def test_website_index_cache_busts_app_script(website_index_source: str) -> None:
    assert 'src="static/app.js?v=__WEBSITE_BUILD_VERSION__"' in website_index_source
    assert 'id="demo-message"' in website_index_source
    assert 'id="demo-email"' in website_index_source
    assert 'id="timelapse-map"' in website_index_source
    assert 'id="timelapse-slider"' in website_index_source


def test_website_deploy_workflow_injects_function_origin(
    website_deploy_workflow: dict[str, Any],
) -> None:
    steps = _get_steps(website_deploy_workflow)

    hostname_step = _find_step(steps, "get function app hostname")
    assert hostname_step is not None, "Website deploy workflow must resolve Function App hostname"
    assert "az functionapp show" in str(hostname_step.get("run", ""))

    config_step = _find_step(steps, "configure website backend fallback origin")
    assert config_step is not None, "Website deploy workflow must inject backend fallback origin"

    run_script = str(config_step.get("run", ""))
    assert 'FUNCTION_APP_ORIGIN="https://${{ steps.function-app.outputs.hostname }}"' in run_script
    assert 'WEBSITE_BUILD_VERSION="${GITHUB_SHA::7}"' in run_script
    assert "__FUNCTION_APP_ORIGIN__" in run_script
    assert "__WEBSITE_BUILD_VERSION__" in run_script
    assert "website/static/app.js" in run_script
    assert "website/index.html" in run_script

    api_contract_step = _find_step(steps, "verify backend api contract compatibility")
    assert api_contract_step is not None, (
        "Website deploy workflow must verify backend API contract"
    )

    contract_script = str(api_contract_step.get("run", ""))
    assert "REQUIRED_API_CONTRACT_VERSION" in contract_script
    assert "/api/api-contract" in contract_script
    assert "website/static/app.js" in contract_script


def test_infra_allows_static_web_app_preview_origins() -> None:
    path = WORKSPACE_ROOT / "infra" / "tofu" / "main.tf"
    content = path.read_text(encoding="utf-8")

    assert '"https://*.azurestaticapps.net"' in content, (
        "Function App CORS must allow Static Web Apps preview subdomains"
    )
