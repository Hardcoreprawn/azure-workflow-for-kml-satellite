"""Shared function-app registration for compute and orchestrator entrypoints."""

from __future__ import annotations

from typing import Any

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
from blueprints.monitoring import scheduler_bp as monitoring_scheduler_bp
from blueprints.ops import bp as ops_bp
from blueprints.org import bp as org_bp
from blueprints.pipeline import bp as pipeline_bp
from blueprints.upload import bp as upload_bp


def register_function_blueprints(
    app: Any,
    *,
    include_monitoring_scheduler: bool,
) -> None:
    """Register all shared blueprints on the provided Function App instance."""
    # Register HTTP blueprints
    app.register_functions(health_bp)
    app.register_functions(auth_bp)
    app.register_functions(billing_bp)
    app.register_functions(contact_bp)
    app.register_functions(demo_bp)
    app.register_functions(eudr_bp)
    app.register_functions(analysis_bp)
    app.register_functions(catalogue_bp)
    app.register_functions(export_bp)

    # Register org management endpoints
    app.register_functions(org_bp)

    # Register upload/history BFF endpoints
    app.register_functions(upload_bp)

    # Register monitoring endpoints; scheduler remains compute-only.
    app.register_functions(monitoring_bp)
    if include_monitoring_scheduler:
        app.register_functions(monitoring_scheduler_bp)

    # Register ops dashboard (operator visibility)
    app.register_functions(ops_bp)

    # Register durable pipeline blueprint
    app.register_functions(pipeline_bp)
