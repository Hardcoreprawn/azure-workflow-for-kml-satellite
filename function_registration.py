"""Shared function-app registration for compute and orchestrator entrypoints."""

from __future__ import annotations

from typing import Any, Literal

# Roles that control which blueprints are registered.
# - "compute": full public API surface + monitoring scheduler (default)
# - "orchestrator": pipeline triggers and health check only (#779)
PipelineRole = Literal["compute", "orchestrator"]


def _orchestrator_blueprints() -> tuple[Any, ...]:
    """Load blueprints for the orchestrator role (pipeline + health only).

    The orchestrator image exposes only internal durable-trigger HTTP routes
    and a health check.  All public-API blueprints are omitted to reduce the
    attack surface (#779).
    """
    from blueprints.health import bp as health_bp
    from blueprints.pipeline import bp as pipeline_bp

    return (health_bp, pipeline_bp)


def _compute_blueprints() -> tuple[Any, ...]:
    """Load the full set of blueprints for the compute role."""
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
    """Load the compute-only monitoring scheduler blueprint lazily."""
    from blueprints.monitoring import scheduler_bp as monitoring_scheduler_bp

    return monitoring_scheduler_bp


def register_function_blueprints(app: Any, *, role: PipelineRole = "compute") -> None:
    """Register blueprints on the provided Function App instance.

    The ``role`` parameter determines which blueprints are registered:
    - ``compute`` (default): full blueprint set including monitoring scheduler
    - ``orchestrator``: pipeline triggers and health check only (#779)
    """
    if role == "orchestrator":
        for blueprint in _orchestrator_blueprints():
            app.register_functions(blueprint)
        return

    for blueprint in _compute_blueprints():
        app.register_functions(blueprint)
    app.register_functions(_monitoring_scheduler_blueprint())
