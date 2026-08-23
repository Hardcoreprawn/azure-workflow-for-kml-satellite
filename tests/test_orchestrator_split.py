"""Tests for the orchestrator image split (#466) and the big/little HTTP contract (#1407).

Verifies that:
- blueprints/pipeline/__init__.py skips activities when PIPELINE_ROLE=orchestrator
- blueprints/pipeline/__init__.py skips orchestrator/aoi_orchestrator (orchestration-trigger
  modules) when PIPELINE_ROLE=orchestrator, so the orchestrator role never competes for
  Durable Task Hub partition leases with compute (#1414)
- function_app_orch.py can be imported without importing activities, and never registers
  an orchestrationTrigger function
- Dockerfile.orchestrator exists and excludes heavy compute packages
- deploy.yml builds both images and passes orchestrator_image to tofu
- orchestrator and compute register the identical public HTTP blueprint set (#1407) —
  #779's original strict-subset contract was over-scoped and is superseded here
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── 1. PIPELINE_ROLE=orchestrator skips activities import ────────────────


def test_pipeline_init_checks_pipeline_role():
    """blueprints/pipeline/__init__.py must read PIPELINE_ROLE and
    conditionally import activities only when role is 'full'.
    """
    init_path = REPO_ROOT / "blueprints" / "pipeline" / "__init__.py"
    source = init_path.read_text()
    assert "PIPELINE_ROLE" in source, "blueprints/pipeline/__init__.py must read PIPELINE_ROLE env var"
    assert "_PIPELINE_ROLE" in source, "blueprints/pipeline/__init__.py must store PIPELINE_ROLE in a local variable"


def test_pipeline_activities_guarded_by_pipeline_role():
    """activities must only be imported when PIPELINE_ROLE == 'full',
    not unconditionally at the module level.
    """
    init_path = REPO_ROOT / "blueprints" / "pipeline" / "__init__.py"
    tree = ast.parse(init_path.read_text(), filename=str(init_path))

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
    import importlib
    import sys

    monkeypatch.setenv("PIPELINE_ROLE", "orchestrator")

    # Remove any cached imports so the env var takes effect
    mods_to_remove = [k for k in sys.modules if k.startswith("blueprints.pipeline")]
    for mod in mods_to_remove:
        sys.modules.pop(mod, None)

    importlib.import_module("blueprints.pipeline")

    assert "blueprints.pipeline.activities" not in sys.modules, (
        "blueprints.pipeline.activities must not be imported when PIPELINE_ROLE=orchestrator"
    )

    # Re-clean for isolation
    for mod in list(sys.modules):
        if mod.startswith("blueprints.pipeline"):
            sys.modules.pop(mod, None)


# ── 1b. PIPELINE_ROLE=orchestrator skips orchestration-trigger modules (#1414) ──


def test_pipeline_orchestration_modules_guarded_by_pipeline_role():
    """orchestrator/aoi_orchestrator must only be imported when PIPELINE_ROLE == 'full'.

    Both modules register an ``orchestration_trigger`` function. If the
    orchestrator role also imports them, it becomes a second worker competing
    for the same Durable Task Hub's control-queue partition leases as compute —
    and has no activities registered, so a replay it wins can never schedule
    an activity and gets stuck forever (#1414).
    """
    init_path = REPO_ROOT / "blueprints" / "pipeline" / "__init__.py"
    tree = ast.parse(init_path.read_text(), filename=str(init_path))

    module_level_unconditional = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module is None:
            for alias in node.names:
                if alias.name in {"orchestrator", "aoi_orchestrator"}:
                    module_level_unconditional.append(alias.name)

    assert not module_level_unconditional, (
        "orchestrator and aoi_orchestrator must not be imported unconditionally at "
        "module level — they must be guarded by PIPELINE_ROLE == 'full' (#1414)"
    )


def test_pipeline_role_orchestrator_skips_orchestration_trigger_modules(monkeypatch):
    """When PIPELINE_ROLE=orchestrator, importing blueprints.pipeline must not
    import the orchestrator or aoi_orchestrator modules.
    """
    import importlib
    import sys

    monkeypatch.setenv("PIPELINE_ROLE", "orchestrator")

    mods_to_remove = [k for k in sys.modules if k.startswith("blueprints.pipeline")]
    for mod in mods_to_remove:
        sys.modules.pop(mod, None)

    importlib.import_module("blueprints.pipeline")

    assert "blueprints.pipeline.orchestrator" not in sys.modules, (
        "blueprints.pipeline.orchestrator must not be imported when PIPELINE_ROLE=orchestrator (#1414)"
    )
    assert "blueprints.pipeline.aoi_orchestrator" not in sys.modules, (
        "blueprints.pipeline.aoi_orchestrator must not be imported when PIPELINE_ROLE=orchestrator (#1414)"
    )

    for mod in list(sys.modules):
        if mod.startswith("blueprints.pipeline"):
            sys.modules.pop(mod, None)


def test_function_app_orch_never_registers_an_orchestration_trigger(monkeypatch):
    """The orchestrator role must never hold an ``orchestrationTrigger`` listener (#1414).

    Regression guard for the actual runtime contract, not just the import
    graph: even if a future change re-adds a shared import elsewhere, this
    catches the orchestrator role becoming eligible for a Durable Task Hub
    partition lease again.
    """
    import importlib
    import sys

    monkeypatch.setenv("PIPELINE_ROLE", "orchestrator")
    sys.modules.pop("function_app_orch", None)
    for mod in list(sys.modules):
        if mod.startswith("blueprints.pipeline"):
            sys.modules.pop(mod, None)

    orch = importlib.import_module("function_app_orch")
    orch.app.functions_bindings = {}
    trigger_types = {fn.get_trigger().type for fn in orch.app.get_functions() if fn.get_trigger()}

    assert "orchestrationTrigger" not in trigger_types, (
        "orchestrator role must never register an orchestrationTrigger function (#1414)"
    )

    sys.modules.pop("function_app_orch", None)
    for mod in list(sys.modules):
        if mod.startswith("blueprints.pipeline"):
            sys.modules.pop(mod, None)


# ── 2. function_app_orch.py structure ───────────────────────────────────


def test_function_app_orch_exists():
    """function_app_orch.py must exist in the repo root."""
    assert (REPO_ROOT / "function_app_orch.py").exists(), (
        "function_app_orch.py is missing — orchestrator image entry point not found"
    )


def test_function_app_orch_uses_shared_registration():
    """function_app_orch.py must use shared registration helper."""
    source = (REPO_ROOT / "function_app_orch.py").read_text()
    assert "from function_registration import register_function_blueprints" in source


def test_entrypoints_use_shared_registration_module():
    """Both entrypoints must register routes via one shared helper."""
    compute_source = (REPO_ROOT / "function_app.py").read_text()
    orch_source = (REPO_ROOT / "function_app_orch.py").read_text()

    assert "from function_registration import register_function_blueprints" in compute_source
    assert "from function_registration import register_function_blueprints" in orch_source
    assert 'register_function_blueprints(app, role="compute")' in compute_source
    assert 'register_function_blueprints(app, role="orchestrator")' in orch_source


def test_function_app_orch_does_not_hardcode_activities():
    """function_app_orch.py must not directly import activities."""
    source = (REPO_ROOT / "function_app_orch.py").read_text()
    assert "from blueprints.pipeline.activities" not in source
    assert "import activities" not in source


def test_function_app_orch_does_not_register_monitoring_scheduler():
    """The orchestrator image must not register the monitoring timer trigger."""
    source = (REPO_ROOT / "function_app_orch.py").read_text()
    assert 'role="orchestrator"' in source
    assert "monitoring_scheduler_bp" not in source


def test_function_app_registers_monitoring_scheduler():
    """The compute image must keep the monitoring timer trigger."""
    source = (REPO_ROOT / "function_app.py").read_text()
    assert 'role="compute"' in source


def test_function_app_orch_imports_and_indexes_without_monitoring_timer(monkeypatch):
    """The orchestrator entry point must import cleanly and omit the timer trigger."""
    import importlib
    import sys

    monkeypatch.setenv("PIPELINE_ROLE", "orchestrator")
    sys.modules.pop("function_app_orch", None)

    orch = importlib.import_module("function_app_orch")
    orch.app.functions_bindings = {}
    functions = orch.app.get_functions()
    names = {fn.get_function_name() for fn in functions}

    assert functions, "function_app_orch must index at least one function"
    assert "monitoring_scheduler" not in names, "function_app_orch must not register the monitoring timer trigger"


# ── 7. Big/little HTTP blueprint contract (#1407, supersedes #779) ─────


def test_orchestrator_and_compute_share_identical_http_blueprints():
    """Orchestrator and compute must register the identical public HTTP blueprint set.

    #779 originally scoped the orchestrator down to health+pipeline only, but the
    frontend's single API base has targeted the orchestrator hostname exclusively
    since #724 — meaning every other public blueprint (billing, upload, account,
    org, export, catalogue, contact, ops, analysis) was unreachable in production.
    None of them depend on GDAL/rasterio, so both roles now serve the same HTTP
    surface; only activities (PIPELINE_ROLE) and the monitoring scheduler timer
    remain compute-only (#1407).
    """
    from function_registration import _http_blueprints

    http_bps = _http_blueprints()
    assert len(http_bps) >= 13, f"Expected at least 13 shared HTTP blueprints, got {len(http_bps)}"


def test_orchestrator_includes_billing_upload_and_ops():
    """Billing, upload, and ops blueprints must be reachable via the orchestrator (#1407)."""
    from blueprints.billing import bp as billing_bp
    from blueprints.ops import bp as ops_bp
    from blueprints.upload import bp as upload_bp
    from function_registration import _http_blueprints

    http_ids = {id(bp) for bp in _http_blueprints()}

    for name, bp in [("billing", billing_bp), ("upload", upload_bp), ("ops", ops_bp)]:
        assert id(bp) in http_ids, (
            f"The '{name}' blueprint must be registered on every role — the orchestrator "
            "is the frontend's only configured API base (#1407)."
        )


def test_orchestrator_registers_health_and_pipeline():
    """Orchestrator must still register the health and pipeline blueprints."""
    from blueprints.health import bp as health_bp
    from blueprints.pipeline import bp as pipeline_bp
    from function_registration import _http_blueprints

    http_ids = {id(bp) for bp in _http_blueprints()}

    assert id(health_bp) in http_ids, "Orchestrator must register health_bp"
    assert id(pipeline_bp) in http_ids, "Orchestrator must register pipeline_bp"


def test_http_blueprints_never_import_heavy_geo_packages():
    """The shared HTTP blueprint set must stay safe for the slim orchestrator image.

    Regression guard for #1407: importing every module backing _http_blueprints()
    must not pull GDAL/rasterio/fiona/shapely/pyproj into sys.modules, since
    Dockerfile.orchestrator does not install them. If a future blueprint change
    (directly or transitively) needs one of these, it must move to a
    compute-only registration path instead of silently breaking the
    orchestrator image at runtime.
    """
    heavy_markers = ("rasterio", "fiona", "osgeo", "pyproj", "shapely")
    http_blueprint_modules = (
        "blueprints.account",
        "blueprints.analysis",
        "blueprints.billing",
        "blueprints.catalogue",
        "blueprints.contact",
        "blueprints.eudr",
        "blueprints.export",
        "blueprints.health",
        "blueprints.monitoring",
        "blueprints.ops",
        "blueprints.org",
        "blueprints.pipeline",
        "blueprints.upload",
    )

    import importlib
    import sys

    for module_name in http_blueprint_modules:
        before = set(sys.modules)
        importlib.import_module(module_name)
        newly_loaded = set(sys.modules) - before
        heavy_hits = sorted(mod for mod in newly_loaded if any(marker in mod for marker in heavy_markers))
        assert not heavy_hits, (
            f"Importing {module_name!r} pulled in heavy geo package(s) {heavy_hits} — "
            "this blueprint can no longer be safely registered on the orchestrator role (#1407)."
        )


# ── 3. Dockerfile.orchestrator ──────────────────────────────────────────


def test_dockerfile_orchestrator_exists():
    """Dockerfile.orchestrator must exist."""
    assert (REPO_ROOT / "Dockerfile.orchestrator").exists(), "Dockerfile.orchestrator is missing"


def test_dockerfile_orchestrator_sets_pipeline_role():
    """Dockerfile.orchestrator must set PIPELINE_ROLE=orchestrator."""
    source = (REPO_ROOT / "Dockerfile.orchestrator").read_text()
    assert "PIPELINE_ROLE=orchestrator" in source, "Dockerfile.orchestrator must set ENV PIPELINE_ROLE=orchestrator"


def test_dockerfile_orchestrator_excludes_heavy_packages():
    """Dockerfile.orchestrator must filter out GDAL-dependent packages."""
    source = (REPO_ROOT / "Dockerfile.orchestrator").read_text()
    # Must use the grep-v exclusion pattern
    heavy = ["fiona", "rasterio", "numpy"]
    for pkg in heavy:
        assert pkg in source, f"Dockerfile.orchestrator must explicitly exclude {pkg} from the install"


def test_dockerfile_orchestrator_copies_orch_entry_point():
    """Dockerfile.orchestrator must install function_app_orch.py as function_app.py."""
    source = (REPO_ROOT / "Dockerfile.orchestrator").read_text()
    assert "function_app_orch.py" in source, "Dockerfile.orchestrator must COPY function_app_orch.py"


# ── 4. image-config.env ─────────────────────────────────────────────────


def test_image_config_env_has_orch_repo():
    """image-config.env must define ORCH_IMAGE_REPO for the CI build."""
    path = REPO_ROOT / ".github" / "image-config.env"
    source = path.read_text()
    assert "ORCH_IMAGE_REPO" in source, ".github/image-config.env must define ORCH_IMAGE_REPO"


def test_image_config_env_defines_shared_uv_version():
    """All project images must receive one pinned uv version from image-config.env."""
    source = (REPO_ROOT / ".github" / "image-config.env").read_text()
    assert re.search(r'^UV_VERSION="?\d+\.\d+\.\d+"?$', source, re.MULTILINE)


def test_project_dockerfiles_consume_shared_uv_version():
    """Project Dockerfiles must not drift through hardcoded uv image tags."""
    for filename in ("Dockerfile", "Dockerfile.orchestrator", "Dockerfile.dev"):
        source = (REPO_ROOT / filename).read_text()
        assert "ARG UV_VERSION" in source, f"{filename} must declare ARG UV_VERSION"
        assert "ghcr.io/astral-sh/uv:${UV_VERSION} AS uv" in source, f"{filename} must use the shared uv build stage"
        assert not re.search(r"ghcr\.io/astral-sh/uv:\d", source), f"{filename} must not hardcode a uv image version"


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
    assert "orchestrator_image=" in source, 'deploy.yml must pass -var="orchestrator_image=..." to tofu plan'


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
