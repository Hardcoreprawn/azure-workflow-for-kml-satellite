"""Parcel annotation and determination override endpoints.

User-initiated writes are authorised at the application layer:
- The Function App's managed identity / connection string provides infrastructure
  access to Cosmos DB.
- ``assert_run_write_access`` enforces that the authenticated user is the run
  owner or an org member before any mutation is applied.
- Notes and overrides are stored as fields on the Cosmos ``runs`` document
  (not in blob storage) so they can be queried and updated atomically.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
import logging
import re
from datetime import UTC, datetime

import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response
from treesight.security.rate_limit import get_client_ip, pipeline_limiter
from treesight.storage import cosmos
from treesight.storage import cosmos as _cosmos_mod

from . import bp
from .history import assert_run_write_access, get_run_record_by_instance_id

logger = logging.getLogger(__name__)

_MAX_NOTE_LENGTH = 2_000
_MIN_OVERRIDE_REASON_LENGTH = 20
_MAX_OVERRIDE_REASON_LENGTH = 1_000
_MIN_REVIEW_NOTE_LENGTH = 20  # required when override=True
_MAX_REVIEW_NOTE_LENGTH = 1_000

# Allow printable Unicode text; strip ASCII/Unicode control chars and common
# prompt-injection delimiters to reduce injection risk in exported documents.
_SAFE_TEXT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028\u2029]")


def _sanitise_text(text: str, max_length: int) -> str:
    """Strip control characters and truncate to *max_length* codepoints."""
    return _SAFE_TEXT_RE.sub("", text.strip())[:max_length]


def _check_standard_guards(
    req: func.HttpRequest,
    feature: str,
) -> tuple[str, func.HttpResponse | None]:
    """Run auth + rate-limit + Cosmos-availability guards shared by both endpoints.

    Returns ``(user_id, None)`` on success, or ``("", error_response)`` on failure.
    """
    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return "", error_response(401, str(exc), req=req)

    if user_id == "anonymous":
        return "", error_response(401, "Authentication required", req=req)

    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return "", error_response(429, "Rate limit exceeded — try again later", req=req)

    if not _cosmos_mod.cosmos_available():
        return "", error_response(503, f"{feature} requires Cosmos DB — not configured", req=req)

    return user_id, None


def _fetch_and_authorise(
    instance_id: str,
    user_id: str,
    req: func.HttpRequest,
) -> tuple[dict | None, func.HttpResponse | None]:
    """Fetch the run record and assert write access.

    Returns ``(run_record, None)`` on success or ``(None, error_response)``.
    """
    run = get_run_record_by_instance_id(instance_id)
    if not run:
        return None, error_response(404, "Run not found", req=req)
    try:
        assert_run_write_access(run, user_id)
    except ValueError as exc:
        return None, error_response(403, str(exc), req=req)
    return run, None


# ---------------------------------------------------------------------------
# POST /api/analysis/notes
# ---------------------------------------------------------------------------


@bp.route(
    route="analysis/notes",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def analysis_notes(req: func.HttpRequest) -> func.HttpResponse:
    """Save or delete a note on a specific parcel within a completed run.

    Body: ``{instance_id, parcel_key, note}``
    An empty ``note`` value deletes the existing note for that parcel.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    user_id, err = _check_standard_guards(req, "Notes")
    if err:
        return err

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    instance_id = str(body.get("instance_id", "")).strip()
    parcel_key = str(body.get("parcel_key", "")).strip()
    note_text = str(body.get("note", "")).strip()

    if not instance_id or not parcel_key:
        return error_response(400, "instance_id and parcel_key are required", req=req)

    if len(note_text) > _MAX_NOTE_LENGTH:
        return error_response(400, f"Note exceeds {_MAX_NOTE_LENGTH} characters", req=req)

    note_text = _sanitise_text(note_text, _MAX_NOTE_LENGTH)

    run, err = _fetch_and_authorise(instance_id, user_id, req)
    if err:
        return err
    assert run is not None  # _fetch_and_authorise guarantees this

    parcel_notes = run.get("parcel_notes") or {}  # type: ignore[union-attr]
    if not isinstance(parcel_notes, dict):
        parcel_notes = {}

    now = datetime.now(UTC).isoformat()
    if note_text:
        parcel_notes[parcel_key] = {"text": note_text, "author_id": user_id, "updated_at": now}
    else:
        parcel_notes.pop(parcel_key, None)

    run["parcel_notes"] = parcel_notes  # type: ignore[index]

    try:
        cosmos.upsert_item("runs", run)
    except Exception:
        logger.exception("Note save failed instance=%s user=%s", instance_id, user_id)
        return error_response(500, "Failed to save note — try again", req=req)

    return func.HttpResponse(
        json.dumps({"saved": True, "parcel_key": parcel_key}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# POST /api/analysis/override
# ---------------------------------------------------------------------------


@bp.route(
    route="analysis/override",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def analysis_override(req: func.HttpRequest) -> func.HttpResponse:
    """Record or revert a human determination override on a specific parcel.

    Body: ``{instance_id, parcel_key, reason, revert}``
    ``revert=true`` removes an existing override, restoring the algorithmic
    determination.  When creating an override, ``reason`` is required and
    must be at least 20 characters so the audit trail is meaningful.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    user_id, err = _check_standard_guards(req, "Overrides")
    if err:
        return err

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    instance_id = str(body.get("instance_id", "")).strip()
    parcel_key = str(body.get("parcel_key", "")).strip()
    reason = str(body.get("reason", "")).strip()
    revert = bool(body.get("revert", False))

    if not instance_id or not parcel_key:
        return error_response(400, "instance_id and parcel_key are required", req=req)

    if not revert and len(reason) < _MIN_OVERRIDE_REASON_LENGTH:
        return error_response(
            400,
            f"Override reason must be at least {_MIN_OVERRIDE_REASON_LENGTH} characters",
            req=req,
        )

    if not revert:
        reason = _sanitise_text(reason, _MAX_OVERRIDE_REASON_LENGTH)

    run, err = _fetch_and_authorise(instance_id, user_id, req)
    if err:
        return err
    assert run is not None  # _fetch_and_authorise guarantees this

    parcel_overrides = run.get("parcel_overrides") or {}  # type: ignore[union-attr]
    if not isinstance(parcel_overrides, dict):
        parcel_overrides = {}

    now = datetime.now(UTC).isoformat()
    if revert:
        parcel_overrides.pop(parcel_key, None)
    else:
        parcel_overrides[parcel_key] = {
            "reason": reason,
            "overridden_by": user_id,
            "overridden_at": now,
            "override_determination": "compliant",
        }

    run["parcel_overrides"] = parcel_overrides  # type: ignore[index]

    try:
        cosmos.upsert_item("runs", run)
    except Exception:
        logger.exception("Override save failed instance=%s user=%s", instance_id, user_id)
        return error_response(500, "Failed to save override — try again", req=req)

    return func.HttpResponse(
        json.dumps({"saved": True, "parcel_key": parcel_key, "reverted": revert}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# GET /api/analysis/{instance_id}/review
# ---------------------------------------------------------------------------


@bp.route(
    route="analysis/{instance_id}/review",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def analysis_review_list(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/analysis/{instance_id}/review — fetch all parcel reviews for a run.

    Returns ``{instance_id, reviews}`` where ``reviews`` is a dict keyed by
    string AOI index (e.g. ``"0"``, ``"1"``).  Each value holds the stored
    ``{override, note, reviewed_by, reviewed_at}`` record.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    user_id, err = _check_standard_guards(req, "Reviews")
    if err:
        return err

    instance_id = req.route_params.get("instance_id", "").strip()
    if not instance_id:
        return error_response(400, "instance_id is required", req=req)

    run, err = _fetch_and_authorise(instance_id, user_id, req)
    if err:
        return err
    assert run is not None  # _fetch_and_authorise guarantees this

    reviews = run.get("parcel_reviews") or {}
    if not isinstance(reviews, dict):
        reviews = {}

    return func.HttpResponse(
        json.dumps({"instance_id": instance_id, "reviews": reviews}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# POST /api/analysis/{instance_id}/parcel/{aoi_index}/review
# ---------------------------------------------------------------------------


def _parse_review_body(
    req: func.HttpRequest,
) -> "tuple[bool, str, func.HttpResponse | None]":
    """Parse and validate the review POST body.

    Returns ``(override, note, None)`` on success, or ``(False, '', error_response)``
    on validation failure so the caller can return the error immediately.
    """
    try:
        body = req.get_json()
    except ValueError:
        return False, "", error_response(400, "Invalid JSON body", req=req)

    override = bool(body.get("override", False))
    note = str(body.get("note", "")).strip()

    if override and len(note) < _MIN_REVIEW_NOTE_LENGTH:
        return (
            False,
            "",
            error_response(
                400,
                f"Note must be at least {_MIN_REVIEW_NOTE_LENGTH} characters"
                " when marking as reviewed",
                req=req,
            ),
        )
    if not note:
        return False, "", error_response(400, "Note is required", req=req)
    if len(note) > _MAX_REVIEW_NOTE_LENGTH:
        return (
            False,
            "",
            error_response(
                400,
                f"Note exceeds {_MAX_REVIEW_NOTE_LENGTH} characters",
                req=req,
            ),
        )

    return override, _sanitise_text(note, _MAX_REVIEW_NOTE_LENGTH), None


@bp.route(
    route="analysis/{instance_id}/parcel/{aoi_index}/review",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def analysis_parcel_review(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/analysis/{instance_id}/parcel/{aoi_index}/review — save a human review.

    Body: ``{override, note}``

    ``override=true`` marks the parcel as compliant with explanation and requires
    at least :data:`_MIN_REVIEW_NOTE_LENGTH` characters in ``note``.
    ``override=false`` saves an informational note without changing the compliance
    determination.  Either way the note is persisted with the reviewer identity and
    timestamp so it can appear in exported audit PDFs.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    user_id, err = _check_standard_guards(req, "Reviews")
    if err:
        return err

    instance_id = req.route_params.get("instance_id", "").strip()
    aoi_index_str = req.route_params.get("aoi_index", "").strip()

    if not instance_id or not aoi_index_str:
        return error_response(400, "instance_id and aoi_index are required", req=req)

    try:
        aoi_index = int(aoi_index_str)
    except ValueError:
        return error_response(400, "aoi_index must be a non-negative integer", req=req)

    if aoi_index < 0:
        return error_response(400, "aoi_index must be a non-negative integer", req=req)

    override, note, body_err = _parse_review_body(req)
    if body_err:
        return body_err

    run, err = _fetch_and_authorise(instance_id, user_id, req)
    if err:
        return err
    assert run is not None  # _fetch_and_authorise guarantees this

    parcel_reviews = run.get("parcel_reviews") or {}  # type: ignore[union-attr]
    if not isinstance(parcel_reviews, dict):
        parcel_reviews = {}

    parcel_key = str(aoi_index)
    now = datetime.now(UTC).isoformat()
    parcel_reviews[parcel_key] = {
        "override": override,
        "note": note,
        "reviewed_by": user_id,
        "reviewed_at": now,
    }

    run["parcel_reviews"] = parcel_reviews  # type: ignore[index]

    try:
        cosmos.upsert_item("runs", run)
    except Exception:
        logger.exception("Review save failed instance=%s user=%s", instance_id, user_id)
        return error_response(500, "Failed to save review — try again", req=req)

    return func.HttpResponse(
        json.dumps({"saved": True, "aoi_index": aoi_index, "instance_id": instance_id}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )
