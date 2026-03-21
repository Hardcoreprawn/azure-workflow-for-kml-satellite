"""Enrichment sub-package — weather, NDVI, mosaic registration, and analysis.

Re-exports public API for backward compatibility so that
``from treesight.pipeline.enrichment import run_enrichment`` still works.
"""

from treesight.pipeline.enrichment.change_detection import (
    compute_change_map,
    detect_changes,
)
from treesight.pipeline.enrichment.frames import build_frame_plan
from treesight.pipeline.enrichment.mosaic import register_mosaic
from treesight.pipeline.enrichment.ndvi import compute_ndvi, fetch_ndvi_stat
from treesight.pipeline.enrichment.runner import run_enrichment
from treesight.pipeline.enrichment.weather import (
    aggregate_weather_monthly,
    fetch_weather,
)

__all__ = [
    "aggregate_weather_monthly",
    "build_frame_plan",
    "compute_change_map",
    "compute_ndvi",
    "detect_changes",
    "fetch_ndvi_stat",
    "fetch_weather",
    "register_mosaic",
    "run_enrichment",
]
