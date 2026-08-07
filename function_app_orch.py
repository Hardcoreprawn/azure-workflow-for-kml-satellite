"""Azure Functions entry point for the orchestrator image (#466).

Registers only the pipeline and health blueprints — not the full public API.
Does NOT register activity functions — those run in the compute image.

Both images share the same Durable task hub and Azure Storage connection.
PIPELINE_ROLE=orchestrator is set in Dockerfile.orchestrator so
blueprints/pipeline/__init__.py skips importing the activities module.

The orchestrator deliberately omits all public-API blueprints (billing, ops,
export, etc.) to reduce attack surface and cold-start cost (#779).
"""

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


def _register_blueprints(app: func.FunctionApp) -> None:
    from function_registration import register_function_blueprints

    register_function_blueprints(app, role="orchestrator")


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

# Wire up distributed rate limiters (#252)
if STORAGE_CONNECTION_STRING:
    try:
        from treesight.constants import (
            RATE_LIMIT_DEMO_MAX,
            RATE_LIMIT_DEMO_WINDOW,
            RATE_LIMIT_FORM_MAX,
            RATE_LIMIT_FORM_WINDOW,
            RATE_LIMIT_PIPELINE_MAX,
            RATE_LIMIT_PIPELINE_WINDOW,
        )
        from treesight.security import (
            TableRateLimiter,
            set_demo_limiter,
            set_form_limiter,
            set_pipeline_limiter,
        )

        set_form_limiter(
            TableRateLimiter(
                RATE_LIMIT_FORM_MAX,
                RATE_LIMIT_FORM_WINDOW,
                "form",
                connection_string=STORAGE_CONNECTION_STRING,
            )
        )
        set_pipeline_limiter(
            TableRateLimiter(
                RATE_LIMIT_PIPELINE_MAX,
                RATE_LIMIT_PIPELINE_WINDOW,
                "pipeline",
                connection_string=STORAGE_CONNECTION_STRING,
            )
        )
        set_demo_limiter(
            TableRateLimiter(
                RATE_LIMIT_DEMO_MAX,
                RATE_LIMIT_DEMO_WINDOW,
                "demo",
                connection_string=STORAGE_CONNECTION_STRING,
            )
        )
    except Exception:
        logger.warning(
            "Could not initialise Table rate limiters; falling back to in-memory",
            exc_info=True,
        )
elif STORAGE_ACCOUNT_NAME:
    try:
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        from treesight.constants import (
            RATE_LIMIT_DEMO_MAX,
            RATE_LIMIT_DEMO_WINDOW,
            RATE_LIMIT_FORM_MAX,
            RATE_LIMIT_FORM_WINDOW,
            RATE_LIMIT_PIPELINE_MAX,
            RATE_LIMIT_PIPELINE_WINDOW,
        )
        from treesight.security import (
            TableRateLimiter,
            set_demo_limiter,
            set_form_limiter,
            set_pipeline_limiter,
        )

        table_url = f"https://{STORAGE_ACCOUNT_NAME}.table.core.windows.net"
        tsc = TableServiceClient(table_url, credential=DefaultAzureCredential())
        set_form_limiter(
            TableRateLimiter(
                RATE_LIMIT_FORM_MAX,
                RATE_LIMIT_FORM_WINDOW,
                "form",
                table_service_client=tsc,
            )
        )
        set_pipeline_limiter(
            TableRateLimiter(
                RATE_LIMIT_PIPELINE_MAX,
                RATE_LIMIT_PIPELINE_WINDOW,
                "pipeline",
                table_service_client=tsc,
            )
        )
        set_demo_limiter(
            TableRateLimiter(
                RATE_LIMIT_DEMO_MAX,
                RATE_LIMIT_DEMO_WINDOW,
                "demo",
                table_service_client=tsc,
            )
        )
    except Exception:
        logger.warning(
            "Could not initialise Table rate limiters via MI; falling back to in-memory",
            exc_info=True,
        )

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
_register_blueprints(app)
