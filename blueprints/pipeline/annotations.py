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
