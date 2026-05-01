"""Tests for upload BFF endpoints (blueprints/upload.py).

Covers:
- POST /api/upload/token — SAS token minting
- GET  /api/upload/status/{submission_id} — pipeline status polling

Note: endpoints decorated with @require_auth must be called with just (req).
The decorator extracts auth_claims/user_id from X-MS-CLIENT-PRINCIPAL.
"""

from __future__ import annotations

import json
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
        self._quota_patcher = patch("blueprints.upload.consume_quota")
        self._release_patcher = patch("blueprints.upload.release_quota")
        self._persist_patcher = patch("blueprints.upload._persist_submission_record")
        self.mock_consume_quota = self._quota_patcher.start()
        self.mock_release_quota = self._release_patcher.start()
        self.mock_persist = self._persist_patcher.start()

    def teardown_method(self):
        self._persist_patcher.stop()
        self._release_patcher.stop()
        self._quota_patcher.stop()

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

        body = {"submission_context": {"feature_count": 5, "aoi_count": 3}}
        req = _make_req("/api/upload/token", method="POST", body=body)
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        mock_blob_client.upload_blob.assert_called_once()
        ticket_data = json.loads(mock_blob_client.upload_blob.call_args[0][0])
        assert ticket_data["user_id"] == "test-user"
        assert "created_at" in ticket_data
        assert ticket_data["submission_context"]["feature_count"] == 5

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
        self.mock_consume_quota.assert_called_once_with("test-user")

    def test_returns_403_when_quota_exhausted(self):
        from blueprints.upload import upload_token

        self.mock_consume_quota.side_effect = ValueError("Quota exhausted")

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
            resp = upload_token(req)

        assert resp.status_code == 502
        self.mock_release_quota.assert_called_once()
        call_args = self.mock_release_quota.call_args
        assert call_args[0][0] == "test-user"
        assert call_args[1].get("instance_id")  # submission_id passed for idempotency

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

    @patch("blueprints.upload.consume_eudr_trial")
    @patch(
        "blueprints.upload.check_eudr_entitlement",
        return_value={"allowed": True, "reason": "free_trial"},
    )
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_true_in_ticket(self, mock_bsc, mock_gen_sas, mock_org, mock_ent, mock_trial):
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

    @patch("blueprints.upload.consume_eudr_trial")
    @patch(
        "blueprints.upload.check_eudr_entitlement",
        return_value={"allowed": True, "reason": "free_trial"},
    )
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_stored_in_run_record(
        self, mock_bsc, mock_gen_sas, mock_org, mock_ent, mock_trial
    ):
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
        """A .kml filename produces a .kml blob name and passes KML content-type to the SAS token."""
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
        """A .kmz filename produces a .kmz blob name and passes KMZ content-type to the SAS token."""
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
# EUDR entitlement enforcement on upload/token
# ===================================================================


class TestUploadTokenEudrEntitlement:
    """Server-side EUDR entitlement gate (#664)."""

    def setup_method(self):
        self._quota_patcher = patch("blueprints.upload.consume_quota")
        self._release_patcher = patch("blueprints.upload.release_quota")
        self._persist_patcher = patch("blueprints.upload._persist_submission_record")
        self.mock_consume_quota = self._quota_patcher.start()
        self.mock_release_quota = self._release_patcher.start()
        self.mock_persist = self._persist_patcher.start()

    def teardown_method(self):
        self._persist_patcher.stop()
        self._release_patcher.stop()
        self._quota_patcher.stop()

    @patch("blueprints.upload.get_user_org", return_value=None)
    def test_eudr_mode_rejects_user_without_org(self, mock_org):
        from blueprints.upload import upload_token

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 403
        data = json.loads(resp.get_body())
        assert "org" in data["error"].lower()
        self.mock_consume_quota.assert_not_called()

    @patch(
        "blueprints.upload.check_eudr_entitlement",
        return_value={"allowed": False, "reason": "subscription_required"},
    )
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    def test_eudr_mode_rejects_when_entitlement_denied(self, mock_org, mock_ent):
        from blueprints.upload import upload_token

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 403
        data = json.loads(resp.get_body())
        assert "subscription" in data["error"].lower() or "entitlement" in data["error"].lower()
        self.mock_consume_quota.assert_not_called()

    @patch("blueprints.upload.consume_eudr_trial")
    @patch(
        "blueprints.upload.check_eudr_entitlement",
        return_value={"allowed": True, "reason": "free_trial"},
    )
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_consumes_trial_when_free(
        self, mock_bsc, mock_gen_sas, mock_org, mock_ent, mock_consume_trial
    ):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        mock_consume_trial.assert_called_once_with("org-1")
        self.mock_consume_quota.assert_called_once()

    @patch("blueprints.upload.consume_eudr_trial")
    @patch(
        "blueprints.upload.check_eudr_entitlement",
        return_value={"allowed": True, "reason": "subscription"},
    )
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_skips_trial_when_subscribed(
        self, mock_bsc, mock_gen_sas, mock_org, mock_ent, mock_consume_trial
    ):
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200
        mock_consume_trial.assert_not_called()
        self.mock_consume_quota.assert_called_once()

    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_non_eudr_mode_skips_entitlement_check(self, mock_bsc, mock_gen_sas):
        """Non-EUDR submissions should not check EUDR entitlement."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": False})
        with patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"):
            resp = upload_token(req)

        assert resp.status_code == 200

    @patch("blueprints.upload.consume_eudr_trial")
    @patch(
        "blueprints.upload.check_eudr_entitlement",
        return_value={"allowed": True, "reason": "free_trial"},
    )
    @patch("blueprints.upload.get_user_org", return_value={"org_id": "org-1", "name": "Test Org"})
    @patch("blueprints.upload.generate_blob_sas")
    @patch("blueprints.upload.get_blob_service_client")
    def test_eudr_mode_refunds_quota_on_trial_consume_failure(
        self, mock_bsc, mock_gen_sas, mock_org, mock_ent, mock_consume_trial
    ):
        """If trial consumption fails after quota was consumed, quota is refunded."""
        from blueprints.upload import upload_token

        mock_bsc.return_value.get_user_delegation_key.return_value = MagicMock()
        mock_gen_sas.return_value = "sv=2024&sig=fakesig"
        mock_consume_trial.side_effect = ValueError("Trial exhausted")

        req = _make_req("/api/upload/token", method="POST", body={"eudr_mode": True})
        with (
            patch("blueprints.upload._safe_release_quota") as mock_release,
            patch("blueprints.upload.STORAGE_ACCOUNT_NAME", "teststorage"),
        ):
            resp = upload_token(req)

        assert resp.status_code == 403
        mock_release.assert_called_once()


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
