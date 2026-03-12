"""Architecture Compliance Tests.

These tests verify that critical configuration files (host.json, Dockerfile, etc.)
adhere to the architectural requirements essential for deployment success.
These act as a safety net against regression of deployment-critical settings.
"""

import json
import re
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).parent.parent.parent

# Source files that must use WorkflowState instead of bare string literals
_ORCHESTRATION_SOURCES = [
    WORKSPACE_ROOT / "kml_satellite" / "orchestrators" / "phases.py",
    WORKSPACE_ROOT / "kml_satellite" / "orchestrators" / "polling.py",
    WORKSPACE_ROOT / "kml_satellite" / "orchestrators" / "kml_pipeline.py",
    WORKSPACE_ROOT / "kml_satellite" / "orchestrators" / "error_helpers.py",
]

# State strings that must not appear as bare literals in orchestration modules
_BARE_STATE_LITERALS = re.compile(
    r"""[=!]= *['"](?:ready|failed|error|completed|success|pending|processing|cancelled|unknown)['"]"""
    r"""|['"](?:ready|failed|error|completed|success|pending|processing|cancelled|unknown)['"] *[=!]=""",
    re.IGNORECASE,
)


def test_host_json_has_extension_bundle():
    """Verify host.json includes the extension bundle configuration.

    Without this, the Azure Functions host cannot load bindings (Event Grid, Durable Task),
    causing silent failures and 404s on triggers.
    """
    host_json_path = WORKSPACE_ROOT / "host.json"
    assert host_json_path.exists(), "host.json missing"

    with host_json_path.open(encoding="utf-8") as f:
        config = json.load(f)

    # 1. Verify Extension Bundle (Critical for bindings)
    assert "extensionBundle" in config, "host.json missing 'extensionBundle'"
    bundle = config["extensionBundle"]
    assert bundle.get("id") == "Microsoft.Azure.Functions.ExtensionBundle"
    assert bundle.get("version") == "[4.*, 5.0.0)"

    # 2. Verify Durable Task extension config
    assert "extensions" in config
    assert "durableTask" in config["extensions"]
    durable = config["extensions"]["durableTask"]
    assert durable.get("hubName") == "KmlSatelliteHub"
    assert durable["storageProvider"]["type"] == "AzureStorage"


def test_dockerfile_uses_correct_base_image():
    """Verify Dockerfile uses the correct Azure Functions Python base image.

    The base image must align with the Python version defined in pyproject.toml
    and verify the multi-stage build structure.
    """
    dockerfile_path = WORKSPACE_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile missing"

    with dockerfile_path.open(encoding="utf-8") as f:
        content = f.read()

    # Verify Base Image (Python 3.12) default remains explicit.
    assert "mcr.microsoft.com/azure-functions/python:4-python3.12" in content, (
        "Dockerfile must default to Python 3.12 Azure Functions base image"
    )

    # Verify Multi-Stage Build with configurable base image args.
    assert "AS builder" in content
    assert "ARG BUILDER_BASE_IMAGE=" in content
    assert "ARG RUNTIME_BASE_IMAGE=" in content
    assert "FROM ${BUILDER_BASE_IMAGE} AS builder" in content
    assert "FROM ${RUNTIME_BASE_IMAGE}" in content


def test_dockerfile_runtime_stage_remains_slim():
    """Guard against runtime package bloat regressions in the final image.

    Runtime stage should not install heavyweight geospatial build/runtime tools
    that are only needed in the builder stage.
    """

    dockerfile_path = WORKSPACE_ROOT / "Dockerfile"
    content = dockerfile_path.read_text(encoding="utf-8")

    runtime_stage = content.split("FROM ${RUNTIME_BASE_IMAGE}", maxsplit=1)[1]

    runtime_packages: list[str] = []
    capture = False
    for line in runtime_stage.splitlines():
        stripped = line.strip()
        if stripped.startswith("RUN apt-get update && apt-get install -y --no-install-recommends"):
            capture = True
            continue
        if capture and "&& rm -rf /var/lib/apt/lists/*" in stripped:
            capture = False
            continue
        if capture:
            package = stripped.removesuffix("\\").strip()
            if package:
                runtime_packages.append(package)

    assert runtime_packages, "Runtime stage must include explicit apt install block"
    installed_runtime_packages = "\n".join(runtime_packages)

    assert "gdal-bin" not in installed_runtime_packages, "Runtime stage must not install gdal-bin"
    assert "build-essential" not in installed_runtime_packages, (
        "Runtime stage must not install build-essential"
    )
    assert "cmake" not in installed_runtime_packages, "Runtime stage must not install cmake"


def test_dockerfile_builder_stage_does_not_install_redundant_gdal_bin():
    """Builder stage should use libgdal-dev without redundant gdal-bin install."""

    dockerfile_path = WORKSPACE_ROOT / "Dockerfile"
    content = dockerfile_path.read_text(encoding="utf-8")

    builder_stage = content.split("FROM ${BUILDER_BASE_IMAGE} AS builder", maxsplit=1)[1]
    builder_stage = builder_stage.split("FROM ${RUNTIME_BASE_IMAGE}", maxsplit=1)[0]

    builder_packages: list[str] = []
    capture = False
    for line in builder_stage.splitlines():
        stripped = line.strip()
        if stripped.startswith("RUN apt-get update && apt-get install -y --no-install-recommends"):
            capture = True
            continue
        if capture and "&& rm -rf /var/lib/apt/lists/*" in stripped:
            capture = False
            continue
        if capture:
            package = stripped.removesuffix("\\").strip()
            if package:
                builder_packages.append(package)

    assert builder_packages, "Builder stage must include explicit apt install block"
    installed_builder_packages = "\n".join(builder_packages)
    assert "libgdal-dev" in installed_builder_packages
    assert "gdal-bin" not in installed_builder_packages, (
        "Builder stage should avoid redundant gdal-bin install to reduce build footprint"
    )


def test_requirements_include_critical_libs():
    """Verify requirements.txt includes essential Azure Functions libraries."""
    req_path = WORKSPACE_ROOT / "requirements.txt"
    assert req_path.exists()

    with req_path.open(encoding="utf-8") as f:
        reqs = f.read()

    assert "azure-functions" in reqs
    assert "azure-functions-durable" in reqs
    assert "azure-storage-blob" in reqs


def test_orchestration_uses_workflow_state_not_bare_literals():
    """Guard: orchestration modules must compare states via WorkflowState, not bare strings.

    Bare literal comparisons like ``== "ready"`` or ``!= "failed"`` are fragile
    and led to the bug where 'error'-state downloads were passed to post-processing.
    All orchestration state comparisons must use WorkflowState enum values.
    """
    violations: list[str] = []
    for source_path in _ORCHESTRATION_SOURCES:
        assert source_path.exists(), f"Expected orchestration source missing: {source_path}"
        lines = source_path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Skip comment lines and docstrings
            if (
                stripped.startswith("#")
                or stripped.startswith('"""')
                or stripped.startswith("'''")
            ):
                continue
            if _BARE_STATE_LITERALS.search(line):
                violations.append(f"{source_path.name}:{lineno}: {stripped}")

    assert not violations, (
        "Bare state string comparisons found in orchestration modules — "
        "use WorkflowState enum instead:\n" + "\n".join(violations)
    )


def test_workflow_state_module_importable():
    """WorkflowState must be importable from its canonical location."""
    from kml_satellite.core.states import WorkflowState  # noqa: F401


def test_protocols_module_importable():
    """Protocol definitions must be importable from their canonical location."""
    from kml_satellite.core.protocols import (  # noqa: F401
        PlanetaryComputerModule,
        RasterDataset,
        RasterioModule,
    )
