"""Data export endpoints — GeoJSON, CSV, and PDF download (M4 §4.6).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline/__init__.py module docstring for details.
"""

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
from blueprints.export.audit_pdf import build_eudr_audit_pdf
from blueprints.export.csv import _as_dict, _build_bulk_csv, _build_csv, _build_eudr_csv
from blueprints.export.geojson import _build_eudr_geojson, _build_geojson
from blueprints.export.pdf import _build_pdf
from treesight.security.rate_limit import get_client_ip, get_pipeline_limiter

bp = func.Blueprint()
logger = logging.getLogger(__name__)

_ALLOWED_FORMATS = {"geojson", "csv", "csv-bulk", "pdf", "eudr-geojson", "eudr-csv", "eudr-pdf"}


def _fetch_run_record_for_export(instance_id: str) -> "dict[str, Any] | None":
    """Fetch the Cosmos run record for annotation-enriched export formats.

    Returns ``None`` on any failure so callers can proceed without review data.
    """
    try:
        from blueprints.pipeline.history import get_run_record_by_instance_id

        return get_run_record_by_instance_id(instance_id)
    except Exception:
        logger.warning("export: could not fetch run record for %s", instance_id)
        return None


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

    if not get_pipeline_limiter().is_allowed(get_client_ip(req)):
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

    # Fetch the run record for annotation-enriched exports (best-effort; non-fatal).
    run_record: dict[str, Any] | None = None
    if fmt in {"eudr-csv", "eudr-pdf"}:
        run_record = _fetch_run_record_for_export(instance_id)

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
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}_eudr.geojson"'
        return func.HttpResponse(
            body,
            status_code=200,
            mimetype="application/geo+json",
            headers=headers,
        )

    if fmt == "eudr-csv":
        csv_body = _build_eudr_csv(manifest, run_record=run_record)
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}_eudr.csv"'
        return func.HttpResponse(
            csv_body,
            status_code=200,
            mimetype="text/csv",
            headers=headers,
        )

    if fmt == "eudr-pdf":
        parcel_reviews = _as_dict(run_record.get("parcel_reviews")) if run_record else None
        parcel_review_history = _as_dict(run_record.get("parcel_review_history")) if run_record else None
        pdf_bytes = build_eudr_audit_pdf(
            manifest,
            instance_id,
            parcel_reviews=parcel_reviews,
            parcel_review_history=parcel_review_history,
        )
        headers["Content-Disposition"] = f'attachment; filename="treesight_{instance_id}_eudr_report.pdf"'
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
