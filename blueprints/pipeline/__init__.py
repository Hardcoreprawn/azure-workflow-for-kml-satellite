"""Durable Functions pipeline blueprint (§3, §4.2).

NOTE: Do NOT add ``from __future__ import annotations`` to this module
or any submodule.  The Azure Functions v2 runtime inspects binding
parameter annotations at import time.  PEP 563 (stringified annotations)
causes the runtime to fail with ``FunctionLoadError``.

The Blueprint instance is created here and imported by each submodule
so all routes, triggers, and activities register on a single blueprint.

``PIPELINE_ROLE`` environment variable controls which submodules are loaded:
  - ``full`` (default): all submodules — compute image registers activities
    plus both ``orchestration_trigger`` functions (``treesight_orchestrator``,
    ``aoi_pipeline``)
  - ``orchestrator``: skips ``activities`` *and* both orchestration-trigger
    modules — orchestrator image only ever registers ``durable_client``
    bindings (start/query) and the Event Grid blob trigger, never a
    control-queue listener (#1414: two apps both holding an
    ``orchestration_trigger`` on the same shared task hub compete for
    partition leases, and the orchestrator role has no activities to
    schedule if it wins one — instances get stuck forever)
"""

import os

import azure.durable_functions as df

bp = df.Blueprint()

_PIPELINE_ROLE = os.environ.get("PIPELINE_ROLE", "full")

# Import submodules to trigger decorator registration on ``bp``.
# Order does not matter — each module imports ``bp`` from this package.
from . import (  # noqa: E402  — must follow bp = df.Blueprint()
    annotations,  # noqa: F401  — registers notes + override endpoints
    blob_trigger,  # noqa: F401  — registers blob trigger (durable_client only)
    diagnostics,  # noqa: F401  — registers diagnostic endpoints (durable_client only)
    enrichment,  # noqa: F401  — registers enrichment HTTP endpoints (durable_client only)
    submission,  # noqa: F401  — registers submission endpoint
)

if _PIPELINE_ROLE == "full":
    from . import (  # noqa: F401
        activities,  # registers activity triggers (compute only)
        aoi_orchestrator,  # registers aoi_pipeline orchestration_trigger (compute only, #1414)
        orchestrator,  # registers treesight_orchestrator orchestration_trigger (compute only, #1414)
    )
