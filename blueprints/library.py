"""User library API — KML and analysis management (M4.4).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json

import azure.functions as func

from blueprints._helpers import (
    cors_headers,
    error_response,
    require_auth,
    sanitise,
)
from treesight.constants import MAX_KML_FILE_SIZE_BYTES
from treesight.storage.library import UserLibrary

bp = func.Blueprint()


# --- GET /api/library ---


@bp.route(route="library", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def get_library(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Return the authenticated user's full KML and analysis library."""
    try:
        lib = UserLibrary(user_id)
        data = lib.get_library()
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    return func.HttpResponse(
        json.dumps(data),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# --- POST /api/library/kmls ---


@bp.route(
    route="library/kmls",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def upload_kml(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Upload a KML to the user's library.

    Accepts either:
    - JSON body: {"name": "...", "kml_content": "<kml>..."}
    - Multipart form: file=<kml file>, name=<optional>
    """
    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object", req=req)

    name = sanitise(body.get("name", ""))
    kml_content = body.get("kml_content", "")

    if not isinstance(kml_content, str) or not kml_content.strip():
        return error_response(400, "kml_content is required", req=req)

    kml_bytes = kml_content.encode("utf-8")
    if len(kml_bytes) > MAX_KML_FILE_SIZE_BYTES:
        return error_response(
            413,
            f"KML exceeds {MAX_KML_FILE_SIZE_BYTES // 1_048_576} MiB limit",
            req=req,
        )

    # Extract basic KML metadata
    polygon_count = kml_content.count("<Polygon")
    if not name:
        # Try to extract name from KML <Document><name> or <Placemark><name>
        import re

        m = re.search(r"<name>([^<]+)</name>", kml_content)
        name = sanitise(m.group(1)) if m else "Untitled KML"

    try:
        lib = UserLibrary(user_id)
        record = lib.add_kml(name, kml_bytes, polygon_count=polygon_count)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    return func.HttpResponse(
        json.dumps(record),
        status_code=201,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# --- GET /api/library/kmls/{kml_id} ---


@bp.route(
    route="library/kmls/{kml_id}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def get_kml(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Download a specific KML file from the user's library."""
    kml_id = req.route_params.get("kml_id", "")
    if not kml_id:
        return error_response(400, "kml_id is required", req=req)

    try:
        lib = UserLibrary(user_id)
        kml_bytes = lib.get_kml(kml_id)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)
    except FileNotFoundError:
        return error_response(404, "KML not found", req=req)

    return func.HttpResponse(
        kml_bytes,
        status_code=200,
        mimetype="application/vnd.google-earth.kml+xml",
        headers=cors_headers(req),
    )


# --- DELETE /api/library/kmls/{kml_id} ---


@bp.route(
    route="library/kmls/{kml_id}",
    methods=["DELETE", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def delete_kml(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Delete a KML and its linked analyses from the user's library."""
    kml_id = req.route_params.get("kml_id", "")
    if not kml_id:
        return error_response(400, "kml_id is required", req=req)

    try:
        lib = UserLibrary(user_id)
        found = lib.delete_kml(kml_id)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    if not found:
        return error_response(404, "KML not found", req=req)

    return func.HttpResponse(
        json.dumps({"deleted": kml_id}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# --- POST /api/library/analyses ---


@bp.route(
    route="library/analyses",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def save_analysis(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Save a completed pipeline analysis to the user's library."""
    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object", req=req)

    kml_id = body.get("kml_id", "")
    instance_id = body.get("instance_id", "")

    if not kml_id or not instance_id:
        return error_response(400, "kml_id and instance_id are required", req=req)

    kml_name = sanitise(body.get("kml_name", ""))
    aoi_name = sanitise(body.get("aoi_name", ""))
    status = body.get("status", "completed")

    if status not in ("running", "completed", "failed"):
        return error_response(400, "Invalid status", req=req)

    try:
        lib = UserLibrary(user_id)
        record = lib.add_analysis(
            kml_id=kml_id,
            kml_name=kml_name or "Untitled",
            instance_id=instance_id,
            aoi_name=aoi_name,
            status=status,
        )
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    return func.HttpResponse(
        json.dumps(record),
        status_code=201,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# --- PATCH /api/library/analyses/{analysis_id} ---


@bp.route(
    route="library/analyses/{analysis_id}",
    methods=["PATCH", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def update_analysis(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Update the status of a library analysis (e.g. running → completed)."""
    analysis_id = req.route_params.get("analysis_id", "")
    if not analysis_id:
        return error_response(400, "analysis_id is required", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    status = body.get("status", "")
    if status and status not in ("running", "completed", "failed"):
        return error_response(400, "Invalid status", req=req)

    extra = {}
    if body.get("frame_count"):
        extra["frame_count"] = int(body["frame_count"])
    if body.get("summary"):
        extra["summary"] = sanitise(body["summary"])[:500]

    if not status and not extra:
        return error_response(400, "Nothing to update", req=req)

    try:
        lib = UserLibrary(user_id)
        if status:
            found = lib.update_analysis_status(analysis_id, status, **extra)
        else:
            # Summary-only update (no status change)
            found = lib.update_analysis_extra(analysis_id, **extra)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    if not found:
        return error_response(404, "Analysis not found", req=req)

    return func.HttpResponse(
        json.dumps({"updated": analysis_id}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# --- DELETE /api/library/analyses/{analysis_id} ---


@bp.route(
    route="library/analyses/{analysis_id}",
    methods=["DELETE", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def delete_analysis(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Remove an analysis from the user's library."""
    analysis_id = req.route_params.get("analysis_id", "")
    if not analysis_id:
        return error_response(400, "analysis_id is required", req=req)

    try:
        lib = UserLibrary(user_id)
        found = lib.delete_analysis(analysis_id)
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    if not found:
        return error_response(404, "Analysis not found", req=req)

    return func.HttpResponse(
        json.dumps({"deleted": analysis_id}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ==========================================================================
# GDPR Data Rights (Articles 15, 17, 20 — UK GDPR / DPA 2018)
# ==========================================================================


# --- GET /api/account/export ---


@bp.route(
    route="account/export",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def export_user_data(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """Export all user data as JSON (Article 20 — right to data portability)."""
    try:
        lib = UserLibrary(user_id)
        data = lib.export_all_data()
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    payload = json.dumps(data, indent=2, default=str)
    headers = cors_headers(req)
    headers["Content-Disposition"] = 'attachment; filename="treesight-data-export.json"'

    return func.HttpResponse(
        payload,
        status_code=200,
        mimetype="application/json",
        headers=headers,
    )


# --- DELETE /api/account ---


@bp.route(
    route="account",
    methods=["DELETE", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def delete_account(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Delete all user data (Article 17 — right to erasure / right to be forgotten).

    This permanently removes all KMLs, analyses, quota records, and the
    library manifest for the authenticated user.  This action cannot be undone.
    """
    # Require explicit confirmation header to prevent accidental deletion
    confirm = req.headers.get("X-Confirm-Delete", "")
    if confirm != "permanently-delete-all-my-data":
        return error_response(
            400,
            "Set header X-Confirm-Delete: permanently-delete-all-my-data to confirm",
            req=req,
        )

    try:
        lib = UserLibrary(user_id)
        result = lib.delete_all_data()
    except ValueError as exc:
        return error_response(403, str(exc), req=req)

    return func.HttpResponse(
        json.dumps(
            {
                "status": "deleted",
                "detail": "All user data has been permanently erased",
                **result,
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
