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

_ALLOWED_FORMATS = {"geojson", "csv"}


# ---------------------------------------------------------------------------
# Shared: fetch enrichment manifest for a given pipeline instance
# ---------------------------------------------------------------------------


async def _fetch_manifest(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> tuple[dict[str, Any] | None, func.HttpResponse | None]:
    """Return (manifest_dict, None) on success or (None, error_response) on failure."""
    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return None, error_response(401, str(exc), req=req)

    instance_id = req.route_params.get("instance_id", "")
    if not instance_id:
        return None, error_response(400, "instance_id required", req=req)

    status = await client.get_status(instance_id)
    if not status or not status.output:
        return None, error_response(404, "Pipeline not found or not complete", req=req)

    # Ownership check: verify calling user owns this pipeline instance
    input_data = status.input if isinstance(status.input, dict) else {}
    owner = input_data.get("user_id", "")
    if owner and user_id != "anonymous" and owner != user_id:
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

    Supported formats: ``geojson``, ``csv``.
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

    # CSV
    csv_body = _build_csv(manifest)
    headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}.csv"'
    return func.HttpResponse(
        csv_body,
        status_code=200,
        mimetype="text/csv",
        headers=headers,
    )
