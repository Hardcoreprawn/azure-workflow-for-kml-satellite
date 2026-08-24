"""Unit tests for UploadTokenHandler.

Each step is tested in isolation by injecting mock callables directly through
the constructor — no module-level patching required.
"""

from __future__ import annotations

import json

import azure.functions as func

from treesight.submission.upload_token_handler import UploadTokenHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_req(body: dict | None = None) -> func.HttpRequest:
    raw = json.dumps(body or {}).encode()
    return func.HttpRequest(
        method="POST",
        url="https://example.com/api/upload/token",
        headers={"Content-Type": "application/json"},
        params={},
        body=raw,
    )


def _noop_error_response(status: int, message: str, *, req, **_) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
    )


def _make_handler(
    user_id: str = "user-1",
    body: dict | None = None,
    req: func.HttpRequest | None = None,
    *,
    active_org: dict | None = None,
    ensure_user_org_fn=None,
    reserve_run_or_error_fn=None,
    write_ticket_and_mint_sas_fn=None,
    finalize_run_fn=None,
    persist_submission_record_fn=None,
    requested_parcel_count_fn=None,
    detect_file_extension_fn=None,
    sanitise_submission_context_fn=None,
    resolve_provider_fn=None,
    build_run_record_fn=None,
) -> UploadTokenHandler:
    body = body or {}
    req = req or _make_req(body)

    def _default_ensure_user_org(req, user_id, active_org):
        return {"org_id": "org-1"}, None

    def _default_reserve(org_id, user_id, parcel_count, is_eudr, submission_id, req):
        return None

    def _default_write_ticket(*args, **kwargs):
        return "https://storage.example.com/blob?sas=fake", None

    def _default_finalize_run(*, org_id, instance_id, status):
        pass

    def _default_persist(submission_id, record, user_id):
        pass

    def _default_parcel_count(b):
        return 1

    def _default_detect(filename):
        return ".kml", "application/vnd.google-earth.kml+xml"

    def _default_sanitise(ctx):
        return ctx

    def _default_resolve_provider(body, ctx):
        return "provider-a"

    def _default_build_run_record(**kwargs):
        return {
            "submission_id": kwargs["submission_id"],
            "user_id": kwargs["user_id"],
            "status": "submitted",
        }

    return UploadTokenHandler(
        user_id=user_id,
        body=body,
        req=req,
        active_org=active_org,
        ensure_user_org_fn=ensure_user_org_fn or _default_ensure_user_org,
        reserve_run_or_error_fn=reserve_run_or_error_fn or _default_reserve,
        write_ticket_and_mint_sas_fn=write_ticket_and_mint_sas_fn or _default_write_ticket,
        finalize_run_fn=finalize_run_fn or _default_finalize_run,
        persist_submission_record_fn=persist_submission_record_fn or _default_persist,
        requested_parcel_count_fn=requested_parcel_count_fn or _default_parcel_count,
        detect_file_extension_fn=detect_file_extension_fn or _default_detect,
        sanitise_submission_context_fn=sanitise_submission_context_fn or _default_sanitise,
        resolve_provider_fn=resolve_provider_fn or _default_resolve_provider,
        build_run_record_fn=build_run_record_fn or _default_build_run_record,
        error_response_fn=_noop_error_response,
    )


# ---------------------------------------------------------------------------
# Happy-path: mint() returns payload on success
# ---------------------------------------------------------------------------


def test_mint_returns_payload_on_success():
    handler = _make_handler()
    payload, err = handler.mint()

    assert err is None
    assert payload is not None
    assert "submissionId" in payload
    assert "sasUrl" in payload
    assert "blobName" in payload
    assert "container" in payload
    assert "contentType" in payload
    assert "expiresMinutes" in payload
    assert "maxBytes" in payload


def test_mint_payload_includes_sas_url():
    handler = _make_handler(
        write_ticket_and_mint_sas_fn=lambda *a, **kw: ("https://storage.example.com/blob?sas=abc", None)
    )
    payload, err = handler.mint()

    assert err is None
    assert payload["sasUrl"] == "https://storage.example.com/blob?sas=abc"


# ---------------------------------------------------------------------------
# Step: _step_resolve_org
# ---------------------------------------------------------------------------


def test_returns_503_when_ensure_user_org_returns_error():
    error_resp = func.HttpResponse(b'{"error": "no org"}', status_code=503)

    handler = _make_handler(ensure_user_org_fn=lambda req, uid, org: (None, error_resp))
    payload, err = handler.mint()

    assert payload is None
    assert err is error_resp


def test_returns_503_when_ensure_user_org_returns_none_org_and_no_error():
    """Guard against the case where ensure_user_org returns (None, None) unexpectedly."""
    handler = _make_handler(ensure_user_org_fn=lambda req, uid, org: (None, None))
    payload, err = handler.mint()

    assert payload is None
    assert err is not None
    assert err.status_code == 503


def test_org_id_is_captured_from_ensure_user_org():
    captured = {}

    def _capture_org_id(org_id, user_id, parcel_count, is_eudr, submission_id, req):
        captured["org_id"] = org_id
        return None

    handler = _make_handler(
        ensure_user_org_fn=lambda req, uid, org: ({"org_id": "my-org-42"}, None),
        reserve_run_or_error_fn=_capture_org_id,
    )
    handler.mint()

    assert captured["org_id"] == "my-org-42"


# ---------------------------------------------------------------------------
# Step: _step_validate_parcel_count
# ---------------------------------------------------------------------------


def test_returns_400_when_parcel_count_is_zero():
    handler = _make_handler(requested_parcel_count_fn=lambda b: 0)
    payload, err = handler.mint()

    assert payload is None
    assert err is not None
    assert err.status_code == 400


def test_returns_400_when_parcel_count_is_negative():
    handler = _make_handler(requested_parcel_count_fn=lambda b: -1)
    payload, err = handler.mint()

    assert payload is None
    assert err is not None
    assert err.status_code == 400


# ---------------------------------------------------------------------------
# Step: _step_reserve_run
# ---------------------------------------------------------------------------


def test_returns_error_when_reservation_fails():
    reserve_err = func.HttpResponse(b'{"error": "quota exhausted"}', status_code=403)

    handler = _make_handler(reserve_run_or_error_fn=lambda org_id, uid, pc, is_eudr, sid, req: reserve_err)
    payload, err = handler.mint()

    assert payload is None
    assert err is reserve_err


def test_reserve_called_with_correct_user_id():
    captured = {}

    def _capture(org_id, user_id, parcel_count, is_eudr, submission_id, req):
        captured["user_id"] = user_id
        return None

    handler = _make_handler(user_id="user-abc", reserve_run_or_error_fn=_capture)
    handler.mint()

    assert captured["user_id"] == "user-abc"


def test_eudr_mode_true_propagated_to_reserve():
    captured = {}

    def _capture(org_id, user_id, parcel_count, is_eudr, submission_id, req):
        captured["is_eudr"] = is_eudr
        return None

    handler = _make_handler(body={"eudr_mode": True}, reserve_run_or_error_fn=_capture)
    handler.mint()

    assert captured["is_eudr"] is True


def test_eudr_mode_false_propagated_to_reserve():
    captured = {}

    def _capture(org_id, user_id, parcel_count, is_eudr, submission_id, req):
        captured["is_eudr"] = is_eudr
        return None

    handler = _make_handler(body={"eudr_mode": False}, reserve_run_or_error_fn=_capture)
    handler.mint()

    assert captured["is_eudr"] is False


# ---------------------------------------------------------------------------
# Step: _step_write_ticket_and_mint_sas / rollback on failure
# ---------------------------------------------------------------------------


def test_releases_reservation_when_sas_fails():
    """finalize_run_fn is called to release the reservation when SAS minting fails."""
    finalize_calls = []

    def _fake_finalize(*, org_id, instance_id, status):
        finalize_calls.append({"org_id": org_id, "instance_id": instance_id, "status": status})

    sas_error = func.HttpResponse(b'{"error": "storage down"}', status_code=502)
    handler = _make_handler(
        write_ticket_and_mint_sas_fn=lambda *a, **kw: (None, sas_error),
        finalize_run_fn=_fake_finalize,
    )
    payload, err = handler.mint()

    assert payload is None
    assert err is sas_error
    assert len(finalize_calls) == 1
    assert finalize_calls[0]["status"] == "failed"


def test_does_not_call_persist_when_sas_fails():
    persist_calls = []

    sas_error = func.HttpResponse(b'{"error": "storage down"}', status_code=502)
    handler = _make_handler(
        write_ticket_and_mint_sas_fn=lambda *a, **kw: (None, sas_error),
        persist_submission_record_fn=lambda *a: persist_calls.append(a),
    )
    handler.mint()

    assert persist_calls == [], "persist must not be called when SAS fails"


# ---------------------------------------------------------------------------
# Step: _step_persist_record
# ---------------------------------------------------------------------------


def test_persist_called_with_correct_user_id():
    persist_calls = []

    handler = _make_handler(
        user_id="user-xyz",
        persist_submission_record_fn=lambda sid, record, uid: persist_calls.append(uid),
    )
    handler.mint()

    assert persist_calls == ["user-xyz"]


def test_blob_name_uses_submission_id_and_kml_extension():
    """Default filename → .kml extension in blob path."""
    captured_blob_name = {}

    def _capture_write(body, user_id, submission_id, blob_name, ctx, req, **kw):
        captured_blob_name["blob_name"] = blob_name
        return "https://storage.example.com/blob?sas=fake", None

    handler = _make_handler(write_ticket_and_mint_sas_fn=_capture_write)
    payload, err = handler.mint()

    assert err is None
    assert captured_blob_name["blob_name"].startswith("analysis/")
    assert captured_blob_name["blob_name"].endswith(".kml")
    sid = payload["submissionId"]
    assert captured_blob_name["blob_name"] == f"analysis/{sid}.kml"


def test_blob_name_uses_kmz_extension_when_detected():
    captured_blob_name = {}

    def _capture_write(body, user_id, submission_id, blob_name, ctx, req, **kw):
        captured_blob_name["blob_name"] = blob_name
        return "https://storage.example.com/blob?sas=fake", None

    handler = _make_handler(
        detect_file_extension_fn=lambda filename: (".kmz", "application/vnd.google-earth.kmz"),
        write_ticket_and_mint_sas_fn=_capture_write,
    )
    _payload, err = handler.mint()

    assert err is None
    assert captured_blob_name["blob_name"].endswith(".kmz")
