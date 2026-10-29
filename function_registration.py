"""Shared function-app registration for compute and orchestrator entrypoints."""

from __future__ import annotations

import os
from typing import Any, Literal

# Existing deployment role names are retained; "full" means worker, not a combined app.
PipelineRole = Literal["compute", "orchestrator"]


def _http_blueprints() -> tuple[Any, ...]:
    """Load admission-owned HTTP blueprints and Event Grid ingress.

    Verified GDAL/rasterio/fiona/shapely/pyproj-free at both static (AST) and
    runtime (sys.modules) import-time for #1407 — safe on the slim
    orchestrator image, which already installs every non-geo dependency
    these need (Dockerfile.orchestrator only excludes fiona/rasterio/numpy/
    shapely/pyproj/pystac-client/planetary-computer).
    """
    from blueprints.account import bp as account_bp
    from blueprints.analysis import bp as analysis_bp
    from blueprints.billing import bp as billing_bp
    from blueprints.catalogue import bp as catalogue_bp
    from blueprints.contact import bp as contact_bp
    from blueprints.eudr import bp as eudr_bp
    from blueprints.export import bp as export_bp
    from blueprints.health import bp as health_bp
    from blueprints.health import probes_bp
    from blueprints.monitoring import bp as monitoring_bp
    from blueprints.ops import bp as ops_bp
    from blueprints.org import bp as org_bp
    from blueprints.pipeline import bp as pipeline_bp
    from blueprints.upload import bp as upload_bp

    return (
        health_bp,
        probes_bp,
        billing_bp,
        contact_bp,
        eudr_bp,
        analysis_bp,
        catalogue_bp,
        export_bp,
        org_bp,
        account_bp,
        upload_bp,
        monitoring_bp,
        ops_bp,
        pipeline_bp,
    )


def _monitoring_scheduler_blueprint() -> Any:
    """Load the compute-only monitoring scheduler blueprint lazily.

    Timer-triggered; its handler calls treesight.pipeline.enrichment.run_enrichment
    (GDAL/rasterio) — must only run on the compute (activity-capable) role, and only
    once across the fleet to avoid duplicate scheduled runs.
    """
    from blueprints.monitoring import scheduler_bp as monitoring_scheduler_bp

    return monitoring_scheduler_bp


def register_function_blueprints(app: Any, *, role: PipelineRole = "compute") -> None:
    """Register only the role-owned surface; reject contradictory settings."""
    expected_roles = {"compute": "full", "orchestrator": "orchestrator"}
    if role not in expected_roles:
        raise ValueError(f"Unknown function entrypoint role: {role!r}")
    pipeline_role = os.environ.get("PIPELINE_ROLE", "full")
    if pipeline_role != expected_roles[role]:
        raise ValueError(f"Entrypoint role {role!r} contradicts PIPELINE_ROLE={pipeline_role!r}")
    if role == "compute":
        from blueprints.health import probes_bp
        from blueprints.pipeline import worker_bp

        app.register_functions(probes_bp)
        app.register_functions(worker_bp)
        app.register_functions(_monitoring_scheduler_blueprint())
        return
    for blueprint in _http_blueprints():
        app.register_functions(blueprint)
