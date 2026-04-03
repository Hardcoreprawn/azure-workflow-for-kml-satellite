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
_AUTH_DISABLED = patch("treesight.security.auth.auth_enabled", return_value=False)
_AUTH_TEST_USER = [
    patch("blueprints._helpers.auth_enabled", return_value=True),
    patch("blueprints._helpers.validate_token", return_value={"sub": "test-user"}),
]
_BILLING_UNGATED = patch(
    "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
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
    @patch("treesight.storage.client.BlobStorageClient")
    def test_checkout_completed_saves_pro(self, mock_cls):
        from blueprints.billing import _handle_event

        store = {}
        mock_cls.return_value.upload_json = lambda c, p, d: store.update({p: d})
        mock_cls.return_value.download_json.side_effect = FileNotFoundError

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

        saved = store.get("subscriptions/user-abc.json")
        assert saved is not None
        assert saved["tier"] == "pro"
        assert saved["status"] == "active"
        assert saved["stripe_customer_id"] == "cus_123"

    @patch("treesight.storage.client.BlobStorageClient")
    def test_subscription_deleted_downgrades(self, mock_cls):
        from blueprints.billing import _handle_event

        store = {}
        mock_cls.return_value.upload_json = lambda c, p, d: store.update({p: d})
        mock_cls.return_value.download_json.side_effect = FileNotFoundError

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

        saved = store.get("subscriptions/user-gone.json")
        assert saved is not None
        assert saved["tier"] == "free"
        assert saved["status"] == "canceled"

    @patch("treesight.storage.client.BlobStorageClient")
    def test_payment_failed_sets_past_due(self, mock_cls):
        from blueprints.billing import _handle_event

        store = {}
        mock_cls.return_value.upload_json = lambda c, p, d: store.update({p: d})
        mock_cls.return_value.download_json.side_effect = FileNotFoundError

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

        saved = store.get("subscriptions/user-broke.json")
        assert saved is not None
        assert saved["status"] == "past_due"

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
    @_AUTH_TEST_USER[1]
    @_AUTH_TEST_USER[0]
    def test_not_configured_returns_503(self, _auth, _token):
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

    @_AUTH_DISABLED
    def test_anonymous_returns_401(self, _auth):
        from blueprints.billing import billing_checkout

        req = _make_req(url="/api/billing/checkout")
        resp = billing_checkout(req)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Portal endpoint tests
# ---------------------------------------------------------------------------


class TestBillingPortal:
    @patch("blueprints.billing.STRIPE_API_KEY", "sk_test_xxx")
    @patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test_xxx")
    @patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", "price_xxx")
    @patch("treesight.storage.client.BlobStorageClient")
    @_BILLING_UNGATED
    @_AUTH_TEST_USER[1]
    @_AUTH_TEST_USER[0]
    def test_no_subscription_returns_404(self, _auth, _token, mock_cls):
        from blueprints.billing import billing_portal

        mock_cls.return_value.download_json.side_effect = FileNotFoundError
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
    @patch("treesight.storage.client.BlobStorageClient")
    @_AUTH_DISABLED
    def test_free_user_status(self, _auth, mock_cls):
        from blueprints.billing import billing_status

        mock_cls.return_value.download_json.side_effect = FileNotFoundError
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

    @patch("treesight.storage.client.BlobStorageClient")
    @_AUTH_TEST_USER[1]
    @_AUTH_TEST_USER[0]
    def test_local_origin_can_enable_tier_emulation(self, _auth, _token, mock_cls):
        from blueprints.billing import billing_emulation, billing_status

        store = {}

        def _download_json(_container, path):
            if path not in store:
                raise FileNotFoundError(path)
            return store[path]

        def _upload_json(_container, path, data):
            store[path] = data

        mock_cls.return_value.download_json.side_effect = _download_json
        mock_cls.return_value.upload_json.side_effect = _upload_json

        emulate_req = _make_req(
            body=json.dumps({"tier": "team"}).encode("utf-8"),
            headers={"Origin": TEST_LOCAL_ORIGIN},
            url="/api/billing/emulation",
        )
        emulate_resp = billing_emulation(emulate_req)
        assert emulate_resp.status_code == 200
        emulate_data = json.loads(emulate_resp.get_body())
        assert emulate_data["tier"] == "team"
        assert emulate_data["tier_source"] == "emulated"
        assert emulate_data["emulation"]["active"] is True

        status_req = _make_req(
            method="GET", headers={"Origin": TEST_LOCAL_ORIGIN}, url="/api/billing/status"
        )
        status_resp = billing_status(status_req)
        assert status_resp.status_code == 200
        status_data = json.loads(status_resp.get_body())
        assert status_data["tier"] == "team"
        assert status_data["capabilities"]["api_access"] is True

    @patch("treesight.storage.client.BlobStorageClient")
    @_AUTH_TEST_USER[1]
    @_AUTH_TEST_USER[0]
    def test_non_local_origin_rejects_tier_emulation(self, _auth, _token, mock_cls):
        from blueprints.billing import billing_emulation

        req = _make_req(
            body=json.dumps({"tier": "team"}).encode("utf-8"),
            url="/api/billing/emulation",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 403

    @patch("treesight.storage.client.BlobStorageClient")
    @_AUTH_DISABLED
    def test_local_origin_allows_anonymous_tier_emulation(self, _auth, mock_cls):
        from blueprints.billing import billing_emulation

        store = {}

        def _download_json(_container, path):
            if path not in store:
                raise FileNotFoundError(path)
            return store[path]

        def _upload_json(_container, path, data):
            store[path] = data

        mock_cls.return_value.download_json.side_effect = _download_json
        mock_cls.return_value.upload_json.side_effect = _upload_json

        req = _make_req(
            body=json.dumps({"tier": "starter"}).encode("utf-8"),
            headers={"Origin": TEST_LOCAL_ORIGIN},
            url="/api/billing/emulation",
        )
        resp = billing_emulation(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["tier"] == "starter"
        assert data["tier_source"] == "emulated"


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

    @patch("treesight.storage.client.BlobStorageClient")
    def test_finds_matching_customer(self, mock_cls):
        from blueprints.billing import _user_id_from_customer

        mock_cls.return_value.list_blobs.return_value = [
            "subscriptions/user-xyz.json",
        ]
        mock_cls.return_value.download_json.return_value = {
            "stripe_customer_id": "cus_target",
            "tier": "pro",
        }
        assert _user_id_from_customer("cus_target") == "user-xyz"

    @patch("treesight.storage.client.BlobStorageClient")
    def test_no_match_returns_none(self, mock_cls):
        from blueprints.billing import _user_id_from_customer

        mock_cls.return_value.list_blobs.return_value = [
            "subscriptions/user-other.json",
        ]
        mock_cls.return_value.download_json.return_value = {
            "stripe_customer_id": "cus_different",
        }
        assert _user_id_from_customer("cus_unknown") is None


class TestUserIdFromCustomerCosmos:
    def setup_method(self):
        from blueprints.billing import _customer_to_user_cache

        _customer_to_user_cache.clear()

    @patch("treesight.storage.cosmos.cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.query_items")
    def test_finds_user_via_cosmos_query(self, mock_query, _mock_cosmos):
        from blueprints.billing import _user_id_from_customer

        mock_query.return_value = [{"user_id": "user-abc"}]
        assert _user_id_from_customer("cus_123") == "user-abc"
        mock_query.assert_called_once_with(
            "subscriptions",
            "SELECT c.user_id FROM c WHERE c.stripe_customer_id = @cid",
            parameters=[{"name": "@cid", "value": "cus_123"}],
        )

    @patch("treesight.storage.cosmos.cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.query_items")
    def test_returns_none_when_no_cosmos_match(self, mock_query, _mock_cosmos):
        from blueprints.billing import _user_id_from_customer

        mock_query.return_value = []
        with patch("treesight.storage.client.BlobStorageClient") as mock_cls:
            mock_cls.return_value.list_blobs.return_value = []
            assert _user_id_from_customer("cus_ghost") is None

    @patch("treesight.storage.cosmos.cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.query_items", side_effect=RuntimeError("down"))
    @patch("treesight.storage.client.BlobStorageClient")
    def test_falls_back_to_blob_on_cosmos_error(self, mock_cls, _mock_query, _mock_cosmos):
        from blueprints.billing import _user_id_from_customer

        mock_cls.return_value.list_blobs.return_value = [
            "subscriptions/user-fallback.json",
        ]
        mock_cls.return_value.download_json.return_value = {
            "stripe_customer_id": "cus_err",
        }
        assert _user_id_from_customer("cus_err") == "user-fallback"
