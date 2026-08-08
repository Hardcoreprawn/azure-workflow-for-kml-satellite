"""Pipeline run telemetry — build stats documents for Cosmos DB (#400).

Every successful pipeline run writes a lightweight document to the
``pipeline_stats`` container.  The data accumulates for the Pipeline ETA
estimator (#399) and general platform analytics.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("treesight.pipeline.telemetry")


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Return the great-circle distance in km between two WGS84 points.

    Coordinates are in **[longitude, latitude]** order (project convention).
    """
    r = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _max_spread_km(centroids: list[list[float]]) -> float | None:
    """Return the maximum pairwise haversine distance (km) between centroids.

    *centroids* is a list of ``[lon, lat]`` pairs (project convention).
    Returns ``None`` when fewer than two centroids are available.
    """
    if len(centroids) < 2:
        return None
    max_dist = 0.0
    for i in range(len(centroids)):
        for j in range(i + 1, len(centroids)):
            c1, c2 = centroids[i], centroids[j]
            d = _haversine_km(c1[0], c1[1], c2[0], c2[1])
            if d > max_dist:
                max_dist = d
    return round(max_dist, 3)


def build_stats_document(
    *,
    instance_id: str,
    user_id: str,
    tier: str,
    aoi_count: int,
    aoi_area_by_name: dict[str, float],
    aoi_centroids: list[list[float]],
    image_count: int,
    batch_used: bool,
    enrichment: dict[str, Any],
    started_at: str | None = None,
    completed_at: str | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    """Build a lightweight pipeline stats document for Cosmos DB.

    Parameters
    ----------
    instance_id:
        Durable orchestration instance ID (used as document ``id``).
    user_id:
        Owning user (partition key).
    tier:
        Subscription tier (e.g. ``"free"``, ``"pro"``).
    aoi_count:
        Number of AOIs in the submission.
    aoi_area_by_name:
        Mapping of AOI name → area in hectares (from ingestion phase).
    aoi_centroids:
        List of ``[lon, lat]`` centroid pairs for spread calculation.
    image_count:
        Number of Sentinel-2 scenes fetched (``ready_count`` from acquisition).
    batch_used:
        Whether Azure Batch fallback was invoked.
    enrichment:
        Enrichment phase result dict (for ``enrichment_set`` and duration).
    started_at:
        ISO-8601 UTC timestamp when the orchestration started (optional).
    completed_at:
        ISO-8601 UTC timestamp when the run completed.  Defaults to *now*.
    status:
        ``"completed"`` or ``"partial"``; failed runs should not call this.
    """
    now = datetime.now(UTC).isoformat()
    completed_at = completed_at or now

    total_area_km2: float | None = None
    if aoi_area_by_name:
        total_ha = sum(aoi_area_by_name.values())
        total_area_km2 = round(total_ha / 100.0, 4)

    spread = _max_spread_km(aoi_centroids)

    duration_s: float | None = None
    if started_at and completed_at:
        try:
            from datetime import datetime as _dt

            t0 = _dt.fromisoformat(started_at)
            t1 = _dt.fromisoformat(completed_at)
            duration_s = round((t1 - t0).total_seconds(), 1)
        except Exception:
            logger.warning("Could not compute pipeline duration", exc_info=True)

    enrichment_set: list[str] = _extract_enrichment_set(enrichment)

    return {
        "id": instance_id,
        "user_id": user_id,
        "instance_id": instance_id,
        "timestamp": completed_at,
        "started_at": started_at,
        "status": status,
        "tier": tier,
        "aoi_count": aoi_count,
        "total_area_km2": total_area_km2,
        "max_spread_km": spread,
        "enrichment_set": enrichment_set,
        "image_count": image_count,
        "duration_s": duration_s,
        "batch_used": batch_used,
    }


def _extract_enrichment_set(enrichment: dict[str, Any]) -> list[str]:
    """Derive the list of enrichment types that ran from the enrichment result."""
    types: list[str] = []
    manifest = enrichment.get("manifest_path") or enrichment.get("manifest")
    if manifest:
        # Infer from keys present in the enrichment result dict.
        candidates = {
            "ndvi": ("ndvi",),
            "weather": ("weather",),
            "scl": ("scl",),
            "change_detection": ("change_detection",),
            "mosaic": ("mosaic",),
        }
        for label, keys in candidates.items():
            if any(enrichment.get(k) for k in keys):
                types.append(label)
        # Always record that enrichment ran if manifest is present
        if not types:
            types = ["enrichment"]
    return types
