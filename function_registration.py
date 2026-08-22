"""Shared function-app registration for compute and orchestrator entrypoints."""

from __future__ import annotations

from typing import Any, Literal

# Roles that control which blueprints are registered.
# - "compute": full HTTP surface + activity functions (PIPELINE_ROLE=full) + monitoring scheduler timer
# - "orchestrator": full HTTP surface (identical to compute), no activities, no scheduler (#1407)
#
# Both roles serve the same public HTTP blueprints ("little" tier, big/little split) —
# none of them import GDAL/rasterio/fiona/shapely/pyproj at load time, so they run fine on
# the slim orchestrator image (Dockerfile.orchestrator). Only Durable activity execution
# (GDAL-heavy, gated by PIPELINE_ROLE inside blueprints/pipeline/__init__.py) and the
# monitoring scheduler timer (which calls treesight.pipeline.enrichment.run_enrichment,
# also GDAL-heavy, and must run exactly once across the fleet) are compute-only ("big" tier).
PipelineRole = Literal["compute", "orchestrator"]


def _http_blueprints() -> tuple[Any, ...]:
    """Load the public HTTP blueprint set shared by every Function App role.

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
    from blueprints.monitoring import bp as monitoring_bp
    from blueprints.ops import bp as ops_bp
    from blueprints.org import bp as org_bp
    from blueprints.pipeline import bp as pipeline_bp
    from blueprints.upload import bp as upload_bp

    return (
        health_bp,
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
    """Register blueprints on the provided Function App instance.

    Both roles register the identical public HTTP blueprint set (#1407) —
    the ``role`` parameter only controls the compute-only extra:
    - ``compute`` (default): HTTP blueprints + monitoring scheduler timer.
      Also runs Durable activity functions via ``PIPELINE_ROLE=full``.
    - ``orchestrator``: HTTP blueprints only. No activities
      (``PIPELINE_ROLE=orchestrator``), no scheduler.
    """
    for blueprint in _http_blueprints():
        app.register_functions(blueprint)
    if role == "compute":
        app.register_functions(_monitoring_scheduler_blueprint())
