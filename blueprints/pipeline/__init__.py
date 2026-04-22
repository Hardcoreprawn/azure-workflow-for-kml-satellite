"""Durable Functions pipeline blueprint (§3, §4.2).

NOTE: Do NOT add ``from __future__ import annotations`` to this module
or any submodule.  The Azure Functions v2 runtime inspects binding
parameter annotations at import time.  PEP 563 (stringified annotations)
causes the runtime to fail with ``FunctionLoadError``.

The Blueprint instance is created here and imported by each submodule
so all routes, triggers, and activities register on a single blueprint.

``PIPELINE_ROLE`` environment variable controls which submodules are loaded:
  - ``full`` (default): all submodules — compute image registers activities
  - ``orchestrator``: skips ``activities`` — orchestrator image, no GDAL/rasterio
"""

import os

import azure.durable_functions as df

bp = df.Blueprint()

_PIPELINE_ROLE = os.environ.get("PIPELINE_ROLE", "full")

# Import submodules to trigger decorator registration on ``bp``.
# Order does not matter — each module imports ``bp`` from this package.
from . import (  # noqa: E402  — must follow bp = df.Blueprint()
    annotations,  # noqa: F401  — registers notes + override endpoints
    aoi_orchestrator,  # noqa: F401  — registers per-AOI sub-orchestrator (#585)
    blob_trigger,  # noqa: F401  — registers blob trigger
    diagnostics,  # noqa: F401  — registers diagnostic endpoints
    enrichment,  # noqa: F401  — registers enrichment HTTP endpoints
    orchestrator,  # noqa: F401  — registers orchestrator
    submission,  # noqa: F401  — registers submission endpoint
)

if _PIPELINE_ROLE == "full":
    from . import activities  # noqa: F401  — registers activity triggers (compute only)
