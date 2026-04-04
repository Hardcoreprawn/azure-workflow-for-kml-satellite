"""Integration tests for Stripe billing — hits real Stripe test-mode API.

Requires STRIPE_API_KEY (sk_test_...) in environment or Key Vault.
Skips automatically if not available.

Uses Stripe's official test card numbers:
    https://docs.stripe.com/testing#cards
"""

import json
import os
import time
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Skip unless a test-mode Stripe key is available
# ---------------------------------------------------------------------------


def _load_stripe_key() -> str:
    """Try env var first, then Key Vault (only if VAULT_NAME is set)."""
    key = os.environ.get("STRIPE_API_KEY", "")
    if key:
        return key
    vault = os.environ.get("VAULT_NAME", "")
    if not vault:
        return ""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        client = SecretClient(
            vault_url=f"https://{vault}.vault.azure.net",
            credential=DefaultAzureCredential(),
        )
        return client.get_secret("stripe-api-key").value or ""
    except Exception:
        return ""


STRIPE_KEY = _load_stripe_key()

skip_no_stripe = pytest.mark.skipif(
    not STRIPE_KEY or not STRIPE_KEY.startswith("sk_test_"),
    reason="No Stripe test key available (set STRIPE_API_KEY or configure Key Vault)",
)

pytestmark = [pytest.mark.integration, skip_no_stripe]

# Stripe test-mode tokens (never pass raw card numbers to the API)
# See: https://docs.stripe.com/testing#tokens
TOK_VISA = "tok_visa"
TOK_DECLINE = "tok_chargeDeclined"


@pytest.fixture(scope="module")
def stripe_mod():
    """Configured Stripe module for test mode."""
    import stripe

    stripe.api_key = STRIPE_KEY
    return stripe


@pytest.fixture(scope="module")
def product(stripe_mod):
    """Find or create a test product."""
    products = stripe_mod.Product.list(limit=100, active=True)
    for p in products.auto_paging_iter():
        if p.name == "Canopex Pro":
            return p
    return stripe_mod.Product.create(
        name="Canopex Pro",
        metadata={"app": "treesight", "tier": "pro", "test": "true"},
    )


@pytest.fixture(scope="module")
def price_gbp(stripe_mod, product):
    """Find or create the GBP test price."""
    prices = stripe_mod.Price.list(product=product.id, currency="gbp", active=True, limit=20)
    for p in prices.auto_paging_iter():
        if p.unit_amount == 3900 and p.recurring and p.recurring.interval == "month":
            return p
    return stripe_mod.Price.create(
        product=product.id,
        unit_amount=3900,
        currency="gbp",
        recurring={"interval": "month"},
        metadata={"test": "true"},
    )


# ---------------------------------------------------------------------------
# Stripe API connectivity
# ---------------------------------------------------------------------------
class TestStripeConnectivity:
    """Verify we can talk to Stripe in test mode."""

    def test_api_key_is_test_mode(self):
        assert STRIPE_KEY.startswith("sk_test_")

    def test_account_accessible(self, stripe_mod):
        account = stripe_mod.Account.retrieve()
        assert account.id is not None

    def test_product_exists(self, product):
        assert product.id.startswith("prod_")
        assert product.name == "Canopex Pro"

    def test_price_exists(self, price_gbp):
        assert price_gbp.id.startswith("price_")
        assert price_gbp.unit_amount == 3900
        assert price_gbp.currency == "gbp"


# ---------------------------------------------------------------------------
# Checkout session creation
# ---------------------------------------------------------------------------
class TestCheckoutSession:
    """Test creating Stripe Checkout sessions via the real API."""

    def test_create_checkout_session(self, stripe_mod, price_gbp):
        session = stripe_mod.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_gbp.id, "quantity": 1}],
            success_url="https://canopex.hrdcrprwn.com?billing=success",
            cancel_url="https://canopex.hrdcrprwn.com?billing=cancel",
            client_reference_id="test-user-001",
            metadata={"user_id": "test-user-001"},
        )
        assert session.id.startswith("cs_test_")
        from urllib.parse import urlparse

        assert session.url is not None
        assert urlparse(session.url).hostname == "checkout.stripe.com"
        assert session.status == "open"
        assert session.mode == "subscription"

    def test_checkout_with_currency_selection(self, stripe_mod, product):
        """Test that USD/EUR prices also work."""
        # Create an ephemeral USD price for this test
        price_usd = stripe_mod.Price.create(
            product=product.id,
            unit_amount=4900,
            currency="usd",
            recurring={"interval": "month"},
            metadata={"test": "true", "ephemeral": "true"},
        )
        session = stripe_mod.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_usd.id, "quantity": 1}],
            success_url="https://canopex.hrdcrprwn.com?billing=success",
            cancel_url="https://canopex.hrdcrprwn.com?billing=cancel",
            client_reference_id="test-user-002",
        )
        assert session.id.startswith("cs_test_")
        assert session.currency == "usd"


# ---------------------------------------------------------------------------
# Customer creation and subscription lifecycle
# ---------------------------------------------------------------------------
class TestSubscriptionLifecycle:
    """Test the full subscription lifecycle using Stripe test helpers."""

    def test_create_customer(self, stripe_mod):
        customer = stripe_mod.Customer.create(
            email="test@treesight-integration.test",
            name="Integration Test User",
            metadata={"user_id": "test-user-lifecycle", "test": "true"},
        )
        assert customer.id.startswith("cus_")
        assert customer.email == "test@treesight-integration.test"
        # Cleanup
        stripe_mod.Customer.delete(customer.id)

    def test_subscription_with_test_card(self, stripe_mod, price_gbp):
        """Create a subscription using the test card via token."""
        # 1. Create customer with test card token
        customer = stripe_mod.Customer.create(
            email="lifecycle@treesight-integration.test",
            source=TOK_VISA,
            metadata={"user_id": "test-user-sub", "test": "true"},
        )

        # 2. Create subscription
        sub = stripe_mod.Subscription.create(
            customer=customer.id,
            items=[{"price": price_gbp.id}],
            metadata={"user_id": "test-user-sub", "test": "true"},
        )
        assert sub.status == "active"
        assert sub["items"]["data"][0]["price"]["id"] == price_gbp.id

        # 3. Cancel at period end (mirrors our portal config)
        updated = stripe_mod.Subscription.modify(sub.id, cancel_at_period_end=True)
        assert updated.cancel_at_period_end is True

        # 4. Cancel immediately for cleanup
        stripe_mod.Subscription.cancel(sub.id)
        canceled = stripe_mod.Subscription.retrieve(sub.id)
        assert canceled.status == "canceled"

        # Cleanup customer
        stripe_mod.Customer.delete(customer.id)

    def test_declined_card(self, stripe_mod, price_gbp):
        """Verify declined test card raises CardError."""
        with pytest.raises(stripe_mod.CardError) as exc_info:
            stripe_mod.Customer.create(
                email="decline@treesight-integration.test",
                source=TOK_DECLINE,
                metadata={"test": "true"},
            )
        assert exc_info.value.code == "card_declined"


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------
class TestWebhookSignature:
    """Test Stripe webhook signature construction and verification."""

    def test_construct_and_verify_event(self, stripe_mod):
        """Round-trip: build a signed payload and verify it."""
        # Build a fake event payload
        payload = json.dumps(
            {
                "id": "evt_test_001",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_test_001",
                        "client_reference_id": "test-user-wh",
                        "customer": "cus_test_001",
                        "subscription": "sub_test_001",
                    }
                },
            }
        )

        # Generate a valid signature
        secret = "whsec_test_secret_for_integration_tests"  # pragma: allowlist secret
        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.{payload}"

        import hashlib
        import hmac

        sig = hmac.new(
            secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        header = f"t={timestamp},v1={sig}"

        # Verify
        event = stripe_mod.Webhook.construct_event(payload, header, secret)
        assert event["type"] == "checkout.session.completed"
        assert event["data"]["object"]["client_reference_id"] == "test-user-wh"

    def test_invalid_signature_raises(self, stripe_mod):
        payload = '{"type": "test"}'
        with pytest.raises(stripe_mod.SignatureVerificationError):
            stripe_mod.Webhook.construct_event(payload, "bad_sig", "whsec_test")


# ---------------------------------------------------------------------------
# Billing endpoint integration (hits real Stripe via blueprint code)
# ---------------------------------------------------------------------------
class TestBillingEndpointIntegration:
    """Test the actual billing blueprint functions against real Stripe."""

    @patch("treesight.security.auth.auth_enabled", return_value=False)
    @patch("treesight.storage.client.BlobStorageClient")
    def test_checkout_endpoint_returns_url(self, mock_storage, _auth, price_gbp):
        import azure.functions as func

        from blueprints.billing import billing_checkout

        with (
            patch("blueprints.billing.STRIPE_API_KEY", STRIPE_KEY),
            patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch("blueprints.billing.STRIPE_PRICE_ID_PRO_GBP", price_gbp.id),
        ):
            req = func.HttpRequest(
                method="POST",
                url="/api/billing/checkout",
                headers={"Origin": "https://canopex.hrdcrprwn.com"},
                body=json.dumps({"currency": "GBP"}).encode(),
            )
            resp = billing_checkout(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        from urllib.parse import urlparse

        assert "checkout_url" in body
        assert urlparse(body["checkout_url"]).hostname == "checkout.stripe.com"

    @patch("treesight.security.auth.auth_enabled", return_value=False)
    @patch("treesight.storage.client.BlobStorageClient")
    def test_status_endpoint_free_user(self, mock_storage, _auth):
        import azure.functions as func

        from blueprints.billing import billing_status

        mock_storage.return_value.download_json.side_effect = FileNotFoundError

        with (
            patch("blueprints.billing.STRIPE_API_KEY", STRIPE_KEY),
            patch("blueprints.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"),
        ):
            req = func.HttpRequest(
                method="GET",
                url="/api/billing/status",
                headers={"Origin": "https://canopex.hrdcrprwn.com"},
                body=b"",
            )
            resp = billing_status(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["tier"] == "free"
        assert body["runs_remaining"] >= 0
