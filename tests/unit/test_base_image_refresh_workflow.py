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


def test_workflow_permissions_follow_least_privilege(workflow: dict[str, Any]) -> None:
    permissions = workflow.get("permissions", {})
    assert permissions == {"contents": "read", "packages": "write"}


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


class TestTrivyDiagnosticsAndPolicy:
    """Contracts for issue #206 actionable Trivy outputs and exception policy."""

    def test_workflow_generates_structured_trivy_reports(self, workflow: dict[str, Any]) -> None:
        steps = _steps(workflow)

        scan = _step_with_name_fragment(steps, "vulnerability scan")
        assert scan is not None, "Primary Trivy scan step missing"
        scan_with = scan.get("with", {})
        assert scan_with.get("format") == "json", (
            "Primary Trivy scan must emit JSON so failures are actionable"
        )
        assert "trivy-results.json" in str(scan_with.get("output", ""))
        assert str(scan_with.get("exit-code", "")) == "0", (
            "Report generation step must not fail before summary/artifact publication"
        )

        sarif = _step_with_name_fragment(steps, "sarif")
        assert sarif is not None, "Workflow must also generate a SARIF report"
        sarif_with = sarif.get("with", {})
        assert sarif_with.get("format") == "sarif"
        assert "trivy-results.sarif" in str(sarif_with.get("output", ""))

    def test_workflow_uploads_trivy_artifacts_even_on_failure(
        self, workflow: dict[str, Any]
    ) -> None:
        steps = _steps(workflow)

        upload = _step_with_name_fragment(steps, "upload trivy")
        assert upload is not None, "Workflow must upload Trivy findings as an artifact"
        assert "actions/upload-artifact" in str(upload.get("uses", ""))
        assert upload.get("if") == "always()", (
            "Trivy reports must upload even when the vulnerability gate fails"
        )

        upload_with = upload.get("with", {})
        assert "trivy" in str(upload_with.get("name", "")).lower()
        artifact_path = str(upload_with.get("path", ""))
        assert "trivy-results.json" in artifact_path
        assert "trivy-results.sarif" in artifact_path

    def test_workflow_publishes_blocker_summary_from_json(self, workflow: dict[str, Any]) -> None:
        steps = _steps(workflow)

        summary = _step_with_name_fragment(steps, "summary")
        assert summary is not None, "Workflow must publish a Trivy blocker summary"
        run_script = str(summary.get("run", ""))
        assert "GITHUB_STEP_SUMMARY" in run_script
        assert "VulnerabilityID" in run_script
        assert "PkgName" in run_script
        assert "InstalledVersion" in run_script
        assert "FixedVersion" in run_script
        assert "Severity" in run_script
        assert "blocking" in run_script.lower(), (
            "Summary must include blocker counts for before/after comparison"
        )

    def test_workflow_validates_allowlist_metadata_and_renders_trivy_ignorefile(
        self, workflow: dict[str, Any]
    ) -> None:
        steps = _steps(workflow)

        validate = _step_with_name_fragment(steps, "allowlist")
        assert validate is not None, "Workflow must validate allowlist metadata"
        run_script = str(validate.get("run", ""))
        assert "owner" in run_script.lower(), "Allowlist validation must require owner"
        assert "expires_on" in run_script, "Allowlist validation must require expiry metadata"
        assert "expired_at" in run_script, "Workflow must render Trivy-compatible expiry field"
        assert "statement" in run_script, "Workflow must preserve exception rationale"

    def test_workflow_enforces_gate_from_structured_report(self, workflow: dict[str, Any]) -> None:
        steps = _steps(workflow)

        gate = _step_with_name_fragment(steps, "gate")
        assert gate is not None, "Workflow must enforce the vulnerability gate explicitly"
        run_script = str(gate.get("run", ""))
        assert "trivy-results.json" in run_script
        assert "HIGH" in run_script and "CRITICAL" in run_script
        assert "exit 1" in run_script, "Gate step must fail the job when blockers remain"


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
    assert "org.opencontainers.image.source" not in content
