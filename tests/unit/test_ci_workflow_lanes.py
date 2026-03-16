"""Contracts for split CI lanes (Issue #150)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.exists(), f"CI workflow missing at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def _step_names(job: dict[str, Any]) -> list[str]:
    return [str(s.get("name", "")) for s in _steps(job)]


def test_ci_has_fast_and_native_jobs(ci_workflow: dict[str, Any]) -> None:
    jobs = ci_workflow.get("jobs", {})
    assert "fast-lint-type-unit" in jobs
    assert "native-geo-validation" in jobs


def test_fast_job_avoids_runner_apt_install(ci_workflow: dict[str, Any]) -> None:
    job = ci_workflow.get("jobs", {}).get("fast-lint-type-unit", {})
    scripts = "\n".join(str(s.get("run", "")) for s in _steps(job))
    assert "apt-get install" not in scripts


def test_fast_job_runs_lint_type_and_unit(ci_workflow: dict[str, Any]) -> None:
    job = ci_workflow.get("jobs", {}).get("fast-lint-type-unit", {})
    names = "\n".join(_step_names(job)).lower()
    scripts = "\n".join(str(s.get("run", "")) for s in _steps(job))

    assert "ruff" in names
    assert "pyright" in names
    assert "unit tests" in names
    assert "uv run pytest" in scripts
    assert "tests/unit/test_health_endpoints.py" in scripts


def test_native_job_installs_geospatial_system_deps(ci_workflow: dict[str, Any]) -> None:
    job = ci_workflow.get("jobs", {}).get("native-geo-validation", {})
    scripts = "\n".join(str(s.get("run", "")) for s in _steps(job))
    assert "apt-get install" in scripts
    assert "libgdal-dev" in scripts
    assert "libgeos-dev" in scripts
    assert "libproj-dev" in scripts


def test_native_job_runs_geospatial_validation(ci_workflow: dict[str, Any]) -> None:
    job = ci_workflow.get("jobs", {}).get("native-geo-validation", {})
    names = "\n".join(_step_names(job))
    scripts = "\n".join(str(s.get("run", "")) for s in _steps(job))
    assert "Run unit tests (geospatial lane)" in names
    assert "import rasterio, fiona, pyproj, shapely" in scripts
    assert 'uv run pytest tests/unit -v --tb=short -m "not integration and not e2e"' in scripts


def test_prs_have_a_hard_format_gate_with_explicit_step(ci_workflow: dict[str, Any]) -> None:
    job = ci_workflow.get("jobs", {}).get("fast-lint-type-unit", {})
    format_step = next(
        (step for step in _steps(job) if "format" in str(step.get("name", "")).lower()),
        None,
    )

    assert format_step is not None, "Fast CI job must include an explicit format gate step"
    assert "pull_request" in str(format_step.get("if", "")), (
        "Formatting gate must run on PRs to block auto-fixable drift before merge"
    )
    assert "uv run ruff format --check ." in str(format_step.get("run", ""))


def test_pr_format_failures_publish_autofix_patch(ci_workflow: dict[str, Any]) -> None:
    job = ci_workflow.get("jobs", {}).get("fast-lint-type-unit", {})
    steps = _steps(job)

    patch_step = next(
        (
            step
            for step in steps
            if "patch" in str(step.get("name", "")).lower()
            or "autofix" in str(step.get("name", "")).lower()
        ),
        None,
    )
    assert patch_step is not None, "CI must generate an autofix patch when formatting fails"
    assert "uv run ruff format ." in str(patch_step.get("run", ""))
    assert "ruff-format.patch" in str(patch_step.get("run", ""))

    upload_step = next(
        (
            step
            for step in steps
            if "upload" in str(step.get("name", "")).lower()
            and "patch" in str(step.get("name", "")).lower()
        ),
        None,
    )
    assert upload_step is not None, "CI must upload the formatting patch as an artifact"
    assert "actions/upload-artifact" in str(upload_step.get("uses", ""))
    assert "ruff-format.patch" in str(upload_step.get("with", {}).get("path", ""))


def test_pr_format_failure_message_includes_local_fix_command(
    ci_workflow: dict[str, Any],
) -> None:
    job = ci_workflow.get("jobs", {}).get("fast-lint-type-unit", {})
    steps = _steps(job)

    fail_step = next(
        (
            step
            for step in steps
            if "fail" in str(step.get("name", "")).lower()
            and "format" in str(step.get("name", "")).lower()
        ),
        None,
    )
    assert fail_step is not None, "CI must fail with a contributor-facing formatting message"
    fail_script = str(fail_step.get("run", ""))
    assert "uv run ruff format ." in fail_script
    assert "GITHUB_STEP_SUMMARY" in fail_script or "::error::" in fail_script


def test_readme_documents_local_format_command() -> None:
    readme_path = Path(__file__).resolve().parent.parent.parent / "README.md"
    content = readme_path.read_text(encoding="utf-8")
    assert "uv run ruff format ." in content, (
        "README must document the local formatting command contributors should run before PRs"
    )
