"""Tests for billing blueprint endpoints (blueprints/billing.py).

Covers:
- Webhook signature verification (rejects invalid, accepts valid)
- Webhook event dispatch (checkout.session.completed, subscription updates)
- Checkout endpoint (auth required, stripe not configured)
- Portal endpoint (auth required, no subscription)
- Status endpoint (returns tier + remaining)
- CORS handling

Note: endpoints decorated with @require_auth must be called with just (req).
When auth is disabled (patched), the decorator injects auth_claims/user_id.
"""

import json
from unittest.mock import patch

import azure.functions as func

from tests.conftest import TEST_LOCAL_ORIGIN, TEST_ORIGIN, make_test_request

_ALLOWED_ORIGIN = TEST_ORIGIN
_REQUIRE_AUTH = patch.dict("os.environ", {"REQUIRE_AUTH": "1"})
_BILLING_UNGATED = patch(
    "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
    frozenset({"test-user"}),
)
_EMULATION_UNGATED = patch(
    "treesight.security.feature_gate.TIER_EMULATION_ALLOWED_USERS",
    frozenset({"test-user"}),
)


def _make_req(method="POST", body=b"", headers=None, url="/api/billing/webhook"):
    return make_test_request(
        url=url,
        method=method,
        body=body,
        headers=headers,
        origin=_ALLOWED_ORIGIN,
    )


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------


class TestBillingWebhook:
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    def test_invalid_signature_returns_400(self):
        from blueprints.billing import billing_webhook

        req = _make_req(body=b'{"type":"test"}', headers={"Stripe-Signature": "bad_sig"})
        resp = billing_webhook(req)
        assert resp.status_code == 400

    @patch("blueprints.billing.STRIPE_API_KEY", "")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "")
    def test_not_configured_returns_503(self):
        from blueprints.billing import billing_webhook

        req = _make_req(body=b"{}")
        resp = billing_webhook(req)
        assert resp.status_code == 503


class TestHandleEvent:
    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_checkout_completed_saves_pro(self, _mock_read, mock_upsert):
        from blueprints.billing import _handle_event

        _handle_event(
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "client_reference_id": "user-abc",
                        "customer": "cus_123",
                        "subscription": "sub_456",
                    }
                },
            }
        )

        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "user-abc"
        assert doc["tier"] == "pro"
        assert doc["status"] == "active"
        assert doc["stripe_customer_id"] == "cus_123"

    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_subscription_deleted_downgrades(self, _mock_read, mock_upsert):
        from blueprints.billing import _handle_event

        _handle_event(
            {
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "metadata": {"user_id": "user-gone"},
                        "customer": "cus_789",
                        "id": "sub_old",
                        "status": "canceled",
                    }
                },
            }
        )

        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "user-gone"
        assert doc["tier"] == "free"
        assert doc["status"] == "canceled"

    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_payment_failed_sets_past_due(self, _mock_read, mock_upsert):
        from blueprints.billing import _handle_event

        _handle_event(
            {
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "metadata": {"user_id": "user-broke"},
                        "customer": "cus_fail",
                        "subscription": "sub_fail",
                    }
                },
            }
        )

        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["status"] == "past_due"

    def test_unknown_user_is_skipped(self):
        from blueprints.billing import _handle_event

        # Should not raise — just logs a warning
        _handle_event({"type": "checkout.session.completed", "data": {"object": {}}})


# ---------------------------------------------------------------------------
# Checkout endpoint tests (calls through @require_auth decorator)
# ---------------------------------------------------------------------------


class TestBillingCheckout:
    @patch("blueprints.billing.STRIPE_API_KEY", "")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "")
    @_BILLING_UNGATED
    def test_not_configured_returns_503(self):
        from blueprints.billing import billing_checkout

        req = _make_req(url="/api/billing/checkout")
        resp = billing_checkout(req)
        assert resp.status_code == 503

    def test_options_returns_204(self):
        from blueprints.billing import billing_checkout

        req = _make_req(method="OPTIONS", url="/api/billing/checkout")
        # OPTIONS is handled before @require_auth checks
        resp = billing_checkout(req)
        assert resp.status_code == 204

    @_REQUIRE_AUTH
    def test_anonymous_returns_401(self):
        from blueprints.billing import billing_checkout

        req = make_test_request(
            url="/api/billing/checkout",
            origin=_ALLOWED_ORIGIN,
            principal_user_id=None,
            auth_header=None,
        )
        resp = billing_checkout(req)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Portal endpoint tests
# ---------------------------------------------------------------------------


class TestBillingPortal:
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    @_BILLING_UNGATED
    def test_no_subscription_returns_404(self, _mock_read):
        from blueprints.billing import billing_portal

        req = _make_req(url="/api/billing/portal")
        resp = billing_portal(req)
        assert resp.status_code == 404

    def test_options_returns_204(self):
        from blueprints.billing import billing_portal

        req = _make_req(method="OPTIONS", url="/api/billing/portal")
        resp = billing_portal(req)
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Status endpoint tests
# ---------------------------------------------------------------------------


class TestBillingStatus:
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_free_user_status(self, _mock_read):
        from blueprints.billing import billing_status

        req = func.HttpRequest(
            method="GET", url="/api/billing/status", headers={"Origin": _ALLOWED_ORIGIN}, body=b""
        )
        resp = billing_status(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["tier"] == "free"
        assert data["runs_remaining"] >= 0
        assert data["capabilities"]["run_limit"] >= 0
        assert data["emulation"]["available"] is False

    def test_options_returns_204(self):
        from blueprints.billing import billing_status

        req = func.HttpRequest(
            method="OPTIONS",
            url="/api/billing/status",
            headers={"Origin": _ALLOWED_ORIGIN},
            body=b"",
        )
        resp = billing_status(req)
        assert resp.status_code == 204

    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item")
    @_BILLING_UNGATED
    @_EMULATION_UNGATED
    def test_allowlisted_operator_can_enable_tier_emulation(self, mock_read, mock_upsert):
        from blueprints.billing import billing_emulation, billing_status

        store: dict[str, dict] = {}

        def _read_item(container, item_id, partition_key):
            return store.get(f"{container}/{item_id}")

        def _upsert_item(container, item):
            store[f"{container}/{item['id']}"] = item
            return item

        mock_read.side_effect = _read_item
        mock_upsert.side_effect = _upsert_item

        emulate_req = _make_req(
            body=json.dumps({"tier": "team"}).encode("utf-8"),
            url="/api/billing/emulation",
        )
        emulate_resp = billing_emulation(emulate_req)
        assert emulate_resp.status_code == 200
        emulate_data = json.loads(emulate_resp.get_body())
        assert emulate_data["tier"] == "team"
        assert emulate_data["tier_source"] == "emulated"
        assert emulate_data["emulation"]["active"] is True

        status_req = _make_req(method="GET", url="/api/billing/status")
        status_resp = billing_status(status_req)
        assert status_resp.status_code == 200
        status_data = json.loads(status_resp.get_body())
        assert status_data["tier"] == "team"
        assert status_data["capabilities"]["api_access"] is True

    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_non_allowlisted_account_rejects_tier_emulation(self, _mock_read):
        from blueprints.billing import billing_emulation

        req = _make_req(
            body=json.dumps({"tier": "team"}).encode("utf-8"),
            url="/api/billing/emulation",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 403

    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_localhost_origin_does_not_bypass_account_lock_for_non_allowlisted(self, _mock_read):
        """Non-allowlisted users are rejected even on localhost origin."""
        from blueprints.billing import billing_emulation

        req = make_test_request(
            url="/api/billing/emulation",
            method="POST",
            body=json.dumps({"tier": "team"}).encode("utf-8"),
            origin=TEST_LOCAL_ORIGIN,
            principal_user_id="not-allowlisted-user",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 403
        # Verify the account-lock policy applies (not origin-based)
        body = resp.get_body().decode("utf-8")
        assert "not yet available" in body

    @_EMULATION_UNGATED
    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item")
    def test_operator_can_emulate_from_non_local_origin(self, mock_read, mock_upsert):
        """Operator-allowlisted users can use tier emulation from production origins."""
        from blueprints.billing import billing_emulation

        store: dict[str, dict] = {}

        def _read_item(container, item_id, partition_key):
            return store.get(f"{container}/{item_id}")

        def _upsert_item(container, item):
            store[f"{container}/{item['id']}"] = item
            return item

        mock_read.side_effect = _read_item
        mock_upsert.side_effect = _upsert_item

        # Non-local origin but user is in TIER_EMULATION_ALLOWED_USERS
        req = _make_req(
            body=json.dumps({"tier": "pro"}).encode("utf-8"),
            url="/api/billing/emulation",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["tier"] == "pro"
        assert data["tier_source"] == "emulated"
        assert data["emulation"]["active"] is True

    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item")
    def test_anonymous_cannot_use_tier_emulation_even_on_local_origin(self, mock_read, mock_upsert):
        from blueprints.billing import billing_emulation

        store: dict[str, dict] = {}

        def _read_item(container, item_id, partition_key):
            return store.get(f"{container}/{item_id}")

        def _upsert_item(container, item):
            store[f"{container}/{item['id']}"] = item
            return item

        mock_read.side_effect = _read_item
        mock_upsert.side_effect = _upsert_item

        req = make_test_request(
            url="/api/billing/emulation",
            method="POST",
            body=json.dumps({"tier": "starter"}).encode("utf-8"),
            origin=TEST_LOCAL_ORIGIN,
            principal_user_id=None,
            auth_header=None,
        )
        resp = billing_emulation(req)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Cosmos-backed billing_allowed path
# ---------------------------------------------------------------------------


class TestCosmosBillingAllowed:
    """Test tier emulation gate when user is allowlisted in Cosmos user record."""

    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item")
    @patch("treesight.security.users.get_user")
    def test_tier_emulation_allowed_via_cosmos_user_record(
        self, mock_get_user, mock_read, mock_upsert
    ):
        """User allowlisted in Cosmos user record can use tier emulation."""
        from blueprints.billing import billing_emulation

        # Mock Cosmos tier_emulation_allowed flag
        mock_get_user.return_value = {"id": "test-user", "tier_emulation_allowed": True}

        store: dict[str, dict] = {}

        def _read_item(container, item_id, partition_key):
            return store.get(f"{container}/{item_id}")

        def _upsert_item(container, item):
            store[f"{container}/{item['id']}"] = item
            return item

        mock_read.side_effect = _read_item
        mock_upsert.side_effect = _upsert_item

        req = make_test_request(
            url="/api/billing/emulation",
            method="POST",
            body=json.dumps({"tier": "pro"}).encode("utf-8"),
            principal_user_id="test-user",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["billing_gated"] is True
        assert data["emulation"]["available"] is True

    @patch("treesight.storage.cosmos.read_item")
    @patch("treesight.security.users.get_user")
    def test_tier_emulation_rejected_when_not_in_cosmos(self, mock_get_user, mock_read):
        """User not allowlisted in Cosmos is rejected."""
        from blueprints.billing import billing_emulation

        # Mock Cosmos user missing tier_emulation_allowed grant
        mock_get_user.return_value = {"id": "not-allowlisted-user", "billing_allowed": True}
        mock_read.return_value = None

        req = make_test_request(
            url="/api/billing/emulation",
            method="POST",
            body=json.dumps({"tier": "pro"}).encode("utf-8"),
            principal_user_id="not-allowlisted-user",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 403
        body = resp.get_body().decode("utf-8")
        assert "not yet available" in body

    @patch("treesight.storage.cosmos.read_item")
    @patch("treesight.security.users.get_user")
    def test_tier_emulation_rejected_on_cosmos_error(self, mock_get_user, mock_read):
        """Cosmos error defaults to reject (safe failure)."""
        from blueprints.billing import billing_emulation

        # Mock Cosmos error
        mock_get_user.side_effect = Exception("Cosmos unavailable")
        mock_read.return_value = None

        req = make_test_request(
            url="/api/billing/emulation",
            method="POST",
            body=json.dumps({"tier": "pro"}).encode("utf-8"),
            principal_user_id="test-user",
        )
        resp = billing_emulation(req)
        # Should reject when Cosmos is down (safe default)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# _user_id_from_customer reverse-lookup
# ---------------------------------------------------------------------------


class TestUserIdFromCustomer:
    def setup_method(self):
        from blueprints.billing import _customer_to_user_cache

        _customer_to_user_cache.clear()

    def test_none_customer_returns_none(self):
        from blueprints.billing import _user_id_from_customer

        assert _user_id_from_customer(None) is None

    @patch("treesight.storage.cosmos.query_items")
    def test_finds_matching_customer(self, mock_query):
        from blueprints.billing import _user_id_from_customer

        mock_query.return_value = [{"user_id": "user-xyz"}]
        assert _user_id_from_customer("cus_target") == "user-xyz"
        mock_query.assert_called_once_with(
            "subscriptions",
            "SELECT c.user_id FROM c WHERE c.stripe_customer_id = @cid",
            parameters=[{"name": "@cid", "value": "cus_target"}],
        )

    @patch("treesight.storage.cosmos.query_items")
    def test_no_match_returns_none(self, mock_query):
        from blueprints.billing import _user_id_from_customer

        mock_query.return_value = []
        assert _user_id_from_customer("cus_unknown") is None

    @patch("treesight.storage.cosmos.query_items", side_effect=RuntimeError("down"))
    def test_returns_none_on_cosmos_error(self, _mock_query):
        from blueprints.billing import _user_id_from_customer

        assert _user_id_from_customer("cus_err") is None

    @patch("treesight.storage.cosmos.query_items")
    def test_does_not_cache_none_on_exception(self, mock_query):
        """After a Cosmos error, the next call should retry — not return cached None."""
        from blueprints.billing import _customer_to_user_cache, _user_id_from_customer

        _customer_to_user_cache.pop("cus_retry", None)

        mock_query.side_effect = RuntimeError("transient")
        assert _user_id_from_customer("cus_retry") is None
        assert "cus_retry" not in _customer_to_user_cache

        mock_query.side_effect = None
        mock_query.return_value = [{"user_id": "recovered-user"}]
        assert _user_id_from_customer("cus_retry") == "recovered-user"


# ---------------------------------------------------------------------------
# billing/status resilience — returns 200 even when storage is unavailable
# ---------------------------------------------------------------------------


class TestBillingStatusResilience:
    @patch("treesight.storage.cosmos.read_item", side_effect=RuntimeError("cosmos down"))
    @patch("treesight.storage.cosmos.query_items", side_effect=RuntimeError("cosmos down"))
    def test_returns_safe_default_when_cosmos_fails(self, _mock_query, _mock_read):
        """billing/status should return 200 with free-tier defaults, not 500."""
        from blueprints.billing import billing_status

        req = func.HttpRequest(
            method="GET",
            url="/api/billing/status",
            headers={"Origin": _ALLOWED_ORIGIN},
            body=b"",
        )
        resp = billing_status(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["tier"] == "free"
        assert data["runs_remaining"] >= 0
        assert data["billing_gated"] is True
