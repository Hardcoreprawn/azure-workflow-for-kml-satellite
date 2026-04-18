"""Tests for EUDR billing endpoints and webhook routing (#613).

Covers:
- GET /api/eudr/billing (status endpoint)
- GET /api/eudr/entitlement (entitlement check)
- POST /api/eudr/subscribe (Stripe checkout creation)
- Webhook routing for EUDR events
- _handle_eudr_event dispatch
- _extract_metered_sub_item
"""

from __future__ import annotations

import json
from unittest.mock import patch

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
