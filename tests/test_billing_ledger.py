"""Tests for treesight.security.billing_ledger — run-level billing (#589)."""

from unittest.mock import MagicMock, patch

from treesight.security.billing_ledger import (
    billing_fields_for_submission,
    classify_run,
    complete_run_billing,
    fail_run_billing,
)

# Shared patch targets — billing_ledger does lazy imports from these modules.
_COSMOS_READ = "treesight.storage.cosmos.read_item"
_COSMOS_UPSERT = "treesight.storage.cosmos.upsert_item"
_GET_SUB = "treesight.security.billing.get_effective_subscription"
_GET_USAGE = "treesight.security.quota.get_usage"
_GET_PROVIDER = "treesight.security.payment_provider.get_payment_provider"


# ---------------------------------------------------------------------------
# classify_run
# ---------------------------------------------------------------------------


class TestClassifyRun:
    def test_demo_tier(self):
        result = classify_run("demo", 0, 3)
        assert result == {"billing_type": "demo", "overage_unit_price": None}

    def test_free_tier(self):
        result = classify_run("free", 5, 10)
        assert result == {"billing_type": "free", "overage_unit_price": None}

    def test_paid_included_run(self):
        """A Pro user on their 20th of 50 included runs."""
        result = classify_run("pro", 19, 50)
        assert result["billing_type"] == "included"
        assert result["overage_unit_price"] is None

    def test_paid_last_included_run(self):
        """A Pro user on their 50th run (index 49) — still included."""
        result = classify_run("pro", 49, 50)
        assert result["billing_type"] == "included"

    def test_paid_first_overage_run(self):
        """A Pro user on run 51 (50 used before this one) — overage."""
        result = classify_run("pro", 50, 50)
        assert result["billing_type"] == "overage"
        assert result["overage_unit_price"] == 0.80

    def test_starter_overage_rate(self):
        result = classify_run("starter", 20, 20)
        assert result["billing_type"] == "overage"
        assert result["overage_unit_price"] == 1.50

    def test_team_overage_rate(self):
        result = classify_run("team", 200, 200)
        assert result["billing_type"] == "overage"
        assert result["overage_unit_price"] == 0.50

    def test_enterprise_overage_has_no_rate(self):
        """Enterprise has no overage rate (unlimited included)."""
        result = classify_run("enterprise", 999, 1000)
        assert result["billing_type"] == "included"
        assert result["overage_unit_price"] is None

    def test_unknown_tier_falls_back_to_free(self):
        result = classify_run("nonexistent", 0, 10)
        assert result["billing_type"] == "free"


# ---------------------------------------------------------------------------
# billing_fields_for_submission
# ---------------------------------------------------------------------------


class TestBillingFieldsForSubmission:
    @patch(_GET_USAGE)
    @patch(_GET_SUB)
    def test_free_user_first_run(self, mock_sub, mock_usage):
        mock_sub.return_value = {"tier": "free", "status": "none"}
        mock_usage.return_value = {"used": 1, "limit": 10}  # 1 because consume was called

        fields = billing_fields_for_submission("u-free")

        assert fields["tier_at_submission"] == "free"
        assert fields["billing_type"] == "free"
        assert fields["overage_unit_price"] is None
        assert fields["billing_status"] == "pending"

    @patch(_GET_USAGE)
    @patch(_GET_SUB)
    def test_pro_included_run(self, mock_sub, mock_usage):
        mock_sub.return_value = {"tier": "pro", "status": "active"}
        mock_usage.return_value = {"used": 10, "limit": 50}

        fields = billing_fields_for_submission("u-pro")

        assert fields["tier_at_submission"] == "pro"
        assert fields["billing_type"] == "included"
        assert fields["billing_status"] == "pending"

    @patch(_GET_USAGE)
    @patch(_GET_SUB)
    def test_pro_overage_run(self, mock_sub, mock_usage):
        mock_sub.return_value = {"tier": "pro", "status": "active"}
        mock_usage.return_value = {"used": 51, "limit": 50}  # 51 — overage

        fields = billing_fields_for_submission("u-pro-over")

        assert fields["billing_type"] == "overage"
        assert fields["overage_unit_price"] == 0.80


# ---------------------------------------------------------------------------
# complete_run_billing
# ---------------------------------------------------------------------------


class TestCompleteRunBilling:
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_marks_included_run_as_charged(self, mock_read, mock_upsert):
        mock_read.return_value = {
            "id": "inst-1",
            "user_id": "u1",
            "billing_type": "included",
            "billing_status": "pending",
        }

        complete_run_billing("u1", "inst-1")

        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["billing_status"] == "charged"

    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_skips_already_charged(self, mock_read, mock_upsert):
        mock_read.return_value = {
            "id": "inst-1",
            "user_id": "u1",
            "billing_type": "included",
            "billing_status": "charged",
            "payment_ref": None,
        }

        complete_run_billing("u1", "inst-1")

        mock_upsert.assert_not_called()

    @patch("treesight.security.billing_ledger._report_overage")
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_reports_overage_to_provider(self, mock_read, mock_upsert, mock_report):
        doc = {
            "id": "inst-2",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "pending",
            "tier_at_submission": "pro",
        }
        mock_read.return_value = doc
        # Simulate _report_overage setting payment_ref (provider succeeded)
        mock_report.side_effect = lambda uid, iid, d: d.__setitem__("payment_ref", "ur_123")

        complete_run_billing("u1", "inst-2")

        mock_report.assert_called_once_with("u1", "inst-2", doc)
        mock_upsert.assert_called_once()
        saved_doc = mock_upsert.call_args[0][1]
        assert saved_doc["billing_status"] == "charged"

    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_handles_missing_document(self, mock_read, mock_upsert):
        mock_read.return_value = None

        complete_run_billing("u1", "inst-missing")

        mock_upsert.assert_not_called()

    @patch("treesight.security.billing_ledger._report_overage")
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_overage_stays_pending_when_provider_fails(self, mock_read, mock_upsert, mock_report):
        """If _report_overage doesn't set payment_ref, run stays pending."""
        mock_read.return_value = {
            "id": "inst-fail",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "pending",
            "tier_at_submission": "pro",
        }
        # Provider returns None — no payment_ref set
        mock_report.side_effect = lambda uid, iid, d: None

        complete_run_billing("u1", "inst-fail")

        mock_report.assert_called_once()
        mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# fail_run_billing
# ---------------------------------------------------------------------------


class TestFailRunBilling:
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_marks_pending_run_as_refunded(self, mock_read, mock_upsert):
        mock_read.return_value = {
            "id": "inst-1",
            "user_id": "u1",
            "billing_type": "included",
            "billing_status": "pending",
        }

        fail_run_billing("u1", "inst-1", reason="pipeline_failure")

        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["billing_status"] == "refunded"
        assert doc["refund_reason"] == "pipeline_failure"

    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_skips_already_refunded(self, mock_read, mock_upsert):
        mock_read.return_value = {
            "id": "inst-1",
            "user_id": "u1",
            "billing_type": "included",
            "billing_status": "refunded",
        }

        fail_run_billing("u1", "inst-1")

        mock_upsert.assert_not_called()

    @patch("treesight.security.billing_ledger._credit_overage")
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_credits_charged_overage_run(self, mock_read, mock_upsert, mock_credit):
        mock_read.return_value = {
            "id": "inst-3",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "charged",
            "tier_at_submission": "pro",
        }

        fail_run_billing("u1", "inst-3", reason="timeout")

        mock_upsert.assert_called_once()
        mock_credit.assert_called_once_with("u1", "inst-3", mock_upsert.call_args[0][1], "timeout")

    @patch("treesight.security.billing_ledger._credit_overage")
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_no_credit_for_pending_overage(self, mock_read, mock_upsert, mock_credit):
        """Overage run that failed before being charged — no credit needed."""
        mock_read.return_value = {
            "id": "inst-4",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "pending",
        }

        fail_run_billing("u1", "inst-4", reason="pipeline_failure")

        mock_upsert.assert_called_once()
        mock_credit.assert_not_called()

    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_handles_missing_document(self, mock_read, mock_upsert):
        mock_read.return_value = None

        fail_run_billing("u1", "inst-missing")

        mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Provider integration (_report_overage / _credit_overage)
# ---------------------------------------------------------------------------


class TestOverageProviderIntegration:
    @patch(_GET_PROVIDER)
    @patch(_GET_SUB)
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_report_overage_calls_provider(
        self, mock_read, mock_upsert, mock_sub, mock_provider_fn
    ):
        mock_read.return_value = {
            "id": "inst-over",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "pending",
            "tier_at_submission": "pro",
        }
        mock_sub.return_value = {
            "tier": "pro",
            "status": "active",
            "stripe_subscription_item_id": "si_abc",
        }
        mock_provider = MagicMock()
        mock_provider.report_usage.return_value = "ur_123"
        mock_provider_fn.return_value = mock_provider

        complete_run_billing("u1", "inst-over")

        mock_provider.report_usage.assert_called_once_with(
            user_id="u1",
            subscription_item_id="si_abc",
            quantity=1,
            idempotency_key="overage-inst-over",
            metadata={"instance_id": "inst-over", "tier": "pro"},
        )
        # Verify payment_ref was saved
        final_doc = mock_upsert.call_args_list[-1][0][1]
        assert final_doc["payment_ref"] == "ur_123"

    @patch(_GET_PROVIDER)
    @patch(_GET_SUB)
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_credit_overage_calls_provider(
        self, mock_read, mock_upsert, mock_sub, mock_provider_fn
    ):
        mock_read.return_value = {
            "id": "inst-credit",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "charged",
            "tier_at_submission": "pro",
        }
        mock_sub.return_value = {
            "tier": "pro",
            "status": "active",
            "stripe_subscription_item_id": "si_abc",
        }
        mock_provider = MagicMock()
        mock_provider.credit_usage.return_value = "cr_456"
        mock_provider_fn.return_value = mock_provider

        fail_run_billing("u1", "inst-credit", reason="timeout")

        mock_provider.credit_usage.assert_called_once_with(
            user_id="u1",
            subscription_item_id="si_abc",
            quantity=1,
            idempotency_key="credit-inst-credit",
            reason="timeout",
        )
        final_doc = mock_upsert.call_args_list[-1][0][1]
        assert final_doc["payment_ref"] == "cr_456"

    @patch(_GET_PROVIDER)
    @patch(_GET_SUB)
    @patch(_COSMOS_UPSERT)
    @patch(_COSMOS_READ)
    def test_no_provider_call_without_stripe_sub(
        self, mock_read, mock_upsert, mock_sub, mock_provider_fn
    ):
        mock_read.return_value = {
            "id": "inst-nosub",
            "user_id": "u1",
            "billing_type": "overage",
            "billing_status": "pending",
            "tier_at_submission": "pro",
        }
        mock_sub.return_value = {
            "tier": "pro",
            "status": "active",
            # No stripe_subscription_item_id
        }

        complete_run_billing("u1", "inst-nosub")

        mock_provider_fn.assert_not_called()
