"""Tests for upload BFF endpoints (blueprints/upload.py).

Covers:
- POST /api/upload/token — SAS token minting
- GET  /api/upload/status/{submission_id} — pipeline status polling

Note: endpoints decorated with @require_auth must be called with just (req).
The decorator extracts auth_claims/user_id from X-MS-CLIENT-PRINCIPAL.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import azure.functions as func

from tests.conftest import TEST_ORIGIN, encode_test_principal

_REQUIRE_AUTH = patch.dict("os.environ", {"REQUIRE_AUTH": "1"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_req(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    params: dict[str, str] | None = None,
    route_params: dict[str, str] | None = None,
    principal_user_id: str | None = "test-user",
) -> func.HttpRequest:
    """Build an authenticated HttpRequest for upload blueprint."""
    h: dict[str, str] = {"Origin": TEST_ORIGIN}
    if principal_user_id:
        h["X-MS-CLIENT-PRINCIPAL"] = encode_test_principal(user_id=principal_user_id)

    raw_body = b""
    if body is not None:
        h["Content-Type"] = "application/json"
        raw_body = json.dumps(body).encode()

    return func.HttpRequest(
        method=method,
        url=url,
        headers=h,
        params=params or {},
        route_params=route_params or {},
        body=raw_body,
    )


# ===================================================================
# POST /api/upload/token
# ===================================================================


class TestUploadToken:
    """SAS token minting endpoint."""

    def setup_method(self):
        self._persist_patcher = patch("blueprints.upload._persist_submission_record")
        self._org_patcher = patch("blueprints.upload.get_user_org")
        self._reserve_patcher = patch("blueprints.upload.reserve_run")
        self.mock_persist = self._persist_patcher.start()
        self.mock_get_user_org = self._org_patcher.start()
        self.mock_reserve_run = self._reserve_patcher.start()

        # Set up default returns for new mocks
        self.mock_get_user_org.return_value = {"org_id": "org-1", "name": "Test Org"}
        self.mock_reserve_run.return_value = {"reserved_parcels": 1}  # MagicMock accepts any call

    def teardown_method(self):
        self._persist_patcher.stop()
        self._reserve_patcher.stop()
        self._org_patcher.stop()

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_returns_sas_url_for_authenticated_user(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert "submissionId" in data
        assert "sasUrl" in data
        assert data["sasUrl"].startswith("https://teststorage.blob.core.windows.net/")
        assert "blobName" in data
        assert data["container"] == "kml-input"
        assert data["expiresMinutes"] > 0
        assert data["maxBytes"] == 10_485_760

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_writes_ticket_blob(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_blob_client = MagicMock()
        mock_bsc.return_value.get_blob_client.return_value = mock_blob_client
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {"submission_context": {"feature_count": 5, "aoi_count": 3}, "parcel_count": 4}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        mock_blob_client.upload_blob.assert_called_once()
        ticket_data = json.loads(mock_blob_client.upload_blob.call_args[0][0])
        assert ticket_data["user_id"] == "test-user"
        assert "created_at" in ticket_data
        assert ticket_data["submission_context"]["feature_count"] == 5
        assert ticket_data["parcel_count"] == 4

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_rejects_non_integer_parcel_count(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req(
            "/api/upload/token",
            method="POST",
            body={"parcel_count": 1.5},
        )
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 400

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_rejects_boolean_parcel_count(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req(
            "/api/upload/token",
            method="POST",
            body={"parcel_count": True},
        )
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 400

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_sas_uses_user_delegation_key(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_delegation_key = MagicMock()
        mock_bsc.return_value.get_user_delegation_key.return_value = mock_delegation_key
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            upload_token(req)

        call_kwargs = mock_gen_sas.call_args[1]
        assert call_kwargs["user_delegation_key"] is mock_delegation_key
        assert call_kwargs["permission"].create is True
        assert call_kwargs["permission"].write is True
        assert call_kwargs["permission"].read is False

    @_REQUIRE_AUTH
    def test_rejects_unauthenticated_request(self):
        from blueprints.upload import upload_token

        req = _make_req("/api/upload/token", method="POST", principal_user_id=None)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 401

    @patch("blueprints.upload.get_blob_service_client")
    def test_returns_503_when_storage_not_configured(self, mock_bsc):
        from blueprints.upload import upload_token

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", ""):
            resp = upload_token(req)

        assert resp.status_code == 503

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_delegation_key_failure_returns_502(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.side_effect = RuntimeError("timeout")

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 502

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_sanitises_submission_context(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_blob_client = MagicMock()
        mock_bsc.return_value.get_blob_client.return_value = mock_blob_client
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {
            "submission_context": {
                "feature_count": 5,
                "evil_field": "should be stripped",
                "total_area_ha": -999,  # negative — should be stripped
            }
        }
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            upload_token(req)

        ticket_data = json.loads(mock_blob_client.upload_blob.call_args[0][0])
        ctx = ticket_data.get("submission_context", {})
        assert "evil_field" not in ctx
        assert ctx["feature_count"] == 5
        assert "total_area_ha" not in ctx  # negative rejected

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_consumes_quota_on_success(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        # Check that reserve_run was called with org_id, user_id, parcel_count, is_eudr, instance_id
        self.mock_reserve_run.assert_called_once()
        call_kwargs = self.mock_reserve_run.call_args.kwargs
        assert call_kwargs["is_eudr"] is False  # Default: not EUDR mode

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_auto_creates_org_for_unaffiliated_user(self, mock_bsc, mock_gen_sas):
        """Users without an org get a personal org auto-created on first submission."""
        from blueprints.upload import upload_token

        auto_org = {"org_id": "auto-org-1", "name": "Test User's Organisation"}
        # First call returns None (no org yet); second call (post-creation verification)
        # returns the newly created org.
        self.mock_get_user_org.side_effect = [None, auto_org]
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        with (
            patch("blueprints.upload.create_org") as mock_create,
            patch(
                "treesight.security.users.get_user",
                return_value={"email": "t@example.com", "display_name": "Test User"},
            ),
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
        ):
            req = _make_req("/api/upload/token", method="POST")
            resp = upload_token(req)

        assert resp.status_code == 200
        mock_create.assert_called_once_with(
            "test-user",
            name="Test User's Organisation",
            email="t@example.com",
            org_id="personal-test-user",
        )

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_cosmos_query_lag_falls_back_to_created_org(self, mock_bsc, mock_gen_sas):
        """If get_user_org returns None after create_org (Cosmos query consistency lag),
        the org returned by create_org is used as a fallback so the request succeeds."""
        from blueprints.upload import upload_token

        new_org = {"org_id": "new-org-1", "name": "Test User's Organisation"}
        # Both get_user_org calls return None (simulates cross-partition query lag).
        # The fallback to create_org's return value should carry the request through.
        self.mock_get_user_org.side_effect = [None, None]
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        with (
            patch("blueprints.upload.create_org", return_value=new_org),
            patch(
                "treesight.security.users.get_user",
                return_value={"display_name": "Test User", "email": "t@example.com"},
            ),
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
        ):
            req = _make_req("/api/upload/token", method="POST")
            resp = upload_token(req)

        # Should succeed despite query lag — fallback to new_org is used.
        assert resp.status_code == 200
        # Reserve was called with the fallback org_id from create_org, not an empty/wrong value.
        self.mock_reserve_run.assert_called_once()
        assert self.mock_reserve_run.call_args.kwargs["org_id"] == "new-org-1"

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_concurrent_first_submission_uses_same_personal_org_id(self, mock_bsc, mock_gen_sas):
        """Concurrent first submissions use deterministic personal org id.

        Simulate eventual-consistency lag where both requests fail to re-read org
        membership immediately after auto-create. Both fallback paths must still
        reserve against the same org_id.
        """
        from blueprints.upload import upload_token

        get_user_org_calls = {"count": 0}
        get_user_org_lock = threading.Lock()

        def _get_user_org_side_effect(_user_id):
            with get_user_org_lock:
                get_user_org_calls["count"] += 1
                # First four calls map to: two initial lookups + two post-create
                # lookups. Return None to simulate eventual-consistency lag.
                if get_user_org_calls["count"] <= 4:
                    return None
            return {"org_id": "personal-test-user", "name": "Test User's Organisation"}

        self.mock_get_user_org.side_effect = _get_user_org_side_effect
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        def _create_org_side_effect(user_id, *, name, email, org_id):
            return {"org_id": org_id, "name": name}

        with (
            patch(
                "blueprints.upload.create_org", side_effect=_create_org_side_effect
            ) as mock_create,
            patch(
                "treesight.security.users.get_user",
                return_value={"display_name": "Test User", "email": "t@example.com"},
            ),
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
        ):
            req_1 = _make_req("/api/upload/token", method="POST")
            req_2 = _make_req("/api/upload/token", method="POST")
            barrier = threading.Barrier(2)

            def _invoke(req):
                barrier.wait(timeout=2)
                return upload_token(req)

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_1 = executor.submit(_invoke, req_1)
                future_2 = executor.submit(_invoke, req_2)
                resp_1 = future_1.result(timeout=5)
                resp_2 = future_2.result(timeout=5)

        assert resp_1.status_code == 200
        assert resp_2.status_code == 200
        assert mock_create.call_count == 2
        assert all(
            call.kwargs.get("org_id") == "personal-test-user" for call in mock_create.call_args_list
        )
        assert self.mock_reserve_run.call_count == 2
        reserved_org_ids = [call.kwargs["org_id"] for call in self.mock_reserve_run.call_args_list]
        assert sorted(reserved_org_ids) == ["personal-test-user", "personal-test-user"]

    def test_auto_create_org_failure_returns_503(self):
        """If org auto-creation fails, return 503 rather than 403."""
        from blueprints.upload import upload_token

        self.mock_get_user_org.return_value = None

        with (
            patch("blueprints.upload.create_org", side_effect=RuntimeError("cosmos down")),
            patch(
                "treesight.security.users.get_user",
                return_value={},
            ),
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
            patch("time.sleep", return_value=None),
        ):
            req = _make_req("/api/upload/token", method="POST")
            resp = upload_token(req)

        assert resp.status_code == 503

    def test_returns_403_when_quota_exhausted(self):
        from blueprints.upload import upload_token
        from treesight.billing.accounting import QuotaExhaustedError

        self.mock_reserve_run.side_effect = QuotaExhaustedError("Org quota exhausted")

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 403

    @patch("blueprints.upload.get_blob_service_client")
    def test_refunds_quota_on_ticket_failure(self, mock_bsc):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_blob_client.return_value.upload_blob.side_effect = RuntimeError(
            "storage down"
        )

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            with patch("treesight.billing.accounting.finalize_run") as mock_finalize:
                resp = upload_token(req)

        assert resp.status_code == 502
        # Check that finalize_run was called to refund the reservation
        mock_finalize.assert_called_once()
        call_args = mock_finalize.call_args
        assert call_args.kwargs["status"] == "failed"

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_persists_submission_record(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {"submission_context": {"feature_count": 3, "aoi_count": 2}}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        self.mock_persist.assert_called_once()
        call_args = self.mock_persist.call_args
        submission_id = call_args[0][0]
        record = call_args[0][1]
        assert record["user_id"] == "test-user"
        assert record["submission_id"] == submission_id
        assert record["instance_id"] == submission_id
        assert record["status"] == "submitted"
        assert record["feature_count"] == 3
        assert record["aoi_count"] == 2

    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_true_in_ticket(self, mock_bsc, mock_gen_sas, mock_org):
        from blueprints.upload import upload_token

        mock_blob_client = MagicMock()
        mock_bsc.return_value.get_blob_client.return_value = mock_blob_client
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {"eudr_mode": True}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        ticket_data = json.loads(mock_blob_client.upload_blob.call_args[0][0])
        assert ticket_data["eudr_mode"] is True
        assert "imagery_filters" in ticket_data
        assert "2020-12-31" in ticket_data["imagery_filters"]["date_start"]

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_false_not_in_ticket(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_blob_client = MagicMock()
        mock_bsc.return_value.get_blob_client.return_value = mock_blob_client
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {"eudr_mode": False}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            upload_token(req)

        ticket_data = json.loads(mock_blob_client.upload_blob.call_args[0][0])
        assert "eudr_mode" not in ticket_data
        assert "imagery_filters" not in ticket_data

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_non_bool_rejected(self, mock_bsc, mock_gen_sas):
        from blueprints.upload import upload_token

        mock_blob_client = MagicMock()
        mock_bsc.return_value.get_blob_client.return_value = mock_blob_client
        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {"eudr_mode": "yes"}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            upload_token(req)

        ticket_data = json.loads(mock_blob_client.upload_blob.call_args[0][0])
        assert "eudr_mode" not in ticket_data

    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_stored_in_run_record(self, mock_bsc, mock_gen_sas, mock_org):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        body = {"eudr_mode": True}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            upload_token(req)

        record = self.mock_persist.call_args[0][1]
        assert record["eudr_mode"] is True

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_kml_filename_produces_kml_blob_and_content_type(self, mock_bsc, mock_gen_sas):
        """A .kml filename produces a .kml blob name and passes KML content-type to SAS token."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"filename": "parcels.kml"})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["blobName"].endswith(".kml")
        assert data["contentType"] == "application/vnd.google-earth.kml+xml"
        call_kwargs = mock_gen_sas.call_args[1]
        assert call_kwargs["content_type"] == "application/vnd.google-earth.kml+xml"

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_kmz_filename_produces_kmz_blob_and_content_type(self, mock_bsc, mock_gen_sas):
        """A .kmz filename produces a .kmz blob name and KMZ content-type (fixes #768)."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"filename": "parcels.kmz"})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["blobName"].endswith(".kmz")
        assert data["contentType"] == "application/vnd.google-earth.kmz"
        call_kwargs = mock_gen_sas.call_args[1]
        assert call_kwargs["content_type"] == "application/vnd.google-earth.kmz"

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_no_filename_defaults_to_kml(self, mock_bsc, mock_gen_sas):
        """When no filename is provided, defaults to .kml extension."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST")
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["blobName"].endswith(".kml")
        call_kwargs = mock_gen_sas.call_args[1]
        assert call_kwargs["content_type"] == "application/vnd.google-earth.kml+xml"

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_unknown_extension_defaults_to_kml(self, mock_bsc, mock_gen_sas):
        """An unrecognised extension falls back to .kml for safety."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"filename": "parcels.shp"})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["blobName"].endswith(".kml")

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_case_insensitive_kmz_extension(self, mock_bsc, mock_gen_sas):
        """Extension detection is case-insensitive (.KMZ treated as KMZ)."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"filename": "parcels.KMZ"})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["blobName"].endswith(".kmz")


# ===================================================================
# Single parcel gate enforcement on upload/token
# ===================================================================


class TestUploadTokenSingleGate:
    """Server-side parcel gate is enforced only through reserve_run."""

    def setup_method(self):
        self._org_patcher = patch("blueprints.upload.get_user_org")
        self._reserve_patcher = patch("blueprints.upload.reserve_run")
        self._persist_patcher = patch("blueprints.upload._persist_submission_record")
        self.mock_get_user_org = self._org_patcher.start()
        self.mock_reserve_run = self._reserve_patcher.start()
        self.mock_persist = self._persist_patcher.start()

        # Default return values
        self.mock_get_user_org.return_value = {"org_id": "org-1", "name": "Test Org"}
        self.mock_reserve_run.return_value = {"reserved_parcels": 1}

    def teardown_method(self):
        self._persist_patcher.stop()
        self._reserve_patcher.stop()
        self._org_patcher.stop()

    def test_auto_creates_org_when_none_and_proceeds(self):
        """Users without an org get one auto-created; submission then succeeds."""
        from blueprints.upload import upload_token

        auto_org = {"org_id": "new-org-1", "name": "Test User's Organisation"}
        # First call: no org. Second call (post-creation verification): org exists.
        self.mock_get_user_org.side_effect = [None, auto_org]
        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with (
            patch("blueprints.upload.create_org"),
            patch(
                "treesight.security.users.get_user",
                return_value={"display_name": "Test User", "email": "t@example.com"},
            ),
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
            patch("blueprints.upload.generate_blob_sas", return_value="sv=2024&sig=fakesig"),
            patch("blueprints.upload.get_blob_service_client") as mock_bsc,
        ):
            mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
            resp = upload_token(req)

        assert resp.status_code == 200
        self.mock_reserve_run.assert_called_once()

    def test_returns_503_when_auto_create_org_fails(self):
        """If org auto-creation fails, 503 is returned and reserve_run is not called."""
        from blueprints.upload import upload_token

        self.mock_get_user_org.return_value = None
        req = _make_req("/api/upload/token", method="POST")
        with (
            patch("blueprints.upload.create_org", side_effect=RuntimeError("cosmos down")),
            patch("treesight.security.users.get_user", return_value={}),
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
            patch("time.sleep", return_value=None),
        ):
            resp = upload_token(req)

        assert resp.status_code == 503
        self.mock_reserve_run.assert_not_called()

    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    def test_eudr_mode_marks_reservation_as_eudr(self, mock_org):
        from blueprints.upload import upload_token

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with (
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
            patch("blueprints.upload.generate_blob_sas", return_value="sv=2024&sig=fakesig"),
            patch("blueprints.upload.get_blob_service_client") as mock_bsc,
        ):
            mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
            resp = upload_token(req)

        assert resp.status_code == 200
        self.mock_reserve_run.assert_called_once()
        assert self.mock_reserve_run.call_args.kwargs["is_eudr"] is True

    @patch("treesight.security.quota.consume_quota")
    @patch("treesight.security.eudr_billing.consume_eudr_trial")
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    def test_eudr_mode_does_not_use_legacy_quota_writers(
        self, mock_org, mock_consume_trial, mock_consume_quota
    ):
        """EUDR upload reservation must be org-pooled and avoid legacy double-debit paths."""
        from blueprints.upload import upload_token

        req = _make_req(
            "/api/upload/token",
            method="POST",
            body={"eudr_mode": True, "parcel_count": 2},
        )
        with (
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
            patch("blueprints.upload.generate_blob_sas", return_value="sv=2024&sig=fakesig"),
            patch("blueprints.upload.get_blob_service_client") as mock_bsc,
        ):
            mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
            resp = upload_token(req)

        assert resp.status_code == 200
        self.mock_reserve_run.assert_called_once()
        assert self.mock_reserve_run.call_args.kwargs["is_eudr"] is True
        assert self.mock_reserve_run.call_args.kwargs["parcel_count"] == 2
        mock_consume_trial.assert_not_called()
        mock_consume_quota.assert_not_called()

    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_non_eudr_mode_marks_reservation_as_non_eudr(self, mock_bsc, mock_gen_sas, mock_org):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": False})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        self.mock_reserve_run.assert_called_once()
        assert self.mock_reserve_run.call_args.kwargs["is_eudr"] is False

    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    def test_eudr_mode_rejected_when_parcel_pool_rejects(self, mock_org):
        from blueprints.upload import upload_token
        from treesight.billing.accounting import MemberCapExceededError

        self.mock_reserve_run.side_effect = MemberCapExceededError("Member cap exceeded")

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 403


# ===================================================================
# GET /api/upload/status/{submission_id}
# ===================================================================


class TestUploadStatus:
    """Pipeline status polling endpoint."""

    _VALID_SID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    @patch("blueprints.upload._cosmos_mod")
    def test_returns_status_from_cosmos(self, mock_cosmos):
        from blueprints.upload import upload_status

        mock_cosmos.query_items.return_value = [
            {
                "submission_id": self._VALID_SID,
                "status": "running",
                "submitted_at": "2026-04-10T10:00:00Z",
                "feature_count": 5,
            }
        ]

        req = _make_req(
            f"/api/upload/status/{self._VALID_SID}",
            route_params={"submission_id": self._VALID_SID},
        )
        resp = upload_status(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["submissionId"] == self._VALID_SID
        assert data["status"] == "running"

    @patch("blueprints.upload._cosmos_mod")
    def test_returns_pending_when_not_found(self, mock_cosmos):
        from blueprints.upload import upload_status

        mock_cosmos.query_items.return_value = []

        req = _make_req(
            f"/api/upload/status/{self._VALID_SID}",
            route_params={"submission_id": self._VALID_SID},
        )
        resp = upload_status(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["status"] == "pending"

    def test_rejects_invalid_uuid(self):
        from blueprints.upload import upload_status

        req = _make_req(
            "/api/upload/status/not-a-uuid",
            route_params={"submission_id": "not-a-uuid"},
        )
        resp = upload_status(req)

        assert resp.status_code == 400

    def test_rejects_empty_submission_id(self):
        from blueprints.upload import upload_status

        req = _make_req(
            "/api/upload/status/",
            route_params={"submission_id": ""},
        )
        resp = upload_status(req)

        assert resp.status_code == 400

    @_REQUIRE_AUTH
    def test_rejects_unauthenticated_request(self):
        from blueprints.upload import upload_status

        req = _make_req(
            f"/api/upload/status/{self._VALID_SID}",
            route_params={"submission_id": self._VALID_SID},
            principal_user_id=None,
        )
        resp = upload_status(req)

        assert resp.status_code == 401
