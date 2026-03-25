"""One-time: Provision Stripe product, prices, webhook, and customer portal.

Usage:
    STRIPE_API_KEY=sk_test_xxx \
    WEBHOOK_URL=https://<func-app>/api/billing/webhook \
    python scripts/_setup_stripe.py

What it creates:
    1. Product: "TreeSight Pro" (monthly subscription)
    2. Three Prices: GBP £39, USD $49, EUR €45
    3. Webhook endpoint listening for billing events
    4. Customer Portal configuration (cancel, invoices, payment update)

Output:
    Prints the env vars to set in Key Vault / local.settings.json.
    These values are NOT written anywhere automatically — copy them yourself.

Idempotent: if a product named "TreeSight Pro" already exists, it reuses it.
"""

import os
import sys


def main() -> None:
    api_key = os.environ.get("STRIPE_API_KEY", "")
    webhook_url = os.environ.get("WEBHOOK_URL", "")

    if not api_key:
        print("ERROR: Set STRIPE_API_KEY env var (use sk_test_... for test mode)")
        sys.exit(1)

    if not api_key.startswith("sk_test_"):
        print("WARNING: This does not look like a test-mode key.")
        resp = input("Continue with live key? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            sys.exit(1)

    if not webhook_url:
        print("ERROR: Set WEBHOOK_URL env var (e.g. https://<func-app>/api/billing/webhook)")
        sys.exit(1)

    try:
        import stripe
    except ImportError:
        print("ERROR: stripe SDK not installed. Run: pip install stripe")
        sys.exit(1)

    stripe.api_key = api_key

    # ------------------------------------------------------------------
    # 1. Product
    # ------------------------------------------------------------------
    print("\n=== Product ===")
    product = _find_or_create_product(stripe)
    print(f"  Product ID: {product.id}")

    # ------------------------------------------------------------------
    # 2. Prices (one per currency)
    # ------------------------------------------------------------------
    print("\n=== Prices ===")
    prices_config = [
        {"currency": "gbp", "unit_amount": 3900, "label": "GBP"},
        {"currency": "usd", "unit_amount": 4900, "label": "USD"},
        {"currency": "eur", "unit_amount": 4500, "label": "EUR"},
    ]
    price_ids: dict[str, str] = {}
    for pc in prices_config:
        price = _find_or_create_price(stripe, product.id, pc["currency"], pc["unit_amount"])
        price_ids[pc["label"]] = price.id
        amt = pc["unit_amount"] / 100
        print(f"  {pc['label']}: {price.id} ({amt:.2f} {pc['currency'].upper()}/mo)")

    # ------------------------------------------------------------------
    # 3. Webhook endpoint
    # ------------------------------------------------------------------
    print("\n=== Webhook ===")
    webhook = _find_or_create_webhook(stripe, webhook_url)
    print(f"  Webhook ID: {webhook.id}")
    print(f"  URL: {webhook.url}")
    # The signing secret is only returned on creation
    webhook_secret = getattr(webhook, "secret", None)
    if webhook_secret:
        print(f"  Signing secret: {webhook_secret}")
    else:
        print("  Signing secret: <already created — check Stripe Dashboard if you need it>")

    # ------------------------------------------------------------------
    # 4. Customer Portal
    # ------------------------------------------------------------------
    print("\n=== Customer Portal ===")
    portal = _create_portal_config(stripe, product.id)
    print(f"  Portal config ID: {portal.id}")

    # ------------------------------------------------------------------
    # 5. Enable Stripe Tax
    # ------------------------------------------------------------------
    print("\n=== Tax ===")
    print("  Stripe Tax is activated per-session via automatic_tax={'enabled': True}.")
    print("  Ensure tax registration is set in Stripe Dashboard → Tax → Registrations")
    print("  for each country you operate in (at minimum: GB for UK VAT).")

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Add these to Key Vault / local.settings.json / GitHub Secrets:")
    print("=" * 60)
    print(f"  STRIPE_API_KEY           = {api_key}")
    if webhook_secret:
        print(f"  STRIPE_WEBHOOK_SECRET    = {webhook_secret}")
    else:
        print("  STRIPE_WEBHOOK_SECRET    = <retrieve from Stripe Dashboard → Webhooks>")
    print(f"  STRIPE_PRICE_ID_PRO_GBP  = {price_ids['GBP']}")
    print(f"  STRIPE_PRICE_ID_PRO_USD  = {price_ids['USD']}")
    print(f"  STRIPE_PRICE_ID_PRO_EUR  = {price_ids['EUR']}")
    print()


def _find_or_create_product(stripe) -> object:
    """Find existing 'TreeSight Pro' product or create one."""
    products = stripe.Product.list(limit=100, active=True)
    for p in products.auto_paging_iter():
        if p.name == "TreeSight Pro":
            print("  Found existing product.")
            return p

    return stripe.Product.create(
        name="TreeSight Pro",
        description=(
            "TreeSight Pro subscription — geospatial satellite analysis with higher limits."
        ),
        metadata={"app": "treesight", "tier": "pro"},
    )


def _find_or_create_price(stripe, product_id: str, currency: str, unit_amount: int) -> object:
    """Find existing monthly price for this product+currency, or create one."""
    prices = stripe.Price.list(product=product_id, currency=currency, active=True, limit=20)
    for p in prices.auto_paging_iter():
        if p.unit_amount == unit_amount and p.recurring and p.recurring.interval == "month":
            return p

    return stripe.Price.create(
        product=product_id,
        unit_amount=unit_amount,
        currency=currency,
        recurring={"interval": "month"},
        tax_behavior="exclusive",
        metadata={"app": "treesight", "tier": "pro"},
    )


WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
]


def _find_or_create_webhook(stripe, url: str) -> object:
    """Find existing webhook for this URL, or create one."""
    endpoints = stripe.WebhookEndpoint.list(limit=20)
    for ep in endpoints.auto_paging_iter():
        if ep.url == url and ep.status != "disabled":
            # Update enabled events in case they changed
            stripe.WebhookEndpoint.modify(ep.id, enabled_events=WEBHOOK_EVENTS)
            return ep

    return stripe.WebhookEndpoint.create(
        url=url,
        enabled_events=WEBHOOK_EVENTS,
        description="TreeSight billing webhook",
        metadata={"app": "treesight"},
    )


def _create_portal_config(stripe, product_id: str) -> object:
    """Create (or update) the billing portal configuration.

    Stripe only allows one active portal config per account, so we always
    create a new one (which supersedes any prior config).
    """
    return stripe.billing_portal.Configuration.create(
        business_profile={
            "headline": "Manage your TreeSight subscription",
            "privacy_policy_url": "https://treesight.hrdcrprwn.com/privacy.html",
            "terms_of_service_url": "https://treesight.hrdcrprwn.com/terms.html",
        },
        features={
            "subscription_cancel": {
                "enabled": True,
                "mode": "at_period_end",
                "cancellation_reason": {
                    "enabled": True,
                    "options": [
                        "too_expensive",
                        "missing_features",
                        "switched_service",
                        "unused",
                        "other",
                    ],
                },
            },
            "subscription_update": {
                "enabled": False,
            },
            "payment_method_update": {
                "enabled": True,
            },
            "invoice_history": {
                "enabled": True,
            },
        },
        default_return_url="https://treesight.hrdcrprwn.com?billing=portal-return",
    )


if __name__ == "__main__":
    main()
