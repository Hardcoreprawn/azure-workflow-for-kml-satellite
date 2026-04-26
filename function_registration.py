"""Shared function-app registration for compute and orchestrator entrypoints."""

from __future__ import annotations

from typing import Any


def _shared_blueprints() -> tuple[Any, ...]:
    """Load shared blueprints lazily to avoid eager API-layer imports."""
    from blueprints.analysis import bp as analysis_bp
    from blueprints.auth import bp as auth_bp
    from blueprints.billing import bp as billing_bp
    from blueprints.catalogue import bp as catalogue_bp
    from blueprints.contact import bp as contact_bp
    from blueprints.demo import bp as demo_bp
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
        auth_bp,
        billing_bp,
        contact_bp,
        demo_bp,
        eudr_bp,
        analysis_bp,
        catalogue_bp,
        export_bp,
        org_bp,
        upload_bp,
        monitoring_bp,
        ops_bp,
        pipeline_bp,
    )


def _monitoring_scheduler_blueprint() -> Any:
    """Load the compute-only monitoring scheduler blueprint lazily."""
    from blueprints.monitoring import scheduler_bp as monitoring_scheduler_bp

    return monitoring_scheduler_bp


def register_function_blueprints(
    app: Any,
    *,
    include_monitoring_scheduler: bool,
) -> None:
    """Register all shared blueprints on the provided Function App instance."""
    for blueprint in _shared_blueprints():
        app.register_functions(blueprint)

    if include_monitoring_scheduler:
        app.register_functions(_monitoring_scheduler_blueprint())
