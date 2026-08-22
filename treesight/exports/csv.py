"""CSV export builders — standard, bulk, and EUDR per-parcel (M4 §4.6)."""

from __future__ import annotations

import csv
import io
from typing import Any

from treesight.exports.frame_row import FrameRow
from treesight.exports.geojson import _toplevel_as_single_aoi
from treesight.pipeline.enrichment.determination import as_screening_determination

_EUDR_CSV_FIELDS = [
    "parcel_name",
    "area_ha",
    "center_lat",
    "center_lon",
    "determination_status",
    "determination_confidence",
    "determination_flags",
    "worldcover_dominant",
    "worldcover_tree_pct",
    "wdpa_is_protected",
    "ndvi_latest_mean",
    "ndvi_observations",
    "change_trajectory",
    "change_comparisons",
    "reviewer_note",
    "reviewed_by",
    "reviewed_at",
]


def _as_dict(value: Any) -> dict[str, Any]:
    """Return *value* if it's a dict, otherwise {} — guards against malformed Cosmos data."""
    return value if isinstance(value, dict) else {}


def _build_csv(manifest: dict[str, Any]) -> str:
    """Build a CSV string from the enrichment manifest.

    One row per frame with NDVI stats, weather context, and change detection.
    """
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])
    weather_daily = manifest.get("weather_daily")
    change_detection = manifest.get("change_detection", {})
    season_changes = change_detection.get("season_changes", [])

    frames = [FrameRow.from_dict(i, f) for i, f in enumerate(frame_plan)]

    # Build a lookup of change-detection results keyed by (season, year)
    change_lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for sc in season_changes:
        key = (sc.get("season", ""), sc.get("year_to", 0))
        change_lookup[key] = sc

    fieldnames = [
        "frame_index",
        "label",
        "year",
        "season",
        "start_date",
        "end_date",
        "collection",
        "is_naip",
        "display_search_id",
        "ndvi_search_id",
        "ndvi_scene_id",
        "resolution_m",
        "cloud_cover_pct",
        "acquired_at",
        "artifact_path",
        "ndvi_mean",
        "ndvi_min",
        "ndvi_max",
        "ndvi_std",
        "ndvi_change_from_previous",
        "mean_temp_c",
        "total_precip_mm",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()

    # Pre-compute average weather per frame date range
    daily_dates = weather_daily.get("dates", []) if weather_daily else []
    daily_temps = weather_daily.get("temp", []) if weather_daily else []
    daily_precip = weather_daily.get("precip", []) if weather_daily else []

    # Pre-group daily weather by date string for O(n+m) lookup
    weather_by_date: dict[str, tuple[float | None, float | None]] = {}
    for j, d in enumerate(daily_dates):
        t = daily_temps[j] if j < len(daily_temps) else None
        p = daily_precip[j] if j < len(daily_precip) else None
        weather_by_date[d] = (t, p)

    for frame in frames:
        ndvi = ndvi_stats[frame.frame_index] if frame.frame_index < len(ndvi_stats) else None

        # Weather aggregation for the frame's date range
        mean_temp = None
        total_precip = None
        if weather_by_date:
            temps_in_range = []
            precip_in_range = []
            for d, (t, p) in weather_by_date.items():
                if frame.start <= d <= frame.end:
                    if t is not None:
                        temps_in_range.append(t)
                    if p is not None:
                        precip_in_range.append(p)
            if temps_in_range:
                mean_temp = round(sum(temps_in_range) / len(temps_in_range), 1)
            if precip_in_range:
                total_precip = round(sum(precip_in_range), 1)

        # Change detection delta
        change = change_lookup.get((frame.season, int(frame.year) if frame.year else 0))
        ndvi_delta = change.get("mean_delta") if change else None

        prov = frame.provenance
        row = {
            "frame_index": frame.frame_index,
            "label": frame.label,
            "year": frame.year,
            "season": frame.season,
            "start_date": frame.start,
            "end_date": frame.end,
            "collection": frame.collection,
            "is_naip": frame.is_naip,
            "display_search_id": prov.get("display_search_id", ""),
            "ndvi_search_id": prov.get("ndvi_search_id", ""),
            "ndvi_scene_id": prov.get("ndvi_scene_id", ndvi.get("scene_id", "") if ndvi else ""),
            "resolution_m": prov.get("resolution_m", ""),
            "cloud_cover_pct": prov.get("cloud_cover_pct", ndvi.get("cloud_cover", "") if ndvi else ""),
            "acquired_at": prov.get("acquired_at", ndvi.get("datetime", "") if ndvi else ""),
            "artifact_path": prov.get("artifact_path", frame.ndvi_raster_path),
            "ndvi_mean": ndvi.get("mean", "") if ndvi else "",
            "ndvi_min": ndvi.get("min", "") if ndvi else "",
            "ndvi_max": ndvi.get("max", "") if ndvi else "",
            "ndvi_std": ndvi.get("std", "") if ndvi else "",
            "ndvi_change_from_previous": ndvi_delta if ndvi_delta is not None else "",
            "mean_temp_c": mean_temp if mean_temp is not None else "",
            "total_precip_mm": total_precip if total_precip is not None else "",
        }
        writer.writerow(row)

    return buf.getvalue()


def _build_bulk_csv(manifest: dict[str, Any]) -> str:
    """Build a per-AOI summary CSV from the enrichment manifest.

    One row per AOI with geometry, vegetation, change, and weather metrics.
    Requires ``per_aoi_metrics`` in the manifest (present for multi-AOI runs).
    """
    per_aoi = manifest.get("per_aoi_metrics", [])
    if not per_aoi:
        return _build_csv(manifest)

    fieldnames = [
        "feature_name",
        "feature_index",
        "area_ha",
        "perimeter_km",
        "centroid_lon",
        "centroid_lat",
        "ndvi_latest_mean",
        "health_class",
        "trend_direction",
        "total_loss_ha",
        "total_gain_ha",
        "net_change_ha",
        "trajectory",
        "temp_mean_c",
        "precip_total_mm",
        "ndvi_data_scope",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()

    for m in per_aoi:
        geo = m.get("geometry", {})
        veg = m.get("vegetation", {})
        latest = veg.get("latest_detail", {})
        change = m.get("change", {})
        weather = m.get("weather", {})

        writer.writerow(
            {
                "feature_name": m.get("feature_name", ""),
                "feature_index": m.get("feature_index", 0),
                "area_ha": geo.get("area_ha", ""),
                "perimeter_km": geo.get("perimeter_km", ""),
                "centroid_lon": geo.get("centroid_lon", ""),
                "centroid_lat": geo.get("centroid_lat", ""),
                "ndvi_latest_mean": latest.get("mean", ""),
                "health_class": veg.get("health_class", ""),
                "trend_direction": veg.get("trend_direction", ""),
                "total_loss_ha": change.get("total_loss_ha", ""),
                "total_gain_ha": change.get("total_gain_ha", ""),
                "net_change_ha": change.get("net_change_ha", ""),
                "trajectory": change.get("trajectory", ""),
                "temp_mean_c": weather.get("temp_mean_c", ""),
                "precip_total_mm": weather.get("precip_total_mm", ""),
                "ndvi_data_scope": m.get("ndvi_data_scope", ""),
            }
        )

    return buf.getvalue()


def _build_eudr_csv(
    manifest: dict[str, Any],
    run_record: dict[str, Any] | None = None,
) -> str:
    """Build a per-parcel CSV with EUDR deforestation evidence.

    One row per AOI from ``per_aoi_enrichment``.  Failed AOIs are included
    with ``determination_status`` = ``error``.

    For single-parcel runs (no ``per_aoi_enrichment``), falls back to
    top-level manifest evidence.  When ``run_record`` is provided, each row
    includes the reviewer note, reviewer identity and timestamp from any
    saved human assessment.
    """
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if not per_aoi:
        per_aoi = _toplevel_as_single_aoi(manifest)

    parcel_reviews: dict[str, dict[str, Any]] = {}
    if run_record:
        parcel_reviews = _as_dict(run_record.get("parcel_reviews"))

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_EUDR_CSV_FIELDS)
    writer.writeheader()

    for idx, aoi in enumerate(per_aoi):
        if "error" in aoi:
            writer.writerow({"parcel_name": aoi.get("name", ""), "determination_status": "error"})
            continue

        center = aoi.get("center", {})
        determination = as_screening_determination(aoi.get("determination"))
        wc = aoi.get("worldcover", {})
        lc = wc.get("land_cover", {}) if wc.get("available") else {}
        wdpa = aoi.get("wdpa", {})
        ndvi_stats = aoi.get("ndvi_stats", [])
        valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
        cd_summary = aoi.get("change_detection", {}).get("summary", {})
        review = _as_dict(parcel_reviews.get(str(idx)))

        writer.writerow(
            {
                "parcel_name": aoi.get("name", ""),
                "area_ha": aoi.get("area_ha", ""),
                "center_lat": center.get("lat", ""),
                "center_lon": center.get("lon", ""),
                "determination_status": determination.screening_outcome,
                "determination_confidence": determination.confidence,
                "determination_flags": "; ".join(determination.flags),
                "worldcover_dominant": lc.get("dominant_class", ""),
                "worldcover_tree_pct": ({c["code"]: c for c in lc.get("classes", [])}.get(10, {}).get("area_pct", "")),
                "wdpa_is_protected": wdpa.get("is_protected", ""),
                "ndvi_latest_mean": valid[-1]["mean"] if valid else "",
                "ndvi_observations": len(valid),
                "change_trajectory": cd_summary.get("trajectory", ""),
                "change_comparisons": cd_summary.get("comparisons", ""),
                "reviewer_note": review.get("note", ""),
                "reviewed_by": review.get("reviewed_by", ""),
                "reviewed_at": review.get("reviewed_at", ""),
            }
        )

    return buf.getvalue()
