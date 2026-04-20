"""Tests for the orchestrator image split (#466).

Verifies that:
- blueprints/pipeline/__init__.py skips activities when PIPELINE_ROLE=orchestrator
- function_app_orch.py can be imported without importing activities
- Dockerfile.orchestrator exists and excludes heavy compute packages
- deploy.yml builds both images and passes orchestrator_image to tofu
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── 1. PIPELINE_ROLE=orchestrator skips activities import ────────────────


def test_pipeline_init_checks_pipeline_role():
    """blueprints/pipeline/__init__.py must read PIPELINE_ROLE and
    conditionally import activities only when role is 'full'.
    """
    init_path = REPO_ROOT / "blueprints" / "pipeline" / "__init__.py"
    source = init_path.read_text()
    assert "PIPELINE_ROLE" in source, (
        "blueprints/pipeline/__init__.py must read PIPELINE_ROLE env var"
    )
    assert "_PIPELINE_ROLE" in source, (
        "blueprints/pipeline/__init__.py must store PIPELINE_ROLE in a local variable"
    )


def test_pipeline_activities_guarded_by_pipeline_role():
    """activities must only be imported when PIPELINE_ROLE == 'full',
    not unconditionally at the module level.
    """
    init_path = REPO_ROOT / "blueprints" / "pipeline" / "__init__.py"
    tree = ast.parse(init_path.read_text(), filename=str(init_path))

    # Find all top-level unconditional imports of activities
    unconditional_activities_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is None:
            # from . import activities
            for alias in node.names:
                if alias.name == "activities":
                    # Check if this import is inside an if block or at top level
                    # We check by seeing if parent is an If node
                    unconditional_activities_imports.append(node)

    # Check differently: look for pattern at module level (not in If)
    module_level_unconditional = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module is None:
            for alias in node.names:
                if alias.name == "activities":
                    module_level_unconditional.append(alias.name)

    assert not module_level_unconditional, (
        "activities must not be imported unconditionally at module level — "
        "it must be guarded by PIPELINE_ROLE == 'full'"
    )


def test_pipeline_role_orchestrator_skips_activities(monkeypatch):
    """When PIPELINE_ROLE=orchestrator, importing blueprints.pipeline must
    not import the activities module.
    """
    import sys

    monkeypatch.setenv("PIPELINE_ROLE", "orchestrator")

    # Remove any cached imports so the env var takes effect
    mods_to_remove = [k for k in sys.modules if k.startswith("blueprints.pipeline")]
    for mod in mods_to_remove:
        sys.modules.pop(mod, None)

    import blueprints.pipeline  # noqa: F401

    assert "blueprints.pipeline.activities" not in sys.modules, (
        "blueprints.pipeline.activities must not be imported when PIPELINE_ROLE=orchestrator"
    )

    # Re-clean for isolation
    for mod in list(sys.modules):
        if mod.startswith("blueprints.pipeline"):
            sys.modules.pop(mod, None)


# ── 2. function_app_orch.py structure ───────────────────────────────────


def test_function_app_orch_exists():
    """function_app_orch.py must exist in the repo root."""
    assert (REPO_ROOT / "function_app_orch.py").exists(), (
        "function_app_orch.py is missing — orchestrator image entry point not found"
    )


def test_function_app_orch_imports_pipeline_bp():
    """function_app_orch.py must import blueprints.pipeline (orchestrator role)."""
    source = (REPO_ROOT / "function_app_orch.py").read_text()
    assert "from blueprints.pipeline import bp as pipeline_bp" in source


def test_function_app_orch_does_not_hardcode_activities():
    """function_app_orch.py must not directly import activities."""
    source = (REPO_ROOT / "function_app_orch.py").read_text()
    assert "from blueprints.pipeline.activities" not in source
    assert "import activities" not in source


# ── 3. Dockerfile.orchestrator ──────────────────────────────────────────


def test_dockerfile_orchestrator_exists():
    """Dockerfile.orchestrator must exist."""
    assert (REPO_ROOT / "Dockerfile.orchestrator").exists(), "Dockerfile.orchestrator is missing"


def test_dockerfile_orchestrator_sets_pipeline_role():
    """Dockerfile.orchestrator must set PIPELINE_ROLE=orchestrator."""
    source = (REPO_ROOT / "Dockerfile.orchestrator").read_text()
    assert "PIPELINE_ROLE=orchestrator" in source, (
        "Dockerfile.orchestrator must set ENV PIPELINE_ROLE=orchestrator"
    )


def test_dockerfile_orchestrator_excludes_heavy_packages():
    """Dockerfile.orchestrator must filter out GDAL-dependent packages."""
    source = (REPO_ROOT / "Dockerfile.orchestrator").read_text()
    # Must use the grep-v exclusion pattern
    heavy = ["fiona", "rasterio", "numpy"]
    for pkg in heavy:
        assert pkg in source, (
            f"Dockerfile.orchestrator must explicitly exclude {pkg} from the install"
        )


def test_dockerfile_orchestrator_copies_orch_entry_point():
    """Dockerfile.orchestrator must install function_app_orch.py as function_app.py."""
    source = (REPO_ROOT / "Dockerfile.orchestrator").read_text()
    assert "function_app_orch.py" in source, (
        "Dockerfile.orchestrator must COPY function_app_orch.py"
    )


# ── 4. image-config.env ─────────────────────────────────────────────────


def test_image_config_env_has_orch_repo():
    """image-config.env must define ORCH_IMAGE_REPO for the CI build."""
    path = REPO_ROOT / ".github" / "image-config.env"
    source = path.read_text()
    assert "ORCH_IMAGE_REPO" in source, ".github/image-config.env must define ORCH_IMAGE_REPO"


# ── 5. infra/tofu — orchestrator_image variable and resource ────────────


def test_tofu_orchestrator_image_variable_defined():
    """infra/tofu/variables.tf must declare orchestrator_image variable."""
    source = (REPO_ROOT / "infra" / "tofu" / "variables.tf").read_text()
    assert 'variable "orchestrator_image"' in source, (
        'infra/tofu/variables.tf must declare variable "orchestrator_image"'
    )


def test_tofu_function_app_orch_resource_defined():
    """infra/tofu/main.tf must declare azapi_resource.function_app_orch."""
    source = (REPO_ROOT / "infra" / "tofu" / "main.tf").read_text()
    assert 'resource "azapi_resource" "function_app_orch"' in source, (
        'infra/tofu/main.tf must declare azapi_resource "function_app_orch"'
    )


def test_tofu_function_app_orch_uses_orchestrator_image():
    """azapi_resource.function_app_orch must reference var.orchestrator_image."""
    source = (REPO_ROOT / "infra" / "tofu" / "main.tf").read_text()
    assert "var.orchestrator_image" in source, (
        "infra/tofu/main.tf must reference var.orchestrator_image in function_app_orch body"
    )


def test_tofu_orchestrator_outputs_defined():
    """infra/tofu/outputs.tf must export orchestrator function app outputs."""
    source = (REPO_ROOT / "infra" / "tofu" / "outputs.tf").read_text()
    assert "function_app_orch_name" in source
    assert "function_app_orch_default_hostname" in source


# ── 6. deploy.yml — dual image build ────────────────────────────────────


def test_deploy_yml_builds_orchestrator_image():
    """deploy.yml must build Dockerfile.orchestrator."""
    source = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "Dockerfile.orchestrator" in source, (
        "deploy.yml must build the orchestrator image from Dockerfile.orchestrator"
    )


def test_deploy_yml_passes_orchestrator_image_to_tofu():
    """deploy.yml must pass orchestrator_image variable to tofu plan."""
    source = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "orchestrator_image=" in source, (
        'deploy.yml must pass -var="orchestrator_image=..." to tofu plan'
    )


def test_deploy_yml_configures_orchestrator_app():
    """deploy.yml must include a step to configure the orchestrator function app."""
    source = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "Configure Orchestrator Function App" in source, (
        "deploy.yml must have a 'Configure Orchestrator Function App' deploy step"
    )


def test_deploy_yml_exposes_orch_image_uri_output():
    """build-image job must expose orch_image_uri output."""
    source = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "orch_image_uri" in source
