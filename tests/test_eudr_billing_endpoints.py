"""Tests for EUDR billing endpoints and webhook routing (#613).

Covers:
- GET /api/eudr/billing (status endpoint)
- GET /api/eudr/entitlement (entitlement check)
- GET /api/eudr/usage (usage dashboard)
- GET /api/eudr/summary-export (aggregated CSV export)
- POST /api/eudr/subscribe (Stripe checkout creation)
- Webhook routing for EUDR events
- _handle_eudr_event dispatch
- _extract_metered_sub_item
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import TEST_ORIGIN, make_test_request

_ALLOWED_ORIGIN = TEST_ORIGIN
_REQUIRE_AUTH = patch.dict("os.environ", {"REQUIRE_AUTH": "1"})


def _make_req(method="GET", url="/api/eudr/billing", body=None, headers=None, params=None):
    return make_test_request(
        url=url,
        method=method,
        body=body,
        headers=headers,
        params=params,
        origin=_ALLOWED_ORIGIN,
    )


# ---------------------------------------------------------------------------
# §1 — GET /api/eudr/billing
# ---------------------------------------------------------------------------


class TestEudrBillingStatus:
    @_REQUIRE_AUTH
    @patch(
        "treesight.security.eudr_billing.get_eudr_billing_status",
        return_value={
            "plan": "free_trial",
            "subscribed": False,
            "assessments_used": 0,
            "trial_remaining": 2,
            "period_parcels_used": 0,
            "included_parcels": 0,
            "overage_parcels": 0,
        },
    )
    @patch("treesight.security.orgs.get_user_org", return_value=None)
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_no_org_returns_empty_status(self, _auth, _org, _status):
        from blueprints.eudr import eudr_billing_status

        req = _make_req()
        resp = eudr_billing_status(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["plan"] == "free_trial"
        assert data["subscribed"] is False

    @_REQUIRE_AUTH
    @patch(
        "treesight.security.eudr_billing.get_eudr_billing_status",
        return_value={
            "plan": "eudr_pro",
            "subscribed": True,
            "assessments_used": 5,
            "trial_remaining": 0,
            "period_parcels_used": 3,
            "included_parcels": 10,
            "overage_parcels": 0,
        },
    )
    @patch(
        "treesight.security.orgs.get_user_org",
        return_value={"org_id": "org-1", "billing": {}},
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_with_org_returns_billing_data(self, _auth, _org, _status):
        from blueprints.eudr import eudr_billing_status

        req = _make_req()
        resp = eudr_billing_status(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["plan"] == "eudr_pro"
        assert data["subscribed"] is True
        assert data["period_parcels_used"] == 3

    def test_options_returns_cors(self):
        from blueprints.eudr import eudr_billing_status

        req = _make_req(method="OPTIONS")
        resp = eudr_billing_status(req)
        assert resp.status_code in (200, 204)

    @_REQUIRE_AUTH
    @patch("blueprints.eudr.check_auth", side_effect=ValueError("No token"))
    def test_unauthenticated_returns_401(self, _auth):
        from blueprints.eudr import eudr_billing_status

        req = make_test_request(url="/api/eudr/billing", auth_header=None, principal_user_id=None)
        resp = eudr_billing_status(req)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# §2 — GET /api/eudr/entitlement
# ---------------------------------------------------------------------------


class TestEudrEntitlement:
    @_REQUIRE_AUTH
    @patch("treesight.security.orgs.get_user_org", return_value=None)
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_no_org_returns_not_allowed(self, _auth, _org):
        from blueprints.eudr import eudr_entitlement_check

        req = _make_req(url="/api/eudr/entitlement")
        resp = eudr_entitlement_check(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["allowed"] is False
        assert data["reason"] == "no_org"

    @_REQUIRE_AUTH
    @patch(
        "treesight.security.eudr_billing.check_eudr_entitlement",
        return_value={"allowed": True, "reason": "subscribed"},
    )
    @patch(
        "treesight.security.orgs.get_user_org",
        return_value={"org_id": "org-1"},
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_subscribed_org_is_allowed(self, _auth, _org, _ent):
        from blueprints.eudr import eudr_entitlement_check

        req = _make_req(url="/api/eudr/entitlement")
        resp = eudr_entitlement_check(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["allowed"] is True

    @_REQUIRE_AUTH
    @patch(
        "treesight.security.eudr_billing.check_eudr_entitlement",
        return_value={"allowed": False, "reason": "trial_exhausted"},
    )
    @patch(
        "treesight.security.orgs.get_user_org",
        return_value={"org_id": "org-1"},
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_exhausted_trial_returns_not_allowed(self, _auth, _org, _ent):
        from blueprints.eudr import eudr_entitlement_check

        req = _make_req(url="/api/eudr/entitlement")
        resp = eudr_entitlement_check(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["allowed"] is False
        assert data["reason"] == "trial_exhausted"


# ---------------------------------------------------------------------------
# §2.1 — GET /api/eudr/usage
# ---------------------------------------------------------------------------


class TestEudrUsage:
    @_REQUIRE_AUTH
    @patch(
        "blueprints.eudr._eudr_usage_payload",
        return_value={
            "current": {
                "periodParcelsUsed": 47,
                "includedParcels": 50,
                "overageParcels": 0,
                "estimatedSpendGbp": 0.0,
                "nextTierThreshold": 100,
                "nextTierRateGbp": 2.5,
                "parcelsToNextTier": 53,
                "within20PercentOfNextTier": False,
            },
            "history": [
                {"month": "2026-01", "runs": 2, "parcels": 18, "overageRuns": 0},
                {"month": "2026-02", "runs": 3, "parcels": 22, "overageRuns": 1},
            ],
        },
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_returns_usage_payload(self, _auth, _payload):
        from blueprints.eudr import eudr_usage_status

        req = _make_req(url="/api/eudr/usage")
        resp = eudr_usage_status(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["current"]["periodParcelsUsed"] == 47
        assert data["history"][0]["month"] == "2026-01"

    @_REQUIRE_AUTH
    @patch("blueprints.eudr.check_auth", side_effect=ValueError("No token"))
    def test_unauthenticated_returns_401(self, _auth):
        from blueprints.eudr import eudr_usage_status

        req = make_test_request(url="/api/eudr/usage", auth_header=None, principal_user_id=None)
        resp = eudr_usage_status(req)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# §3 — POST /api/eudr/subscribe
# ---------------------------------------------------------------------------


class TestEudrSubscribe:
    @_REQUIRE_AUTH
    @patch("blueprints.eudr.check_auth", side_effect=ValueError("No token"))
    def test_unauthenticated_returns_401(self, _auth):
        from blueprints.eudr import eudr_subscribe

        req = make_test_request(
            url="/api/eudr/subscribe",
            method="POST",
            auth_header=None,
            principal_user_id=None,
        )
        resp = eudr_subscribe(req)
        assert resp.status_code == 401

    @_REQUIRE_AUTH
    @patch("treesight.security.orgs.get_user_org", return_value=None)
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_no_org_returns_404(self, _auth, _org):
        from blueprints.eudr import eudr_subscribe

        req = _make_req(method="POST", url="/api/eudr/subscribe")
        resp = eudr_subscribe(req)
        assert resp.status_code == 404

    @_REQUIRE_AUTH
    @patch(
        "treesight.security.eudr_billing.is_org_owner",
        return_value=False,
    )
    @patch(
        "treesight.security.orgs.get_user_org",
        return_value={"org_id": "org-1", "billing": {}},
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_non_owner_returns_403(self, _auth, _org, _owner):
        from blueprints.eudr import eudr_subscribe

        req = _make_req(method="POST", url="/api/eudr/subscribe")
        resp = eudr_subscribe(req)
        assert resp.status_code == 403

    @_REQUIRE_AUTH
    @patch(
        "treesight.security.eudr_billing.is_org_owner",
        return_value=True,
    )
    @patch(
        "treesight.security.orgs.get_user_org",
        return_value={"org_id": "org-1", "billing": {"eudr_status": "active"}},
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_already_subscribed_returns_409(self, _auth, _org, _owner):
        from blueprints.eudr import eudr_subscribe

        req = _make_req(method="POST", url="/api/eudr/subscribe")
        resp = eudr_subscribe(req)
        assert resp.status_code == 409

    @_REQUIRE_AUTH
    @patch("treesight.config.STRIPE_WEBHOOK_SECRET", "")
    @patch("treesight.config.STRIPE_API_KEY", "")
    @patch(
        "treesight.security.eudr_billing.is_org_owner",
        return_value=True,
    )
    @patch(
        "treesight.security.orgs.get_user_org",
        return_value={"org_id": "org-1", "billing": {}},
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "test-user"}, "test-user"))
    def test_stripe_not_configured_returns_503(self, _auth, _org, _owner):
        from blueprints.eudr import eudr_subscribe

        req = _make_req(method="POST", url="/api/eudr/subscribe")
        resp = eudr_subscribe(req)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# §4 — Webhook EUDR routing
# ---------------------------------------------------------------------------


class TestWebhookEudrRouting:
    def test_handle_eudr_event_checkout_completed(self):
        from blueprints.billing import _handle_eudr_event

        with (
            patch("treesight.security.eudr_billing.save_eudr_subscription") as mock_save,
            patch("blueprints.billing._extract_metered_sub_item", return_value="si_metered_123"),
        ):
            _handle_eudr_event(
                "checkout.session.completed",
                {"customer": "cus_eudr_1", "subscription": "sub_eudr_1"},
                {"org_id": "org-1", "product": "eudr"},
            )
            mock_save.assert_called_once_with(
                "org-1",
                tier="eudr_pro",
                status="active",
                stripe_customer_id="cus_eudr_1",
                stripe_subscription_id="sub_eudr_1",
                stripe_subscription_item_id="si_metered_123",
            )

    def test_handle_eudr_event_subscription_updated(self):
        from blueprints.billing import _handle_eudr_event

        with patch("treesight.security.eudr_billing.save_eudr_subscription") as mock_save:
            _handle_eudr_event(
                "customer.subscription.updated",
                {"customer": "cus_eudr_1", "id": "sub_eudr_1", "status": "active"},
                {"org_id": "org-1", "product": "eudr"},
            )
            mock_save.assert_called_once_with(
                "org-1",
                tier="eudr_pro",
                status="active",
                stripe_customer_id="cus_eudr_1",
                stripe_subscription_id="sub_eudr_1",
            )

    def test_handle_eudr_event_subscription_deleted(self):
        from blueprints.billing import _handle_eudr_event

        with patch("treesight.security.eudr_billing.save_eudr_subscription") as mock_save:
            _handle_eudr_event(
                "customer.subscription.deleted",
                {"customer": "cus_eudr_1", "id": "sub_eudr_1", "status": "canceled"},
                {"org_id": "org-1", "product": "eudr"},
            )
            mock_save.assert_called_once_with(
                "org-1",
                tier="eudr_pro",
                status="canceled",
                stripe_customer_id="cus_eudr_1",
                stripe_subscription_id="sub_eudr_1",
            )

    def test_handle_eudr_event_payment_failed(self):
        from blueprints.billing import _handle_eudr_event

        with patch("treesight.security.eudr_billing.save_eudr_subscription") as mock_save:
            _handle_eudr_event(
                "invoice.payment_failed",
                {"customer": "cus_eudr_1", "subscription": "sub_eudr_1"},
                {"org_id": "org-1", "product": "eudr"},
            )
            mock_save.assert_called_once_with(
                "org-1",
                tier="eudr_pro",
                status="past_due",
                stripe_customer_id="cus_eudr_1",
                stripe_subscription_id="sub_eudr_1",
            )

    def test_handle_eudr_event_no_org_id_skips(self):
        from blueprints.billing import _handle_eudr_event

        with patch("treesight.security.eudr_billing.save_eudr_subscription") as mock_save:
            _handle_eudr_event(
                "checkout.session.completed",
                {"customer": "cus_1", "subscription": "sub_1"},
                {"product": "eudr"},  # no org_id
            )
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# §5 — _extract_metered_sub_item
# ---------------------------------------------------------------------------


class TestExtractMeteredSubItem:
    def test_returns_metered_item_id(self):
        from blueprints.billing import _extract_metered_sub_item

        mock_sub = {
            "items": {
                "data": [
                    {"id": "si_base_1", "price": {"recurring": {"usage_type": "licensed"}}},
                    {"id": "si_meter_1", "price": {"recurring": {"usage_type": "metered"}}},
                ]
            }
        }
        with patch("blueprints.billing._get_stripe") as mock_stripe:
            mock_stripe.return_value.Subscription.retrieve.return_value = mock_sub
            result = _extract_metered_sub_item("sub_test_1")
        assert result == "si_meter_1"

    def test_returns_none_for_no_subscription_id(self):
        from blueprints.billing import _extract_metered_sub_item

        assert _extract_metered_sub_item(None) is None

    def test_returns_none_on_stripe_error(self):
        from blueprints.billing import _extract_metered_sub_item

        with patch("blueprints.billing._get_stripe") as mock_stripe:
            mock_stripe.return_value.Subscription.retrieve.side_effect = Exception("boom")
            result = _extract_metered_sub_item("sub_test_1")
        assert result is None


# ---------------------------------------------------------------------------
# §5 — GET /api/eudr/summary-export (#674)
# ---------------------------------------------------------------------------


class TestSummaryRowsFromManifest:
    """Unit tests for _summary_rows_from_manifest — pure helper."""

    def test_returns_row_per_aoi(self):
        from blueprints.eudr import _summary_rows_from_manifest

        manifest = {
            "per_aoi_enrichment": [
                {
                    "name": "Parcel A",
                    "area_ha": 10.5,
                    "center": {"lat": -1.5, "lon": 37.5},
                    "determination": {
                        "deforestation_free": True,
                        "confidence": "high",
                        "flags": [],
                    },
                }
            ]
        }
        rows = _summary_rows_from_manifest("run-001", "2026-01-15T10:00:00Z", manifest, None)
        assert len(rows) == 1
        row = rows[0]
        assert row["run_id"] == "run-001"
        assert row["parcel_name"] == "Parcel A"
        assert row["determination_status"] == "compliant"
        assert row["determination_confidence"] == "high"
        assert row["overridden"] == "no"
        assert row["note"] == ""

    def test_non_compliant_parcel(self):
        from blueprints.eudr import _summary_rows_from_manifest

        manifest = {
            "per_aoi_enrichment": [
                {
                    "name": "Parcel B",
                    "area_ha": 5.0,
                    "center": {"lat": 0.0, "lon": 0.0},
                    "determination": {
                        "deforestation_free": False,
                        "confidence": "high",
                        "flags": ["Vegetation loss 12.0% (1.5 ha) in 2024-Q1"],
                    },
                }
            ]
        }
        rows = _summary_rows_from_manifest("run-002", "2026-02-01T08:00:00Z", manifest, None)
        assert rows[0]["determination_status"] == "non_compliant"
        assert "Vegetation loss" in rows[0]["determination_flags"]

    def test_merges_override_and_note(self):
        from blueprints.eudr import _summary_rows_from_manifest

        manifest = {
            "per_aoi_enrichment": [
                {
                    "name": "Parcel C",
                    "area_ha": 3.0,
                    "center": {"lat": 1.0, "lon": 30.0},
                    "determination": {
                        "deforestation_free": False,
                        "confidence": "medium",
                        "flags": [],
                    },
                }
            ]
        }
        run_record = {
            "parcel_notes": {"0": "Verified on-site — no change visible"},
            "parcel_overrides": {
                "0": {"reason": "Ground-truthed as compliant after site visit", "reverted": False}
            },
        }
        rows = _summary_rows_from_manifest("run-003", "2026-03-01T00:00:00Z", manifest, run_record)
        assert rows[0]["overridden"] == "yes"
        assert "Ground-truthed" in rows[0]["override_reason"]
        assert "Verified" in rows[0]["note"]

    def test_empty_per_aoi_enrichment(self):
        from blueprints.eudr import _summary_rows_from_manifest

        rows = _summary_rows_from_manifest("run-x", "2026-01-01T00:00:00Z", {}, None)
        assert rows == []

    def test_reverted_override_not_marked_overridden(self):
        from blueprints.eudr import _summary_rows_from_manifest

        manifest = {
            "per_aoi_enrichment": [
                {
                    "name": "P",
                    "area_ha": 1.0,
                    "center": {},
                    "determination": {
                        "deforestation_free": False,
                        "confidence": "low",
                        "flags": [],
                    },
                }
            ]
        }
        run_record = {
            "parcel_overrides": {"0": {"reason": "Some reason", "reverted": True}},
        }
        rows = _summary_rows_from_manifest("run-r", "2026-01-01T00:00:00Z", manifest, run_record)
        assert rows[0]["overridden"] == "no"


class TestEudrSummaryExport:
    """GET /api/eudr/summary-export — aggregated org CSV."""

    @_REQUIRE_AUTH
    @patch("blueprints.eudr.check_auth", side_effect=ValueError("No token"))
    def test_unauthenticated_returns_401(self, _auth):
        from blueprints.eudr import _eudr_summary_export

        req = make_test_request(
            url="/api/eudr/summary-export", auth_header=None, principal_user_id=None
        )
        client = AsyncMock()
        resp = asyncio.run(_eudr_summary_export(req, client))
        assert resp.status_code == 401

    @_REQUIRE_AUTH
    @patch(
        "blueprints.eudr._fetch_org_run_records",
        return_value=[
            {"instance_id": "inst-001", "submitted_at": "2026-01-10T12:00:00Z"},
        ],
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "u1"}, "u1"))
    def test_returns_csv_with_header_and_rows(self, _auth, _runs):
        from blueprints.eudr import _eudr_summary_export

        fake_manifest = {
            "per_aoi_enrichment": [
                {
                    "name": "Parcel Alpha",
                    "area_ha": 8.0,
                    "center": {"lat": -2.0, "lon": 36.0},
                    "determination": {
                        "deforestation_free": True,
                        "confidence": "high",
                        "flags": [],
                    },
                }
            ]
        }
        mock_status = MagicMock()
        mock_status.output = {"enrichment_manifest": "enrichment/p/t/timelapse_payload.json"}
        client = AsyncMock()
        client.get_status = AsyncMock(return_value=mock_status)

        with patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls:
            mock_storage_cls.return_value.download_json.return_value = fake_manifest
            req = make_test_request(url="/api/eudr/summary-export")
            resp = asyncio.run(_eudr_summary_export(req, client))

        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        body = resp.get_body().decode()
        assert "run_id" in body  # header present
        assert "Parcel Alpha" in body
        assert "compliant" in body

    @_REQUIRE_AUTH
    @patch(
        "blueprints.eudr._fetch_org_run_records",
        return_value=[],
    )
    @patch("blueprints.eudr.check_auth", return_value=({"sub": "u1"}, "u1"))
    def test_no_runs_returns_404(self, _auth, _runs):
        from blueprints.eudr import _eudr_summary_export

        client = AsyncMock()
        req = make_test_request(url="/api/eudr/summary-export")
        resp = asyncio.run(_eudr_summary_export(req, client))
        assert resp.status_code == 404
