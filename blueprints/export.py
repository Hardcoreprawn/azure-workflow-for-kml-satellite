"""Data export endpoints — GeoJSON and CSV download (M4 §4.6).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import csv
import io
import json
import logging
from typing import Any

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import (
    cors_headers,
    cors_preflight,
    error_response,
    fetch_enrichment_manifest,
)
from treesight.constants import EUDR_CUTOFF_DATE
from treesight.security.rate_limit import get_client_ip, pipeline_limiter

bp = func.Blueprint()
logger = logging.getLogger(__name__)

_ALLOWED_FORMATS = {"geojson", "csv", "csv-bulk", "pdf", "eudr-geojson", "eudr-csv", "eudr-pdf"}


# ---------------------------------------------------------------------------
# GeoJSON export
# ---------------------------------------------------------------------------


def _build_geojson(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection from the enrichment manifest.

    The AOI polygon becomes the geometry; NDVI stats, weather, and frame
    metadata are stored as Feature properties.
    """
    coords = manifest.get("coords", [])
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])
    weather_monthly = manifest.get("weather_monthly")
    change_detection = manifest.get("change_detection", {})

    # Build per-frame features (each frame = one temporal observation)
    features: list[dict[str, Any]] = []
    for i, frame in enumerate(frame_plan):
        ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None
        props: dict[str, Any] = {
            "frame_index": i,
            "label": frame.get("label", ""),
            "year": frame.get("year"),
            "season": frame.get("season", ""),
            "start_date": frame.get("start", ""),
            "end_date": frame.get("end", ""),
            "collection": frame.get("collection", ""),
            "is_naip": frame.get("is_naip", False),
        }
        if ndvi:
            props["ndvi_mean"] = ndvi.get("mean")
            props["ndvi_min"] = ndvi.get("min")
            props["ndvi_max"] = ndvi.get("max")
            props["ndvi_std"] = ndvi.get("std")
            props["ndvi_scene_id"] = ndvi.get("scene_id")

        # Close polygon ring if needed
        ring = list(coords)
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [ring],
            },
            "properties": props,
        }
        features.append(feature)

    # Summary feature with change-detection & weather data
    summary_props: dict[str, Any] = {
        "type": "summary",
        "enriched_at": manifest.get("enriched_at", ""),
        "enrichment_duration_seconds": manifest.get("enrichment_duration_seconds"),
    }
    if weather_monthly:
        summary_props["weather_monthly"] = weather_monthly
    if change_detection.get("summary"):
        summary_props["change_detection_summary"] = change_detection["summary"]

    center = manifest.get("center", {})
    if center:
        summary_feature: dict[str, Any] = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [center.get("lon", 0), center.get("lat", 0)],
            },
            "properties": summary_props,
        }
        features.append(summary_feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _build_csv(manifest: dict[str, Any]) -> str:
    """Build a CSV string from the enrichment manifest.

    One row per frame with NDVI stats, weather context, and change detection.
    """
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])
    weather_daily = manifest.get("weather_daily")
    change_detection = manifest.get("change_detection", {})
    season_changes = change_detection.get("season_changes", [])

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

    for i, frame in enumerate(frame_plan):
        ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None

        # Weather aggregation for the frame's date range
        mean_temp = None
        total_precip = None
        if weather_by_date:
            start, end = frame.get("start", ""), frame.get("end", "")
            temps_in_range = []
            precip_in_range = []
            for d, (t, p) in weather_by_date.items():
                if start <= d <= end:
                    if t is not None:
                        temps_in_range.append(t)
                    if p is not None:
                        precip_in_range.append(p)
            if temps_in_range:
                mean_temp = round(sum(temps_in_range) / len(temps_in_range), 1)
            if precip_in_range:
                total_precip = round(sum(precip_in_range), 1)

        # Change detection delta
        change = change_lookup.get((frame.get("season", ""), frame.get("year", 0)))
        ndvi_delta = change.get("mean_delta") if change else None

        row = {
            "frame_index": i,
            "label": frame.get("label", ""),
            "year": frame.get("year", ""),
            "season": frame.get("season", ""),
            "start_date": frame.get("start", ""),
            "end_date": frame.get("end", ""),
            "collection": frame.get("collection", ""),
            "is_naip": frame.get("is_naip", False),
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


# ---------------------------------------------------------------------------
# EUDR per-parcel GeoJSON export (#582)
# ---------------------------------------------------------------------------


def _build_eudr_geojson(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a per-parcel GeoJSON FeatureCollection with EUDR evidence.

    Each AOI in ``per_aoi_enrichment`` becomes a Feature with EUDR-specific
    properties: determination status, WorldCover baseline, WDPA overlap,
    NDVI summary, and change trajectory.
    """
    per_aoi = manifest.get("per_aoi_enrichment", [])

    features: list[dict[str, Any]] = []
    for aoi in per_aoi:
        props: dict[str, Any] = {"parcel_name": aoi.get("name", "")}

        if "error" in aoi:
            props["error"] = aoi["error"]
            features.append({"type": "Feature", "geometry": None, "properties": props})
            continue

        props["area_ha"] = aoi.get("area_ha", 0.0)
        center = aoi.get("center", {})
        props["center_lat"] = center.get("lat")
        props["center_lon"] = center.get("lon")

        # Determination
        det = aoi.get("determination", {})
        props["determination_status"] = det.get("status", "unknown")
        props["determination_confidence"] = det.get("confidence", "unknown")
        props["determination_flags"] = det.get("flags", [])

        # WorldCover baseline
        wc = aoi.get("worldcover", {})
        if wc.get("available"):
            lc = wc.get("land_cover", {})
            props["worldcover_dominant"] = lc.get("dominant_class", "")
            classes = {c["code"]: c for c in lc.get("classes", [])}
            props["worldcover_tree_pct"] = classes.get(10, {}).get("area_pct", 0.0)
        else:
            props["worldcover_dominant"] = ""
            props["worldcover_tree_pct"] = None

        # WDPA
        wdpa = aoi.get("wdpa", {})
        props["wdpa_checked"] = wdpa.get("checked", False)
        props["wdpa_is_protected"] = wdpa.get("is_protected", False)

        # NDVI summary
        ndvi_stats = aoi.get("ndvi_stats", [])
        valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
        if valid:
            props["ndvi_latest_mean"] = valid[-1]["mean"]
            props["ndvi_observations"] = len(valid)
        else:
            props["ndvi_latest_mean"] = None
            props["ndvi_observations"] = 0

        # Change detection
        cd = aoi.get("change_detection", {})
        summary = cd.get("summary", {})
        props["change_trajectory"] = summary.get("trajectory", "unknown")
        props["change_comparisons"] = summary.get("comparisons", 0)

        # Build polygon geometry
        coords = aoi.get("coords", [])
        ring = list(coords)
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])

        geometry: dict[str, Any] | None = (
            {"type": "Polygon", "coordinates": [ring]} if ring else None
        )

        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# EUDR per-parcel CSV export (#582)
# ---------------------------------------------------------------------------

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
]


def _build_eudr_csv(manifest: dict[str, Any]) -> str:
    """Build a per-parcel CSV with EUDR deforestation evidence.

    One row per AOI from ``per_aoi_enrichment``.  Failed AOIs are included
    with ``determination_status`` = ``error``.
    """
    per_aoi = manifest.get("per_aoi_enrichment", [])

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_EUDR_CSV_FIELDS)
    writer.writeheader()

    for aoi in per_aoi:
        if "error" in aoi:
            writer.writerow({"parcel_name": aoi.get("name", ""), "determination_status": "error"})
            continue

        center = aoi.get("center", {})
        det = aoi.get("determination", {})
        wc = aoi.get("worldcover", {})
        lc = wc.get("land_cover", {}) if wc.get("available") else {}
        wdpa = aoi.get("wdpa", {})
        ndvi_stats = aoi.get("ndvi_stats", [])
        valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
        cd_summary = aoi.get("change_detection", {}).get("summary", {})

        writer.writerow(
            {
                "parcel_name": aoi.get("name", ""),
                "area_ha": aoi.get("area_ha", ""),
                "center_lat": center.get("lat", ""),
                "center_lon": center.get("lon", ""),
                "determination_status": det.get("status", "unknown"),
                "determination_confidence": det.get("confidence", "unknown"),
                "determination_flags": "; ".join(det.get("flags", [])),
                "worldcover_dominant": lc.get("dominant_class", ""),
                "worldcover_tree_pct": (
                    {c["code"]: c for c in lc.get("classes", [])}.get(10, {}).get("area_pct", "")
                ),
                "wdpa_is_protected": wdpa.get("is_protected", ""),
                "ndvi_latest_mean": valid[-1]["mean"] if valid else "",
                "ndvi_observations": len(valid),
                "change_trajectory": cd_summary.get("trajectory", ""),
                "change_comparisons": cd_summary.get("comparisons", ""),
            }
        )

    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF export (EUDR audit report)
# ---------------------------------------------------------------------------


def _pdf_header(pdf: Any, manifest: dict[str, Any], instance_id: str) -> None:
    """Write title and metadata section of the PDF."""
    eudr_mode = manifest.get("eudr_mode", False)
    center = manifest.get("center", {})

    pdf.set_font("Helvetica", "B", 18)
    title = "EUDR Due-Diligence Report" if eudr_mode else "Canopex Analysis Report"
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Report ID: {instance_id}", new_x="LMARGIN", new_y="NEXT")
    enriched_at = manifest.get("enriched_at", "")
    if enriched_at:
        pdf.cell(0, 6, f"Generated: {enriched_at[:19]}", new_x="LMARGIN", new_y="NEXT")
    if center:
        pdf.cell(
            0,
            6,
            f"Location: {center.get('lat', 0):.4f}, {center.get('lon', 0):.4f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.ln(6)


def _safe_text(text: str) -> str:
    """Normalise unicode punctuation to latin-1 safe equivalents for core PDF fonts."""
    return (
        text.replace("\u2014", "--")
        .replace("\u2013", "-")
        .replace("\u2026", "...")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2192", "->")
        .replace("\u2190", "<-")
    )


def _pdf_eudr_section(pdf: Any, manifest: dict[str, Any]) -> None:
    """Write EUDR compliance summary section."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "EUDR Compliance Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    cutoff = manifest.get("eudr_date_start", EUDR_CUTOFF_DATE)
    pdf.cell(0, 6, "EUDR cutoff date: 31 December 2020", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        6,
        f"Analysis period: {cutoff} to present",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    wc = manifest.get("worldcover", {})
    if wc.get("available"):
        lc = wc.get("land_cover", {})
        dominant = lc.get("dominant_class", "N/A")
        pdf.cell(
            0,
            6,
            f"ESA WorldCover: {dominant} (dominant)",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        for cls in lc.get("classes", [])[:5]:
            label = cls.get("label") or "Unknown"
            area_pct = cls.get("area_pct")
            try:
                area_pct_str = f"{float(area_pct):.1f}%" if area_pct is not None else "N/A"
            except (TypeError, ValueError):
                area_pct_str = "N/A"
            pdf.cell(
                0,
                5,
                f"  {label}: {area_pct_str}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

    wdpa = manifest.get("wdpa", {})
    if wdpa.get("checked"):
        status = "Yes -- protected area overlap detected" if wdpa.get("is_protected") else "No"
        pdf.cell(
            0,
            6,
            f"Protected area (WDPA): {status}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        for pa in wdpa.get("protected_areas", []):
            pdf.cell(
                0,
                6,
                _safe_text(f"  - {pa.get('name', '')} ({pa.get('designation', '')})"),
                new_x="LMARGIN",
                new_y="NEXT",
            )

    pdf.ln(4)


def _pdf_vegetation_section(
    pdf: Any,
    manifest: dict[str, Any],
) -> None:
    """Write vegetation analysis and frame detail table."""
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])
    change_detection = manifest.get("change_detection", {})

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Vegetation Analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    summary = change_detection.get("summary", {})
    if summary:
        trajectory = summary.get("trajectory", "Unknown")
        comparisons = summary.get("comparisons", 0)
        pdf.cell(
            0,
            6,
            f"Trajectory: {trajectory} ({comparisons} year-over-year comparisons)",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    valid_ndvi = [s for s in ndvi_stats if s and s.get("mean") is not None]
    if valid_ndvi:
        means = [s["mean"] for s in valid_ndvi]
        overall_avg = sum(means) / len(means)
        pdf.cell(
            0,
            6,
            f"NDVI observations: {len(valid_ndvi)} frames, "
            f"average: {overall_avg:.3f}, "
            f"range: {min(means):.3f} to {max(means):.3f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.ln(4)

    # Frame detail table
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Frame Details", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 8)
    col_ratios = [0.18, 0.11, 0.11, 0.16, 0.16, 0.12, 0.16]
    page_w = pdf.epw  # effective page width (inside margins)
    col_widths = [round(r * page_w, 1) for r in col_ratios]
    headers_row = ["Label", "Year", "Season", "Start", "End", "NDVI Mean", "Collection"]
    for i, h in enumerate(headers_row):
        pdf.cell(col_widths[i], 6, h, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for idx, frame in enumerate(frame_plan):
        ndvi = ndvi_stats[idx] if idx < len(ndvi_stats) else None
        ndvi_val = f"{ndvi['mean']:.3f}" if ndvi and ndvi.get("mean") is not None else "--"
        row_data = [
            _safe_text(frame.get("label", ""))[:18],
            str(frame.get("year", "")),
            frame.get("season", ""),
            frame.get("start", ""),
            frame.get("end", ""),
            ndvi_val,
            frame.get("collection", ""),
        ]
        for i, val in enumerate(row_data):
            pdf.cell(col_widths[i], 5, val, border=1)
        pdf.ln()

    pdf.ln(6)


def _pdf_per_parcel_sections(pdf: Any, per_aoi: list[dict[str, Any]]) -> None:
    """Write per-parcel EUDR evidence sections (#582)."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Per-Parcel Evidence", new_x="LMARGIN", new_y="NEXT")

    for idx, aoi in enumerate(per_aoi):
        name = aoi.get("name", f"Parcel {idx + 1}")

        if "error" in aoi:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, _safe_text(f"{name} -- ERROR"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 5, "Enrichment failed for this parcel.", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            continue

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _safe_text(name), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)

        # Area and location
        area = aoi.get("area_ha", 0.0)
        center = aoi.get("center", {})
        pdf.cell(
            0,
            5,
            f"Area: {area:.2f} ha | Centre: {center.get('lat', 0):.4f}, {center.get('lon', 0):.4f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        # Determination
        det = aoi.get("determination", {})
        status = det.get("status", "unknown")
        confidence = det.get("confidence", "unknown")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(
            0,
            5,
            f"Determination: {status} (confidence: {confidence})",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("Helvetica", "", 9)
        for flag in det.get("flags", []):
            pdf.cell(0, 5, _safe_text(f"  - {flag}"), new_x="LMARGIN", new_y="NEXT")

        # WorldCover
        wc = aoi.get("worldcover", {})
        if wc.get("available"):
            lc = wc.get("land_cover", {})
            pdf.cell(
                0,
                5,
                f"WorldCover: {lc.get('dominant_class', 'N/A')} (dominant)",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # WDPA
        wdpa = aoi.get("wdpa", {})
        if wdpa.get("checked"):
            prot = "Yes" if wdpa.get("is_protected") else "No"
            pdf.cell(
                0,
                5,
                f"Protected area overlap: {prot}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # NDVI summary
        ndvi_stats = aoi.get("ndvi_stats", [])
        valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
        if valid:
            means = [s["mean"] for s in valid]
            pdf.cell(
                0,
                5,
                f"NDVI: {len(valid)} observations, latest {means[-1]:.3f}, "
                f"range {min(means):.3f}-{max(means):.3f}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        # Change detection
        cd = aoi.get("change_detection", {}).get("summary", {})
        if cd:
            pdf.cell(
                0,
                5,
                f"Change trajectory: {cd.get('trajectory', 'unknown')} "
                f"({cd.get('comparisons', 0)} comparisons)",
                new_x="LMARGIN",
                new_y="NEXT",
            )

        pdf.ln(3)


def _build_pdf(manifest: dict[str, Any], instance_id: str = "") -> bytes:
    """Build an audit-quality PDF report from the enrichment manifest.

    Uses fpdf2 (pure Python, no system dependencies).
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    _pdf_header(pdf, manifest, instance_id)

    if manifest.get("eudr_mode", False):
        _pdf_eudr_section(pdf, manifest)

    _pdf_vegetation_section(pdf, manifest)

    # Weather summary
    weather_monthly = manifest.get("weather_monthly")
    if weather_monthly:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Weather Context", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if isinstance(weather_monthly, list):
            months = [m.get("month", "") for m in weather_monthly]
            temps = [m.get("mean_temp") for m in weather_monthly]
            precips = [m.get("total_precip") for m in weather_monthly]
        else:
            months = weather_monthly.get("months", []) or weather_monthly.get("labels", [])
            temps = weather_monthly.get("avg_temp", []) or weather_monthly.get("temp", [])
            precips = weather_monthly.get("total_precip", []) or weather_monthly.get("precip", [])
        if months:
            pdf.cell(
                0,
                6,
                f"Weather period: {months[0]} to {months[-1]} ({len(months)} months)",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        if temps:
            avg_t = sum(t for t in temps if t is not None) / max(
                1, len([t for t in temps if t is not None])
            )
            pdf.cell(0, 6, f"Mean temperature: {avg_t:.1f} C", new_x="LMARGIN", new_y="NEXT")
        if precips:
            total_p = sum(p for p in precips if p is not None)
            pdf.cell(
                0,
                6,
                f"Total precipitation: {total_p:.0f} mm",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.ln(4)

    # Per-parcel EUDR evidence sections (#582)
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if per_aoi:
        _pdf_per_parcel_sections(pdf, per_aoi)

    # Disclaimer
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0,
        4,
        "Disclaimer: This report is generated from satellite imagery analysis and "
        "provides supporting evidence only. It does not constitute a complete EUDR "
        "due-diligence assessment under Regulation (EU) 2023/1115. Operators remain "
        "responsible for fulfilling all regulatory obligations.",
    )

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Audit-grade EUDR evidence PDF (#587)
# ---------------------------------------------------------------------------

_EUDR_CUTOFF_YEAR = 2021  # Post-31 December 2020


def _audit_cover_page(pdf: Any, manifest: dict[str, Any], instance_id: str) -> None:
    """Write a structured cover page for the EUDR audit report."""
    pdf.set_font("Helvetica", "B", 22)
    pdf.ln(30)
    pdf.cell(0, 14, "EUDR Satellite Evidence Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, f"Report reference: {instance_id}", align="C", new_x="LMARGIN", new_y="NEXT")
    enriched_at = manifest.get("enriched_at", "")
    if enriched_at:
        pdf.cell(0, 7, f"Generated: {enriched_at[:19]}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # Operator info (if available)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 11)
    operator = manifest.get("operator_name", "")
    if operator:
        pdf.cell(
            0, 7, f"Operator: {_safe_text(operator)}", align="C", new_x="LMARGIN", new_y="NEXT"
        )
    commodity = manifest.get("commodity", "")
    if commodity:
        pdf.cell(
            0, 7, f"Commodity: {_safe_text(commodity)}", align="C", new_x="LMARGIN", new_y="NEXT"
        )

    # Summary counts
    per_aoi = manifest.get("per_aoi_enrichment", [])
    total = len(per_aoi)
    succeeded = [a for a in per_aoi if "error" not in a]
    free_count = sum(
        1 for a in succeeded if a.get("determination", {}).get("status") == "deforestation_free"
    )
    review_count = len(succeeded) - free_count

    pdf.ln(8)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, f"Production plots assessed: {total}", align="C", new_x="LMARGIN", new_y="NEXT")
    if succeeded:
        pdf.cell(
            0,
            7,
            f"Deforestation-free: {free_count} | Further review: {review_count}",
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    cutoff = manifest.get("eudr_date_start", EUDR_CUTOFF_DATE)
    pdf.cell(
        0,
        7,
        f"Assessment period: {cutoff} to present",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(
        0,
        6,
        "Generated by Canopex satellite analysis platform",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )


def _audit_executive_summary(pdf: Any, manifest: dict[str, Any]) -> None:
    """Write executive summary section."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "1. Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    per_aoi = manifest.get("per_aoi_enrichment", [])
    succeeded = [a for a in per_aoi if "error" not in a]
    failed = [a for a in per_aoi if "error" in a]
    free_count = sum(
        1 for a in succeeded if a.get("determination", {}).get("status") == "deforestation_free"
    )
    review_count = len(succeeded) - free_count

    pdf.cell(0, 6, f"Total plots assessed: {len(per_aoi)}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        6,
        f"Plots classified deforestation-free: {free_count} of {len(succeeded)}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    if review_count:
        pdf.cell(
            0,
            6,
            f"Plots requiring further review: {review_count}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    if failed:
        pdf.cell(
            0,
            6,
            f"Plots with enrichment errors: {len(failed)}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(3)
    pdf.cell(0, 6, "Data sources:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0,
        5,
        "  - Sentinel-2 L2A (10m, via Microsoft Planetary Computer)",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(0, 5, "  - ESA WorldCover 10m (2021)", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "  - WDPA (World Database on Protected Areas)", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        5,
        "  - IO Annual Land Use / Land Cover (2017-2023)",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(0, 5, "  - ALOS PALSAR Forest/Non-Forest", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _audit_methodology(pdf: Any) -> None:
    """Write methodology section."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "2. Methodology", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)

    sections = [
        (
            "Satellite imagery",
            "Sentinel-2 Level-2A surface reflectance imagery at 10m spatial resolution, "
            "sourced via Microsoft Planetary Computer STAC API. Cloud-masked using the "
            "SCL (Scene Classification Layer) band.",
        ),
        (
            "Vegetation index",
            "NDVI (Normalized Difference Vegetation Index) computed from Sentinel-2 "
            "bands B08 (NIR) and B04 (Red). NDVI values range from -1 to +1; healthy "
            "vegetation typically exceeds 0.4.",
        ),
        (
            "Change detection",
            "Season-matched year-over-year NDVI comparison. Each observation period is "
            "compared to the same season in the preceding year. Loss is flagged when NDVI "
            "decline exceeds the deforestation threshold across a significant portion of "
            "the parcel.",
        ),
        (
            "Baseline reference",
            "The EUDR cutoff date is 31 December 2020. Imagery from the first available "
            "post-cutoff observation period serves as the baseline. All subsequent periods "
            "are compared against this baseline and against each other.",
        ),
        (
            "Land cover classification",
            "ESA WorldCover 10m (2021) provides baseline land-cover class (tree cover, "
            "cropland, grassland, etc.) at the time closest to the EUDR cutoff date.",
        ),
        (
            "Protected areas",
            "WDPA (World Database on Protected Areas) is checked for spatial overlap "
            "with each parcel. Overlap with a protected area is flagged as a risk factor.",
        ),
        (
            "Deforestation determination",
            "A parcel is classified 'deforestation_free' when: (1) no significant NDVI "
            "loss (>5% of area or >1 ha) is detected in any post-2020 comparison period, "
            "and (2) the overall vegetation trajectory is not declining. Otherwise the "
            "parcel is classified 'further_review'.",
        ),
        (
            "Limitations",
            "Cloud cover may reduce temporal coverage. Mixed pixels at parcel boundaries "
            "can affect NDVI accuracy. Sentinel-2 revisit interval is 5 days at the "
            "equator. NDVI is a proxy for vegetation health, not a direct measure of "
            "tree count or biomass. This analysis provides supporting evidence only.",
        ),
    ]

    for title, body in sections:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4, body)
        pdf.ln(2)

    pdf.ln(2)


def _audit_single_parcel(pdf: Any, aoi: dict[str, Any], section_num: str) -> None:
    """Write a single parcel's assessment in the audit report."""
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(
        0,
        8,
        _safe_text(f"{section_num} {aoi.get('name', 'Parcel')}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 9)

    # Location and area
    area = aoi.get("area_ha", 0.0)
    center = aoi.get("center", {})
    coords = aoi.get("coords", [])
    pdf.cell(
        0,
        5,
        f"Area: {area:.2f} ha | Centre: "
        f"{center.get('lat', 0):.6f}, {center.get('lon', 0):.6f} | "
        f"Vertices: {len(coords)}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    # Determination result
    det = aoi.get("determination", {})
    status = det.get("status", "unknown")
    confidence = det.get("confidence", "unknown")
    pdf.set_font("Helvetica", "B", 10)
    status_label = {
        "deforestation_free": "DEFORESTATION-FREE",
        "further_review": "FURTHER REVIEW REQUIRED",
    }.get(status, status.upper())
    pdf.cell(
        0,
        7,
        f"Determination: {status_label} (confidence: {confidence})",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 9)

    for flag in det.get("flags", []):
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 5, _safe_text(f"  ! {flag}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    # WorldCover baseline
    wc = aoi.get("worldcover", {})
    if wc.get("available"):
        lc = wc.get("land_cover", {})
        pdf.cell(
            0,
            5,
            f"Land cover (WorldCover 2021): {lc.get('dominant_class', 'N/A')} (dominant)",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        for cls in lc.get("classes", [])[:5]:
            label = cls.get("label", "")
            pct = cls.get("area_pct")
            pct_str = f"{float(pct):.1f}%" if pct is not None else "N/A"
            pdf.cell(0, 4, f"    {label}: {pct_str}", new_x="LMARGIN", new_y="NEXT")

    # Protected area
    wdpa = aoi.get("wdpa", {})
    if wdpa.get("checked"):
        prot = "YES -- overlap detected" if wdpa.get("is_protected") else "No overlap"
        pdf.cell(0, 5, f"Protected area (WDPA): {prot}", new_x="LMARGIN", new_y="NEXT")

    # NDVI timeseries
    ndvi_stats = aoi.get("ndvi_stats", [])
    frame_plan = aoi.get("frame_plan", [])
    valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
    if valid:
        means = [s["mean"] for s in valid]
        pdf.cell(
            0,
            5,
            f"NDVI: {len(valid)} observations | "
            f"Latest: {means[-1]:.3f} | Range: {min(means):.3f}-{max(means):.3f}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    # Change detection
    cd_summary = aoi.get("change_detection", {}).get("summary", {})
    if cd_summary:
        pdf.cell(
            0,
            5,
            f"Change trajectory: {cd_summary.get('trajectory', 'unknown')} "
            f"({cd_summary.get('comparisons', 0)} comparisons)",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        loss = cd_summary.get("total_loss_ha")
        gain = cd_summary.get("total_gain_ha")
        if loss is not None or gain is not None:
            pdf.cell(
                0,
                5,
                f"  Loss: {loss or 0:.2f} ha | Gain: {gain or 0:.2f} ha",
                new_x="LMARGIN",
                new_y="NEXT",
            )

    # Data provenance (scene IDs)
    scenes = []
    for i, stat in enumerate(ndvi_stats):
        if stat and stat.get("scene_id"):
            label = frame_plan[i].get("label", f"Frame {i}") if i < len(frame_plan) else ""
            scenes.append(f"{label}: {stat['scene_id']}")
    if scenes:
        pdf.cell(0, 5, "Scene provenance:", new_x="LMARGIN", new_y="NEXT")
        for scene in scenes[:10]:
            pdf.cell(0, 4, f"    {scene}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)


def _audit_per_parcel(pdf: Any, per_aoi: list[dict[str, Any]]) -> None:
    """Write detailed per-parcel assessment sections."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "3. Per-Parcel Assessment", new_x="LMARGIN", new_y="NEXT")

    for idx, aoi in enumerate(per_aoi):
        name = aoi.get("name", f"Parcel {idx + 1}")
        section_num = f"3.{idx + 1}"

        if "error" in aoi:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(
                0,
                8,
                _safe_text(f"{section_num} {name} -- ENRICHMENT FAILED"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(
                0,
                5,
                "Data enrichment failed for this parcel. No assessment available.",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.ln(4)
            continue

        _audit_single_parcel(pdf, aoi, section_num)


def _audit_appendix(
    pdf: Any,
    manifest: dict[str, Any],
) -> None:
    """Write appendix with post-2020 NDVI timeseries table."""
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])

    # Filter to post-2020 only
    filtered: list[tuple[dict, dict | None]] = []
    for i, frame in enumerate(frame_plan):
        year = frame.get("year", 0)
        if year >= _EUDR_CUTOFF_YEAR:
            ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None
            filtered.append((frame, ndvi))

    if not filtered:
        return

    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "4. Appendix: Post-2020 NDVI Timeseries", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 8)
    col_ratios = [0.14, 0.09, 0.09, 0.12, 0.12, 0.10, 0.10, 0.10, 0.14]
    page_w = pdf.epw
    col_widths = [round(r * page_w, 1) for r in col_ratios]
    headers_row = [
        "Label",
        "Year",
        "Season",
        "Start",
        "End",
        "NDVI Mean",
        "NDVI Min",
        "NDVI Max",
        "Scene ID",
    ]
    for i, h in enumerate(headers_row):
        pdf.cell(col_widths[i], 6, h, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    for frame, ndvi in filtered:
        ndvi_mean = f"{ndvi['mean']:.3f}" if ndvi and ndvi.get("mean") is not None else "--"
        ndvi_min = f"{ndvi['min']:.3f}" if ndvi and ndvi.get("min") is not None else "--"
        ndvi_max = f"{ndvi['max']:.3f}" if ndvi and ndvi.get("max") is not None else "--"
        scene_id = (ndvi.get("scene_id", "") if ndvi else "")[:16]

        row_data = [
            _safe_text(frame.get("label", ""))[:16],
            str(frame.get("year", "")),
            frame.get("season", ""),
            frame.get("start", ""),
            frame.get("end", ""),
            ndvi_mean,
            ndvi_min,
            ndvi_max,
            scene_id,
        ]
        for i, val in enumerate(row_data):
            pdf.cell(col_widths[i], 5, val, border=1)
        pdf.ln()

    pdf.ln(4)


def _audit_disclaimer(pdf: Any) -> None:
    """Write legal disclaimer for the audit report."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "Legal Disclaimer", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0,
        4,
        "This report provides satellite-based evidence to support EUDR due diligence "
        "under Regulation (EU) 2023/1115. It does not constitute a complete Due Diligence "
        "Statement (DDS). Operators remain responsible for fulfilling all regulatory "
        "obligations including risk assessment, mitigation measures, and submission of "
        "the DDS to the EU Information System.\n\n"
        "The analysis is based on publicly available satellite imagery and geospatial "
        "datasets. Results are subject to the limitations of remote sensing including "
        "cloud cover, sensor resolution, and mixed-pixel effects. All NDVI and change "
        "detection results should be interpreted as supporting evidence, not definitive "
        "proof of land-use status.\n\n"
        "Methodology: Sentinel-2 L2A via Microsoft Planetary Computer; NDVI change "
        "detection; ESA WorldCover 2021; WDPA protected area overlay; IO Annual LULC; "
        "ALOS PALSAR Forest/Non-Forest.",
    )


def build_eudr_audit_pdf(manifest: dict[str, Any], instance_id: str = "") -> bytes:
    """Build an audit-grade EUDR evidence PDF report (#587).

    Structured for compliance officers: cover page, executive summary,
    methodology, per-parcel assessment, post-2020 NDVI appendix, and
    legal disclaimer.
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # 1. Cover page
    pdf.add_page()
    _audit_cover_page(pdf, manifest, instance_id)

    # 2. Executive summary
    pdf.add_page()
    _audit_executive_summary(pdf, manifest)

    # 3. Methodology
    _audit_methodology(pdf)

    # 4. Per-parcel assessment
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if per_aoi:
        pdf.add_page()
        _audit_per_parcel(pdf, per_aoi)

    # 5. Appendix: post-2020 NDVI timeseries
    _audit_appendix(pdf, manifest)

    # 6. Legal disclaimer
    _audit_disclaimer(pdf)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------


@bp.route(
    route="export/{instance_id}/{format}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def export_data(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/export/{instance_id}/{format} — download enrichment data.

    Supported formats: ``geojson``, ``csv``, ``csv-bulk``, ``pdf``,
    ``eudr-geojson``, ``eudr-csv``, ``eudr-pdf``.

    The ``csv-bulk`` format produces one row per AOI with aggregated metrics.
    Falls back to the regular temporal CSV when ``per_aoi_metrics`` is absent.
    Returns the file as a downloadable attachment.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return error_response(429, "Too many requests — please wait before trying again", req=req)

    fmt = (req.route_params.get("format") or "").lower()
    if fmt not in _ALLOWED_FORMATS:
        return error_response(
            400,
            f"Unsupported format '{fmt}'. Use one of: {', '.join(sorted(_ALLOWED_FORMATS))}",
            req=req,
        )

    manifest, err = await fetch_enrichment_manifest(req, client)
    if err:
        return err
    assert manifest is not None  # ensured by err check above

    instance_id = req.route_params.get("instance_id", "")
    headers = cors_headers(req)

    if fmt == "geojson":
        geojson = _build_geojson(manifest)
        body = json.dumps(geojson, indent=2, default=str)
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}.geojson"'
        return func.HttpResponse(
            body,
            status_code=200,
            mimetype="application/geo+json",
            headers=headers,
        )

    if fmt == "csv":
        csv_body = _build_csv(manifest)
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}.csv"'
        return func.HttpResponse(
            csv_body,
            status_code=200,
            mimetype="text/csv",
            headers=headers,
        )

    if fmt == "csv-bulk":
        csv_body = _build_bulk_csv(manifest)
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}_bulk.csv"'
        return func.HttpResponse(
            csv_body,
            status_code=200,
            mimetype="text/csv",
            headers=headers,
        )

    if fmt == "eudr-geojson":
        geojson = _build_eudr_geojson(manifest)
        body = json.dumps(geojson, indent=2, default=str)
        headers["Content-Disposition"] = (
            f'attachment; filename="treesight_{instance_id}_eudr.geojson"'
        )
        return func.HttpResponse(
            body,
            status_code=200,
            mimetype="application/geo+json",
            headers=headers,
        )

    if fmt == "eudr-csv":
        csv_body = _build_eudr_csv(manifest)
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}_eudr.csv"'
        return func.HttpResponse(
            csv_body,
            status_code=200,
            mimetype="text/csv",
            headers=headers,
        )

    if fmt == "eudr-pdf":
        pdf_bytes = build_eudr_audit_pdf(manifest, instance_id)
        headers["Content-Disposition"] = (
            f'attachment; filename="treesight_{instance_id}_eudr_report.pdf"'
        )
        return func.HttpResponse(
            pdf_bytes,
            status_code=200,
            mimetype="application/pdf",
            headers=headers,
        )

    # PDF
    pdf_bytes = _build_pdf(manifest, instance_id)
    headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}.pdf"'
    return func.HttpResponse(
        pdf_bytes,
        status_code=200,
        mimetype="application/pdf",
        headers=headers,
    )
