"""Tests for EUDR per-parcel metered Stripe billing (#613).

EUDR billing is org-scoped:
- 2 lifetime free assessments per org (no card required)
- £49/month base subscription with 10 included parcels
- Graduated metered overage: £3 (11-100), £2.50 (101-500), £1.80 (501+)
- Only org owners can subscribe
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from treesight.constants import EUDR_FREE_ASSESSMENTS, EUDR_INCLUDED_PARCELS

_UPSERT_ITEM = "treesight.storage.cosmos.upsert_item"
_GET_ORG = "treesight.security.orgs.get_org"


# ---------------------------------------------------------------------------
# §1 — Free trial (org-scoped)
# ---------------------------------------------------------------------------


class TestEudrFreeTrial:
    """The free trial gives 2 lifetime parcel assessments per org."""

    @patch(_GET_ORG)
    def test_new_org_has_trial_remaining(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_trial_remaining

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 0,
        }
        assert get_eudr_trial_remaining("org-1") == EUDR_FREE_ASSESSMENTS

    @patch(_GET_ORG)
    def test_one_used_has_one_remaining(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_trial_remaining

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 1,
        }
        assert get_eudr_trial_remaining("org-1") == 1

    @patch(_GET_ORG)
    def test_two_used_has_zero_remaining(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_trial_remaining

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 2,
        }
        assert get_eudr_trial_remaining("org-1") == 0

    @patch(_GET_ORG)
    def test_missing_counter_treated_as_zero(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_trial_remaining

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
        }
        assert get_eudr_trial_remaining("org-1") == EUDR_FREE_ASSESSMENTS

    @patch(_GET_ORG)
    def test_nonexistent_org_returns_zero(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_trial_remaining

        mock_get_org.return_value = None
        assert get_eudr_trial_remaining("missing") == 0


class TestConsumeEudrTrial:
    """Consuming a trial assessment increments the org counter."""

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_consumes_one_assessment(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import consume_eudr_trial

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 0,
        }
        consume_eudr_trial("org-1")
        doc = mock_upsert.call_args[0][1]
        assert doc["eudr_assessments_used"] == 1

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_raises_when_trial_exhausted(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import consume_eudr_trial

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": EUDR_FREE_ASSESSMENTS,
        }
        with pytest.raises(ValueError, match=r"free.*exhausted"):
            consume_eudr_trial("org-1")
        mock_upsert.assert_not_called()

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_raises_for_nonexistent_org(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import consume_eudr_trial

        mock_get_org.return_value = None
        with pytest.raises(ValueError, match="not found"):
            consume_eudr_trial("missing")


# ---------------------------------------------------------------------------
# §2 — Assessment entitlement check
# ---------------------------------------------------------------------------


class TestCheckEudrEntitlement:
    """Check whether an org can submit an EUDR assessment."""

    @patch(_GET_ORG)
    def test_free_trial_allows_assessment(self, mock_get_org):
        from treesight.security.eudr_billing import check_eudr_entitlement

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 0,
        }
        result = check_eudr_entitlement("org-1")
        assert result["allowed"] is True
        assert result["reason"] == "free_trial"

    @patch(_GET_ORG)
    def test_trial_exhausted_no_subscription_blocked(self, mock_get_org):
        from treesight.security.eudr_billing import check_eudr_entitlement

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": EUDR_FREE_ASSESSMENTS,
            "billing": {},
        }
        result = check_eudr_entitlement("org-1")
        assert result["allowed"] is False
        assert result["reason"] == "subscription_required"

    @patch(_GET_ORG)
    def test_active_subscription_allows_assessment(self, mock_get_org):
        from treesight.security.eudr_billing import check_eudr_entitlement

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": EUDR_FREE_ASSESSMENTS,
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
                "stripe_subscription_id": "sub_123",
            },
        }
        result = check_eudr_entitlement("org-1")
        assert result["allowed"] is True
        assert result["reason"] == "subscription"

    @patch(_GET_ORG)
    def test_cancelled_subscription_blocked(self, mock_get_org):
        from treesight.security.eudr_billing import check_eudr_entitlement

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": EUDR_FREE_ASSESSMENTS,
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "canceled",
            },
        }
        result = check_eudr_entitlement("org-1")
        assert result["allowed"] is False
        assert result["reason"] == "subscription_required"


# ---------------------------------------------------------------------------
# §3 — EUDR billing status
# ---------------------------------------------------------------------------


class TestGetEudrBillingStatus:
    """Billing status payload for the EUDR frontend."""

    @patch(_GET_ORG)
    def test_free_trial_status(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_billing_status

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 1,
        }
        status = get_eudr_billing_status("org-1")
        assert status["plan"] == "free_trial"
        assert status["assessments_used"] == 1
        assert status["trial_remaining"] == 1
        assert status["subscribed"] is False

    @patch(_GET_ORG)
    def test_subscribed_status(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_billing_status

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 5,
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
                "eudr_period_parcels": 7,
                "stripe_customer_id": "cus_abc",
            },
        }
        status = get_eudr_billing_status("org-1")
        assert status["plan"] == "eudr_pro"
        assert status["subscribed"] is True
        assert status["period_parcels_used"] == 7
        assert status["included_parcels"] == EUDR_INCLUDED_PARCELS
        assert status["overage_parcels"] == 0

    @patch(_GET_ORG)
    def test_overage_calculation(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_billing_status

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 15,
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
                "eudr_period_parcels": 15,
            },
        }
        status = get_eudr_billing_status("org-1")
        assert status["period_parcels_used"] == 15
        assert status["overage_parcels"] == 5

    @patch(_GET_ORG)
    def test_nonexistent_org_returns_empty(self, mock_get_org):
        from treesight.security.eudr_billing import get_eudr_billing_status

        mock_get_org.return_value = None
        status = get_eudr_billing_status("missing")
        assert status["plan"] == "none"
        assert status["subscribed"] is False


# ---------------------------------------------------------------------------
# §4 — Save EUDR subscription on org
# ---------------------------------------------------------------------------


class TestSaveEudrSubscription:
    """Saving an EUDR subscription updates the org billing fields."""

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_saves_subscription_fields(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import save_eudr_subscription

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "billing": {},
        }
        save_eudr_subscription(
            "org-1",
            tier="eudr_pro",
            status="active",
            stripe_customer_id="cus_abc",
            stripe_subscription_id="sub_123",
        )
        doc = mock_upsert.call_args[0][1]
        assert doc["billing"]["eudr_tier"] == "eudr_pro"
        assert doc["billing"]["eudr_status"] == "active"
        assert doc["billing"]["stripe_customer_id"] == "cus_abc"
        assert doc["billing"]["stripe_subscription_id"] == "sub_123"

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_raises_for_nonexistent_org(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import save_eudr_subscription

        mock_get_org.return_value = None
        with pytest.raises(ValueError, match="not found"):
            save_eudr_subscription("missing", tier="eudr_pro", status="active")


# ---------------------------------------------------------------------------
# §5 — Record EUDR usage (parcel count)
# ---------------------------------------------------------------------------


class TestRecordEudrUsage:
    """Record parcel usage after successful enrichment completion."""

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_increments_period_parcels(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import record_eudr_usage

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
                "eudr_period_parcels": 5,
                "stripe_subscription_item_id": "si_123",
            },
        }
        record_eudr_usage("org-1", parcel_count=3)
        doc = mock_upsert.call_args[0][1]
        assert doc["billing"]["eudr_period_parcels"] == 8

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_increments_lifetime_counter(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import record_eudr_usage

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 2,
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
                "eudr_period_parcels": 0,
            },
        }
        record_eudr_usage("org-1", parcel_count=2)
        doc = mock_upsert.call_args[0][1]
        assert doc["eudr_assessments_used"] == 4

    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_free_trial_usage_increments_lifetime_only(self, mock_get_org, mock_upsert):
        from treesight.security.eudr_billing import record_eudr_usage

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "eudr_assessments_used": 0,
            "billing": {},
        }
        record_eudr_usage("org-1", parcel_count=1)
        doc = mock_upsert.call_args[0][1]
        assert doc["eudr_assessments_used"] == 1
        # No period parcels tracked for free trial
        assert doc["billing"].get("eudr_period_parcels", 0) == 0


# ---------------------------------------------------------------------------
# §6 — EUDR Stripe usage reporting
# ---------------------------------------------------------------------------


class TestReportEudrStripeUsage:
    """Metered usage reported to Stripe after parcel enrichment completes."""

    @patch("treesight.security.payment_provider.get_payment_provider")
    @patch(_UPSERT_ITEM)
    @patch(_GET_ORG)
    def test_reports_metered_usage_to_stripe(self, mock_get_org, mock_upsert, mock_provider):
        from treesight.security.eudr_billing import report_eudr_stripe_usage

        provider = MagicMock()
        provider.report_usage.return_value = "ur_123"
        mock_provider.return_value = provider

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
                "stripe_subscription_item_id": "si_123",
            },
        }

        result = report_eudr_stripe_usage(
            "org-1",
            parcel_count=3,
            idempotency_key="run-abc",
        )
        assert result == "ur_123"
        provider.report_usage.assert_called_once_with(
            user_id="org-1",
            subscription_item_id="si_123",
            quantity=3,
            idempotency_key="run-abc",
        )

    @patch("treesight.security.payment_provider.get_payment_provider")
    @patch(_GET_ORG)
    def test_skips_reporting_for_free_trial(self, mock_get_org, mock_provider):
        from treesight.security.eudr_billing import report_eudr_stripe_usage

        provider = MagicMock()
        mock_provider.return_value = provider

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "billing": {},
        }

        result = report_eudr_stripe_usage(
            "org-1",
            parcel_count=1,
            idempotency_key="run-abc",
        )
        assert result is None
        provider.report_usage.assert_not_called()

    @patch("treesight.security.payment_provider.get_payment_provider")
    @patch(_GET_ORG)
    def test_skips_reporting_without_subscription_item(self, mock_get_org, mock_provider):
        from treesight.security.eudr_billing import report_eudr_stripe_usage

        provider = MagicMock()
        mock_provider.return_value = provider

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "billing": {
                "eudr_tier": "eudr_pro",
                "eudr_status": "active",
            },
        }

        result = report_eudr_stripe_usage(
            "org-1",
            parcel_count=1,
            idempotency_key="run-abc",
        )
        assert result is None
        provider.report_usage.assert_not_called()


# ---------------------------------------------------------------------------
# §7 — Owner-only guard
# ---------------------------------------------------------------------------


class TestIsOrgOwner:
    """Subscribe is restricted to org owners."""

    @patch(_GET_ORG)
    def test_owner_is_recognised(self, mock_get_org):
        from treesight.security.eudr_billing import is_org_owner

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "members": [
                {"user_id": "u-owner", "role": "owner"},
                {"user_id": "u-member", "role": "member"},
            ],
        }
        assert is_org_owner("org-1", "u-owner") is True

    @patch(_GET_ORG)
    def test_member_is_not_owner(self, mock_get_org):
        from treesight.security.eudr_billing import is_org_owner

        mock_get_org.return_value = {
            "id": "org-1",
            "org_id": "org-1",
            "members": [
                {"user_id": "u-owner", "role": "owner"},
                {"user_id": "u-member", "role": "member"},
            ],
        }
        assert is_org_owner("org-1", "u-member") is False

    @patch(_GET_ORG)
    def test_nonexistent_org_returns_false(self, mock_get_org):
        from treesight.security.eudr_billing import is_org_owner

        mock_get_org.return_value = None
        assert is_org_owner("missing", "u-anyone") is False
