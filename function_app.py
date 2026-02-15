"""Azure Functions entry point — KML Satellite Imagery Pipeline.

This module registers all Azure Functions (triggers, orchestrators, activities)
using the Python v2 programming model.

All business logic lives in the kml_satellite package. This file is purely
the wiring layer between Azure Functions bindings and application code.
"""

import azure.functions as func

app = func.FunctionApp()


# ---------------------------------------------------------------------------
# Trigger: Blob Created → Start Orchestration
# ---------------------------------------------------------------------------
# TODO (Issue #3): Register Event Grid / Blob trigger that starts the
# Durable Functions orchestrator when a .kml file is uploaded to kml-input.


# ---------------------------------------------------------------------------
# Orchestrator: KML Processing Pipeline
# ---------------------------------------------------------------------------
# TODO (Issue #3): Register the Durable Functions orchestrator that
# coordinates parse → fan-out → acquire imagery → post-process → fan-in.


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------
# TODO (Issue #4): parse_kml activity
# TODO (Issue #5): parse_kml_multi activity
# TODO (Issue #6): prepare_aoi activity
# TODO (Issue #7): write_metadata activity
# TODO (Issue #8-#12): imagery acquisition activities
