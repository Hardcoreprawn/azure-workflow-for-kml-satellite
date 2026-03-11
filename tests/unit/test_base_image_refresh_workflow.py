"""Contracts for issue #151 base image refresh automation workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = WORKSPACE_ROOT / ".github" / "workflows" / "base-image-refresh.yml"
BASE_DOCKERFILE_PATH = WORKSPACE_ROOT / "Dockerfile.base"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.exists(), f"Workflow missing at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    return wf.get("jobs", {}).get("refresh-base-image", {}).get("steps", [])


def _step_with_name_fragment(
    steps: list[dict[str, Any]], name_fragment: str
) -> dict[str, Any] | None:
    lowered_fragment = name_fragment.lower()
    return next(
        (step for step in steps if lowered_fragment in step.get("name", "").lower()),
        None,
    )


def test_workflow_has_schedule_and_manual_dispatch(workflow: dict[str, Any]) -> None:
    # PyYAML can parse bare `on` as bool True in YAML 1.1
    on_block = workflow.get("on") or workflow.get(True, {})
    assert "schedule" in on_block
    assert "workflow_dispatch" in on_block


def test_workflow_builds_local_candidate_before_publish(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    build = _step_with_name_fragment(steps, "build base image candidate")
    assert build is not None
    assert "docker/build-push-action" in build.get("uses", "")
    assert build.get("with", {}).get("push") is False
    assert build.get("with", {}).get("load") is True
    assert build.get("with", {}).get("file") == "./Dockerfile.base"


def test_workflow_publishes_only_after_validation(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    step_names = [step.get("name", "") for step in steps]

    assert step_names.index("Run geospatial import smoke check") < step_names.index(
        "Publish validated base image"
    )
    assert step_names.index("Vulnerability scan (Trivy)") < step_names.index(
        "Publish validated base image"
    )

    publish = _step_with_name_fragment(steps, "publish validated base image")
    assert publish is not None
    assert 'docker push "${{ steps.image.outputs.name }}"' in str(publish.get("run", ""))


def test_workflow_runs_geospatial_import_smoke_check(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    smoke = _step_with_name_fragment(steps, "smoke")
    assert smoke is not None
    run_script = str(smoke.get("run", ""))
    assert "import rasterio, fiona, pyproj, shapely" in run_script


def test_workflow_scans_vulnerabilities(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    scan = _step_with_name_fragment(steps, "vulnerability")
    assert scan is not None
    uses = str(scan.get("uses", "")).lower()
    assert "trivy" in uses or "grype" in uses


def test_workflow_uses_immutable_run_scoped_tag(workflow: dict[str, Any]) -> None:
    steps = _steps(workflow)
    image_step = _step_with_name_fragment(steps, "set image name")
    assert image_step is not None

    script = str(image_step.get("run", ""))
    assert re.search(
        r"geo-base-\$\{GITHUB_SHA\}-\$\{GITHUB_RUN_ID\}-\$\{GITHUB_RUN_ATTEMPT\}",
        script,
    )


def test_base_image_workflow_uses_dedicated_dockerfile() -> None:
    assert BASE_DOCKERFILE_PATH.exists(), (
        f"Dedicated base Dockerfile missing: {BASE_DOCKERFILE_PATH}"
    )

    content = BASE_DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE=" in content
    assert "FROM ${BASE_IMAGE}" in content
    assert "import rasterio, fiona, pyproj, shapely, lxml" in content
