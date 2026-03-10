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
    r"""== *['"](?:ready|failed|error|completed|success|pending|processing)['"]"""
    r"""|['"](?:ready|failed|error|completed|success|pending|processing)['"] *==""",
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

    # Verify Base Image (Python 3.12)
    assert "mcr.microsoft.com/azure-functions/python:4-python3.12" in content, (
        "Dockerfile must use Python 3.12 Azure Functions base image"
    )

    # Verify Multi-Stage Build
    assert "AS builder" in content
    assert "FROM mcr.microsoft.com/azure-functions/python:4-python3.12" in content


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
