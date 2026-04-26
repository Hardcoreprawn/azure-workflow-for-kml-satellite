"""Azure Functions entry point — registers all blueprints."""

import logging

import azure.functions as func

from treesight.config import (
    APPINSIGHTS_CONNECTION_STRING,
    STORAGE_ACCOUNT_NAME,
    STORAGE_CONNECTION_STRING,
    validate_config,
)
from treesight.function_registration import register_function_blueprints
from treesight.log import configure_logging

if APPINSIGHTS_CONNECTION_STRING:
    configure_logging()

logger = logging.getLogger(__name__)

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
register_function_blueprints(app, include_monitoring_scheduler=True)
