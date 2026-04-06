"""Azure Functions entry point — registers all blueprints."""

import logging

import azure.functions as func

from treesight.config import (
    APPINSIGHTS_CONNECTION_STRING,
    STORAGE_ACCOUNT_NAME,
    STORAGE_CONNECTION_STRING,
    validate_config,
)
from treesight.log import configure_logging

if APPINSIGHTS_CONNECTION_STRING:
    configure_logging()

logger = logging.getLogger(__name__)

from blueprints.analysis import bp as analysis_bp
from blueprints.billing import bp as billing_bp
from blueprints.catalogue import bp as catalogue_bp
from blueprints.contact import bp as contact_bp
from blueprints.demo import bp as demo_bp
from blueprints.eudr import bp as eudr_bp
from blueprints.export import bp as export_bp
from blueprints.health import bp as health_bp
from blueprints.monitoring import bp as monitoring_bp
from blueprints.pipeline import bp as pipeline_bp

# Fail-fast config validation (§8.6)
validate_config()

# Wire up distributed replay store for valet tokens (M1.8)
if STORAGE_CONNECTION_STRING:
    try:
        from treesight.security import TableReplayStore, set_replay_store

        set_replay_store(TableReplayStore(STORAGE_CONNECTION_STRING))
    except Exception:
        logger.warning(
            "Could not initialise Table replay store; falling back to in-memory",
            exc_info=True,
        )
elif STORAGE_ACCOUNT_NAME:
    try:
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        from treesight.security import TableReplayStore, set_replay_store

        table_url = f"https://{STORAGE_ACCOUNT_NAME}.table.core.windows.net"
        table_service_client = TableServiceClient(table_url, credential=DefaultAzureCredential())
        set_replay_store(TableReplayStore(table_service_client=table_service_client))
    except Exception:
        logger.warning(
            "Could not initialise Table replay store via MI; falling back to in-memory",
            exc_info=True,
        )

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Register HTTP blueprints
app.register_functions(health_bp)
app.register_functions(billing_bp)
app.register_functions(contact_bp)
app.register_functions(demo_bp)
app.register_functions(eudr_bp)
app.register_functions(analysis_bp)
app.register_functions(catalogue_bp)
app.register_functions(export_bp)

# Register monitoring blueprint (Timer Trigger + HTTP)
app.register_functions(monitoring_bp)

# Register durable pipeline blueprint
app.register_functions(pipeline_bp)
