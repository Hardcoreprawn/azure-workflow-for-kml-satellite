"""Enrichment sub-package — weather, NDVI, mosaic registration, and analysis.

Re-exports public API for backward compatibility so that
``from treesight.pipeline.enrichment import run_enrichment`` still works.
"""

from treesight.pipeline.enrichment.aoi_metrics import (
    compute_aoi_metrics,
    compute_multi_aoi_summary,
    compute_ndvi_trend,
)
from treesight.pipeline.enrichment.change_detection import (
    compute_change_map,
    detect_changes,
)
from treesight.pipeline.enrichment.fire import fetch_fire_hotspots
from treesight.pipeline.enrichment.flood import fetch_flood_events
from treesight.pipeline.enrichment.frames import build_frame_plan
from treesight.pipeline.enrichment.mosaic import register_mosaic
from treesight.pipeline.enrichment.ndvi import compute_ndvi, fetch_ndvi_stat
from treesight.pipeline.enrichment.runner import (
    enrich_data_sources,
    enrich_finalize,
    enrich_imagery,
    enrich_single_aoi_step,
    run_enrichment,
)
from treesight.pipeline.enrichment.weather import (
    aggregate_weather_monthly,
    fetch_weather,
)

__all__ = [
    "aggregate_weather_monthly",
    "build_frame_plan",
    "compute_aoi_metrics",
    "compute_change_map",
    "compute_multi_aoi_summary",
    "compute_ndvi",
    "compute_ndvi_trend",
    "detect_changes",
    "enrich_data_sources",
    "enrich_finalize",
    "enrich_imagery",
    "enrich_single_aoi_step",
    "fetch_fire_hotspots",
    "fetch_flood_events",
    "fetch_ndvi_stat",
    "fetch_weather",
    "register_mosaic",
    "run_enrichment",
]
