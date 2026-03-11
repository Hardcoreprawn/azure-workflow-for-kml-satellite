"""Contracts for issue #151 base image refresh automation workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".github"
    / "workflows"
    / "base-image-refresh.yml"
)


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.exists(), f"Workflow missing at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    return wf.get("jobs", {}).get("refresh-base-image", {}).get("steps", [])


def test_workflow_has_schedule_and_manual_dispatch(workflow: dict[str, Any]) -> None:
    # PyYAML can parse bare `on` as bool True in YAML 1.1
    on_block = workflow.get("on") or workflow.get(True, {})
    assert "schedule" in on_block
    assert "workflow_dispatch" in on_block


def test_workflow_builds_and_pushes_base_image(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    build = next((s for s in steps if "build and push" in s.get("name", "").lower()), None)
    assert build is not None
    assert "docker/build-push-action" in build.get("uses", "")
    assert build.get("with", {}).get("push") is True


def test_workflow_runs_geospatial_import_smoke_check(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    smoke = next((s for s in steps if "smoke" in s.get("name", "").lower()), None)
    assert smoke is not None
    run_script = str(smoke.get("run", ""))
    assert "import rasterio, fiona, pyproj, shapely" in run_script


def test_workflow_scans_vulnerabilities(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    scan = next((s for s in steps if "vulnerability" in s.get("name", "").lower()), None)
    assert scan is not None
    uses = str(scan.get("uses", "")).lower()
    assert "trivy" in uses or "grype" in uses
