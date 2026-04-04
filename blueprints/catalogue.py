"""Catalogue API endpoints (§3.3 — Catalogue browsing + time-series).

Provides read-only HTTP access to the temporal acquisition catalogue.
Data is written by the pipeline (see ``treesight.catalogue.repository``).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import logging
from datetime import datetime

import azure.functions as func

from blueprints._helpers import cors_headers, error_response, require_auth
from treesight.catalogue.contracts import (
    CatalogueEntryResponse,
    CatalogueListResponse,
)
from treesight.catalogue.repository import (
    get_entry,
    list_entries,
    list_entries_for_aoi,
    list_entries_for_run,
)

bp = func.Blueprint()

logger = logging.getLogger(__name__)

# Hard limits to prevent abuse
_MAX_LIMIT = 100
_MAX_OFFSET = 10_000


def _parse_int(value: str | None, default: int) -> int:
    """Safely parse an integer query param, falling back to *default*."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 date string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# ---- GET /api/catalogue ----


@bp.function_name("catalogue_list")
@bp.route(route="catalogue", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def catalogue_list(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """List catalogue entries with optional filters and pagination."""
    params = req.params

    limit = min(max(_parse_int(params.get("limit"), 20), 1), _MAX_LIMIT)
    offset = min(max(_parse_int(params.get("offset"), 0), 0), _MAX_OFFSET)
    sort = params.get("sort", "desc")
    if sort not in ("asc", "desc"):
        sort = "desc"

    entries, total = list_entries(
        user_id,
        aoi_name=params.get("aoiName"),
        status=params.get("status"),
        date_from=_parse_iso(params.get("dateFrom")),
        date_to=_parse_iso(params.get("dateTo")),
        provider=params.get("provider"),
        limit=limit,
        offset=offset,
        sort=sort,
    )

    body = CatalogueListResponse(
        entries=[CatalogueEntryResponse.from_model(e) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
        has_more=(offset + limit < total),
    )

    return func.HttpResponse(
        body.model_dump_json(by_alias=True),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---- GET /api/catalogue/{entryId} ----


@bp.function_name("catalogue_detail")
@bp.route(
    route="catalogue/{entryId}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def catalogue_detail(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """Get a single catalogue entry by id."""
    entry_id = req.route_params.get("entryId", "")
    if not entry_id:
        return error_response(400, "Missing entryId", req=req)

    entry = get_entry(entry_id, user_id)
    if entry is None:
        return error_response(404, "Catalogue entry not found", req=req)

    resp = CatalogueEntryResponse.from_model(entry)
    return func.HttpResponse(
        resp.model_dump_json(by_alias=True),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---- GET /api/catalogue/run/{runId} ----


@bp.function_name("catalogue_by_run")
@bp.route(
    route="catalogue/run/{runId}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def catalogue_by_run(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """List all catalogue entries for a specific pipeline run."""
    run_id = req.route_params.get("runId", "")
    if not run_id:
        return error_response(400, "Missing runId", req=req)

    entries = list_entries_for_run(user_id, run_id)

    body = CatalogueListResponse(
        entries=[CatalogueEntryResponse.from_model(e) for e in entries],
        total=len(entries),
        offset=0,
        limit=len(entries),
        has_more=False,
    )

    return func.HttpResponse(
        body.model_dump_json(by_alias=True),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---- GET /api/catalogue/aoi/{aoiName} ----


@bp.function_name("catalogue_by_aoi")
@bp.route(
    route="catalogue/aoi/{aoiName}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def catalogue_by_aoi(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """List acquisition history for a specific AOI (time-series)."""
    aoi_name = req.route_params.get("aoiName", "")
    if not aoi_name:
        return error_response(400, "Missing aoiName", req=req)

    limit = min(_parse_int(req.params.get("limit"), 20), _MAX_LIMIT)
    entries = list_entries_for_aoi(user_id, aoi_name, limit=limit)

    body = CatalogueListResponse(
        entries=[CatalogueEntryResponse.from_model(e) for e in entries],
        total=len(entries),
        offset=0,
        limit=limit,
        has_more=False,
    )

    return func.HttpResponse(
        body.model_dump_json(by_alias=True),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
