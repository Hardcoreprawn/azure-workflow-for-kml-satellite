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

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response
from treesight.constants import DEFAULT_OUTPUT_CONTAINER

bp = func.Blueprint()
logger = logging.getLogger(__name__)

_ALLOWED_FORMATS = {"geojson", "csv", "pdf"}


# ---------------------------------------------------------------------------
# Shared: fetch enrichment manifest for a given pipeline instance
# ---------------------------------------------------------------------------


async def _fetch_manifest(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> tuple[dict[str, Any] | None, func.HttpResponse | None]:
    """Return (manifest_dict, None) on success or (None, error_response) on failure."""
    try:
        check_auth(req)
    except ValueError as exc:
        return None, error_response(401, str(exc), req=req)

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return None, error_response(400, "instance_id required", req=req)

    status = await client.get_status(instance_id)
    if not status or not status.output:
        return None, error_response(404, "Pipeline not found or not complete", req=req)

    output = status.output if isinstance(status.output, dict) else {}
    manifest_path = output.get("enrichment_manifest") or output.get("enrichmentManifest")
    if not manifest_path:
        return None, error_response(404, "No enrichment data for this pipeline run", req=req)

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        data = storage.download_json(DEFAULT_OUTPUT_CONTAINER, manifest_path)
    except Exception:
        logger.exception("Failed to download enrichment manifest")
        return None, error_response(404, "Enrichment manifest not found in storage", req=req)

    return data, None


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
        key = (sc.get("season", ""), sc.get("year_b", 0))
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
    daily_temps = weather_daily.get("temperature_2m_mean", []) if weather_daily else []
    daily_precip = weather_daily.get("precipitation_sum", []) if weather_daily else []

    for i, frame in enumerate(frame_plan):
        ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None

        # Simple weather aggregation for the frame's date range
        mean_temp = None
        total_precip = None
        if daily_dates:
            start, end = frame.get("start", ""), frame.get("end", "")
            temps_in_range = []
            precip_in_range = []
            for j, d in enumerate(daily_dates):
                if start <= d <= end:
                    if j < len(daily_temps) and daily_temps[j] is not None:
                        temps_in_range.append(daily_temps[j])
                    if j < len(daily_precip) and daily_precip[j] is not None:
                        precip_in_range.append(daily_precip[j])
            if temps_in_range:
                mean_temp = round(sum(temps_in_range) / len(temps_in_range), 1)
            if precip_in_range:
                total_precip = round(sum(precip_in_range), 1)

        # Change detection delta
        change = change_lookup.get((frame.get("season", ""), frame.get("year", 0)))
        ndvi_delta = change.get("ndvi_mean_delta") if change else None

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


# ---------------------------------------------------------------------------
# PDF export (EUDR audit report)
# ---------------------------------------------------------------------------


def _pdf_header(pdf: Any, manifest: dict[str, Any], instance_id: str) -> None:
    """Write title and metadata section of the PDF."""
    eudr_mode = manifest.get("eudr_mode", False)
    center = manifest.get("center", {})

    pdf.set_font("Helvetica", "B", 18)
    title = "EUDR Due-Diligence Report" if eudr_mode else "TreeSight Analysis Report"
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


def _pdf_eudr_section(pdf: Any, manifest: dict[str, Any]) -> None:
    """Write EUDR compliance summary section."""
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "EUDR Compliance Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    cutoff = manifest.get("eudr_date_start", "2021-01-01")
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
        pdf.cell(
            0,
            6,
            f"ESA WorldCover: data available (item: {wc.get('item_id', 'N/A')})",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    wdpa = manifest.get("wdpa", {})
    if wdpa.get("checked"):
        status = "Yes — protected area overlap detected" if wdpa.get("is_protected") else "No"
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
                f"  - {pa.get('name', '')} ({pa.get('designation', '')})",
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
        ndvi_val = f"{ndvi['mean']:.3f}" if ndvi and ndvi.get("mean") is not None else "\u2014"
        row_data = [
            frame.get("label", "")[:18],
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
        months = weather_monthly.get("months", [])
        temps = weather_monthly.get("avg_temp", [])
        precips = weather_monthly.get("total_precip", [])
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

    Supported formats: ``geojson``, ``csv``, ``pdf``.
    Returns the file as a downloadable attachment.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    fmt = (req.route_params.get("format") or "").lower()
    if fmt not in _ALLOWED_FORMATS:
        return error_response(
            400,
            f"Unsupported format '{fmt}'. Use one of: {', '.join(sorted(_ALLOWED_FORMATS))}",
            req=req,
        )

    manifest, err = await _fetch_manifest(req, client)
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

    # PDF
    pdf_bytes = _build_pdf(manifest, instance_id)
    headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}.pdf"'
    return func.HttpResponse(
        pdf_bytes,
        status_code=200,
        mimetype="application/pdf",
        headers=headers,
    )
