"""Contracts for issue #152 base image strategy adoption.

This suite enforces:
1. A documented strategy decision (ADR-style note)
2. Dockerfile support for explicit base image selection
3. Deploy workflow passing base image build arguments
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


def test_strategy_adr_exists_and_documents_pinning() -> None:
    adr_path = WORKSPACE_ROOT / "docs" / "adr" / "0001-geospatial-base-image-strategy.md"
    assert adr_path.exists(), f"Missing ADR: {adr_path}"

    content = adr_path.read_text(encoding="utf-8").lower()
    assert "issue #152" in content
    assert "selected strategy" in content
    assert "provenance" in content
    assert "pin" in content or "digest" in content
    assert "option" in content, "ADR should record evaluated options"
    assert "benchmark" in content, "ADR should capture benchmark evidence"
    assert "reduced" in content or "%" in content, "ADR should record measured improvement"


@pytest.fixture(scope="module")
def dockerfile_content() -> str:
    dockerfile = WORKSPACE_ROOT / "Dockerfile"
    assert dockerfile.exists(), "Dockerfile missing"
    return dockerfile.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deploy_workflow() -> dict[str, Any]:
    workflow = WORKSPACE_ROOT / ".github" / "workflows" / "deploy.yml"
    assert workflow.exists(), "deploy.yml missing"
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))


def test_dockerfile_uses_configurable_base_image_args(dockerfile_content: str) -> None:
    assert "ARG BUILDER_BASE_IMAGE=" in dockerfile_content
    assert "ARG RUNTIME_BASE_IMAGE=" in dockerfile_content
    assert "FROM ${BUILDER_BASE_IMAGE} AS builder" in dockerfile_content
    assert "FROM ${RUNTIME_BASE_IMAGE}" in dockerfile_content


def test_deploy_workflow_sets_base_image_build_args(deploy_workflow: dict[str, Any]) -> None:
    steps = deploy_workflow.get("jobs", {}).get("deploy-dev", {}).get("steps", [])
    build_step = next(
        (s for s in steps if "build and push" in s.get("name", "").lower()),
        None,
    )

    assert build_step is not None, "Build step not found in deploy workflow"
    build_args = str(build_step.get("with", {}).get("build-args", ""))

    assert "BUILDER_BASE_IMAGE=" in build_args
    assert "RUNTIME_BASE_IMAGE=" in build_args
