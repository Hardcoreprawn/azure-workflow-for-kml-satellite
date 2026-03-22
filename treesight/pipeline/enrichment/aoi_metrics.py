"""Per-AOI quantitative metrics for professional users.

Computes accurate, per-polygon statistics from enrichment data:
- Geometric: area, perimeter, centroid, bbox dimensions
- Vegetation: NDVI time series, trend direction, current health
- Change: year-over-year loss/gain in hectares and percentage
- Weather: per-AOI temperature and precipitation summary

All metrics use the AOI's actual polygon boundary, not the union
bounding box — so multi-AOI KMLs get distinct, accurate results.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# NDVI health classification thresholds (Sentinel-2 L2A, 0–1 scale)
NDVI_THRESHOLDS = {
    "bare_soil": 0.1,
    "sparse": 0.2,
    "moderate": 0.4,
    "healthy": 0.6,
    "very_healthy": 0.8,
}


def classify_ndvi(mean: float) -> str:
    """Classify NDVI mean into a human-readable vegetation health label."""
    if mean < NDVI_THRESHOLDS["bare_soil"]:
        return "bare_soil"
    if mean < NDVI_THRESHOLDS["sparse"]:
        return "sparse_vegetation"
    if mean < NDVI_THRESHOLDS["moderate"]:
        return "moderate_vegetation"
    if mean < NDVI_THRESHOLDS["healthy"]:
        return "healthy_vegetation"
    if mean < NDVI_THRESHOLDS["very_healthy"]:
        return "very_healthy_vegetation"
    return "dense_vegetation"


def compute_ndvi_trend(ndvi_stats: list[dict[str, float] | None]) -> dict[str, Any]:
    """Compute NDVI trend statistics from a time series.

    Takes the enrichment frame_plan's ndvi_stat list and computes:
    - Linear trend direction and magnitude
    - Latest vs earliest comparison
    - Maximum observed drop between consecutive observations
    - Overall stability assessment
    """
    # Filter to frames with valid NDVI data
    valid = [(i, s) for i, s in enumerate(ndvi_stats) if s and s.get("mean") is not None]
    if len(valid) < 2:
        latest = valid[0][1]["mean"] if valid else None
        return {
            "direction": "insufficient_data",
            "observations": len(valid),
            "latest_mean": latest,
            "health_class": classify_ndvi(latest) if latest is not None else "unknown",
        }

    means = [s["mean"] for _, s in valid]
    n = len(means)

    # Simple linear regression: y = a + bx
    x_mean = (n - 1) / 2.0
    y_mean = sum(means) / n
    numerator = sum((i - x_mean) * (m - y_mean) for i, m in enumerate(means))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0.0

    # Classify trend
    if abs(slope) < 0.002:
        direction = "stable"
    elif slope > 0:
        direction = "improving"
    else:
        direction = "declining"

    # Consecutive drops (track original frame index, not filtered index)
    max_drop = 0.0
    max_drop_idx = -1
    for i in range(1, n):
        drop = means[i - 1] - means[i]
        if drop > max_drop:
            max_drop = drop
            max_drop_idx = valid[i][0]  # original frame index

    # Coefficient of variation (stability indicator)
    std = math.sqrt(sum((m - y_mean) ** 2 for m in means) / n) if n > 1 else 0.0
    cv = std / y_mean if y_mean > 0 else 0.0

    earliest_mean = means[0]
    latest_mean = means[-1]
    overall_change = latest_mean - earliest_mean

    return {
        "direction": direction,
        "slope_per_frame": round(slope, 5),
        "observations": n,
        "earliest_mean": round(earliest_mean, 4),
        "latest_mean": round(latest_mean, 4),
        "overall_change": round(overall_change, 4),
        "overall_change_pct": round(overall_change / earliest_mean * 100, 1)
        if earliest_mean
        else 0.0,
        "max_consecutive_drop": round(max_drop, 4),
        "max_drop_frame_index": max_drop_idx,
        "coefficient_of_variation": round(cv, 3),
        "mean_ndvi": round(y_mean, 4),
        "std_ndvi": round(std, 4),
        "health_class": classify_ndvi(latest_mean),
    }


def compute_aoi_metrics(
    aoi_data: dict[str, Any],
    ndvi_stats: list[dict[str, float] | None],
    weather_daily: dict[str, Any] | None = None,
    change_detection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute comprehensive quantitative metrics for a single AOI.

    Parameters
    ----------
    aoi_data : dict
        AOI model data (from prepare_aoi), must include:
        feature_name, area_ha, perimeter_km, centroid, bbox.
    ndvi_stats : list
        Per-frame NDVI statistics from enrichment (may contain Nones).
    weather_daily : dict or None
        Daily weather data from Open-Meteo.
    change_detection : dict or None
        Change detection results from raster comparison.

    Returns
    -------
    dict
        Complete per-AOI metrics package.
    """
    metrics: dict[str, Any] = {
        "feature_name": aoi_data.get("feature_name", "Unknown"),
        "feature_index": aoi_data.get("feature_index", 0),
    }

    # --- Geometry ---
    area_ha = aoi_data.get("area_ha", 0.0)
    perimeter_km = aoi_data.get("perimeter_km", 0.0)
    bbox = aoi_data.get("bbox", [0, 0, 0, 0])
    centroid = aoi_data.get("centroid", [0, 0])

    metrics["geometry"] = {
        "area_ha": area_ha,
        "area_km2": round(area_ha / 100, 4),
        "perimeter_km": perimeter_km,
        "compactness": _compactness_index(area_ha, perimeter_km),
        "centroid_lon": round(centroid[0], 6),
        "centroid_lat": round(centroid[1], 6),
        "bbox": bbox,
        "bbox_width_km": round(_bbox_width_km(bbox), 2),
        "bbox_height_km": round(_bbox_height_km(bbox), 2),
    }

    # --- Vegetation (NDVI) ---
    ndvi_trend = compute_ndvi_trend(ndvi_stats)
    metrics["vegetation"] = ndvi_trend

    # Latest NDVI detail
    valid_stats = [s for s in ndvi_stats if s and s.get("mean") is not None]
    if valid_stats:
        latest = valid_stats[-1]
        metrics["vegetation"]["latest_detail"] = {
            "mean": latest.get("mean"),
            "min": latest.get("min"),
            "max": latest.get("max"),
            "std": latest.get("std"),
            "median": latest.get("median"),
            "valid_pixels": latest.get("valid_pixels"),
            "cloud_cover": latest.get("cloud_cover"),
            "scene_date": latest.get("datetime", ""),
        }

    # --- Change Detection ---
    if change_detection and change_detection.get("season_changes"):
        changes = change_detection["season_changes"]
        summary = change_detection.get("summary", {})
        metrics["change"] = {
            "comparisons": len(changes),
            "total_loss_ha": round(sum(c.get("loss_ha", 0) for c in changes), 2),
            "total_gain_ha": round(sum(c.get("gain_ha", 0) for c in changes), 2),
            "net_change_ha": round(
                sum(c.get("gain_ha", 0) - c.get("loss_ha", 0) for c in changes), 2
            ),
            "trajectory": summary.get("trajectory", "unknown"),
            "worst_loss": _worst_change(changes, "loss_ha"),
            "best_gain": _worst_change(changes, "gain_ha"),
        }
    else:
        metrics["change"] = {"comparisons": 0, "trajectory": "insufficient_data"}

    # --- Weather Summary ---
    if weather_daily and weather_daily.get("temp"):
        temps = [t for t in weather_daily["temp"] if t is not None]
        precips = [p for p in weather_daily.get("precip", []) if p is not None]
        metrics["weather"] = {
            "observation_days": len(temps),
            "temp_mean_c": round(sum(temps) / len(temps), 1) if temps else None,
            "temp_min_c": round(min(temps), 1) if temps else None,
            "temp_max_c": round(max(temps), 1) if temps else None,
            "precip_total_mm": round(sum(precips), 1) if precips else None,
            "precip_days": sum(1 for p in precips if p > 0.1) if precips else 0,
        }
    else:
        metrics["weather"] = {"observation_days": 0}

    return metrics


def compute_multi_aoi_summary(
    aoi_metrics_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute aggregate summary across multiple AOIs.

    Provides portfolio-level view for multi-polygon KMLs.
    """
    n = len(aoi_metrics_list)
    if n == 0:
        return {"aoi_count": 0}

    total_area = sum(m["geometry"]["area_ha"] for m in aoi_metrics_list)
    total_perimeter = sum(m["geometry"]["perimeter_km"] for m in aoi_metrics_list)

    # Weighted mean NDVI (by area)
    ndvi_values = []
    area_weights = []
    for m in aoi_metrics_list:
        if m["vegetation"].get("latest_mean") is not None:
            ndvi_values.append(m["vegetation"]["latest_mean"])
            area_weights.append(m["geometry"]["area_ha"])

    weighted_ndvi = None
    if ndvi_values and sum(area_weights) > 0:
        weighted_ndvi = round(
            sum(n * w for n, w in zip(ndvi_values, area_weights, strict=True)) / sum(area_weights),
            4,
        )

    # Health distribution
    health_counts: dict[str, int] = {}
    for m in aoi_metrics_list:
        hc = m["vegetation"].get("health_class", "unknown")
        health_counts[hc] = health_counts.get(hc, 0) + 1

    # Trend distribution
    trend_counts: dict[str, int] = {}
    for m in aoi_metrics_list:
        td = m["vegetation"].get("direction", "unknown")
        trend_counts[td] = trend_counts.get(td, 0) + 1

    # Total change
    total_loss = sum(m["change"].get("total_loss_ha", 0) for m in aoi_metrics_list)
    total_gain = sum(m["change"].get("total_gain_ha", 0) for m in aoi_metrics_list)

    return {
        "aoi_count": n,
        "total_area_ha": round(total_area, 4),
        "total_perimeter_km": round(total_perimeter, 4),
        "weighted_mean_ndvi": weighted_ndvi,
        "health_distribution": health_counts,
        "trend_distribution": trend_counts,
        "total_loss_ha": round(total_loss, 2),
        "total_gain_ha": round(total_gain, 2),
        "net_change_ha": round(total_gain - total_loss, 2),
    }


# ── Private helpers ────────────────────────────────────────────


def _compactness_index(area_ha: float, perimeter_km: float) -> float:
    """Polsby-Popper compactness: 4π·area / perimeter². Returns 0–1 (1 = circle)."""
    if perimeter_km <= 0 or area_ha <= 0:
        return 0.0
    area_km2 = area_ha / 100
    perimeter2 = perimeter_km**2
    return round(4 * math.pi * area_km2 / perimeter2, 3)


def _bbox_width_km(bbox: list[float]) -> float:
    """Approximate east-west extent of bbox in kilometres."""
    if len(bbox) < 4:
        return 0.0
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    deg_to_km = 111.32 * math.cos(math.radians(mid_lat))
    return abs(max_lon - min_lon) * deg_to_km


def _bbox_height_km(bbox: list[float]) -> float:
    """Approximate north-south extent of bbox in kilometres."""
    if len(bbox) < 4:
        return 0.0
    return abs(bbox[3] - bbox[1]) * 111.32


def _worst_change(changes: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    """Find the season-change entry with the largest value for a given key."""
    if not changes:
        return None
    worst = max(changes, key=lambda c: c.get(key, 0))
    val = worst.get(key, 0)
    if val <= 0:
        return None
    season = worst.get("season", "")
    # Support both legacy (year_a/year_b) and current (year_from/year_to) keys.
    year_start = worst.get("year_from") or worst.get("year_a") or ""
    year_end = worst.get("year_to") or worst.get("year_b") or ""
    return {
        "value_ha": round(val, 2),
        "period": f"{season} {year_start}\u2192{year_end}",
    }
