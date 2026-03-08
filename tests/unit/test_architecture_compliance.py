"""Architecture Compliance Tests.

These tests verify that critical configuration files (host.json, Dockerfile, etc.)
adhere to the architectural requirements essential for deployment success.
These act as a safety net against regression of deployment-critical settings.
"""

import json
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).parent.parent.parent


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
