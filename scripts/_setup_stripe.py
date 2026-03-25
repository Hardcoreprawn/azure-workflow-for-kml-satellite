"""One-time: Provision Stripe product, prices, webhook, and customer portal.

Usage:
    # First, store your Stripe test API key in Key Vault:
    #   az keyvault secret set --vault-name kv-kmlsat-dev \
    #       --name stripe-api-key --value "sk_test_..."
    #
    # Then run:
    python scripts/_setup_stripe.py --vault-name kv-kmlsat-dev

What it creates (in Stripe):
    1. Product: "TreeSight Pro" (monthly subscription)
    2. Three Prices: GBP £39, USD $49, EUR €45
    3. Webhook endpoint listening for billing events
    4. Customer Portal configuration (cancel, invoices, payment update)

What it writes (back to Key Vault):
    stripe-webhook-secret, stripe-price-id-pro-gbp, -usd, -eur

Idempotent: if a product named "TreeSight Pro" already exists, it reuses it.
"""

import argparse
import os
import subprocess
import sys
from typing import Any

_REQUIRED_PACKAGES = {
    "stripe": "stripe",
    "azure.identity": "azure-identity",
    "azure.keyvault.secrets": "azure-keyvault-secrets",  # pragma: allowlist secret
}


def _ensure_deps() -> None:
    """Auto-install missing Python packages."""
    missing = []
    for module, pkg in _REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision Stripe for TreeSight")
    parser.add_argument(
        "--vault-name",
        default=os.environ.get("VAULT_NAME", "kv-kmlsat-dev"),
        help="Azure Key Vault name (default: kv-kmlsat-dev)",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get("WEBHOOK_URL", ""),
        help="Stripe webhook URL. Auto-derived from Key Vault tags if omitted.",
    )
    args = parser.parse_args()

    # --- Prerequisites ---
    _ensure_deps()
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    vault_url = f"https://{args.vault_name}.vault.azure.net"
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    # --- Read Stripe API key from Key Vault ---
    print(f"\n=== Key Vault: {args.vault_name} ===")
    try:
        api_key = kv_client.get_secret("stripe-api-key").value or ""
    except Exception:
        print("ERROR: Could not read 'stripe-api-key' from Key Vault.")
        print(
            "  Store it first:  az keyvault secret set --vault-name "
            f"{args.vault_name} --name stripe-api-key --value 'sk_test_...'"
        )
        sys.exit(1)

    if not api_key:
        print("ERROR: 'stripe-api-key' secret is empty in Key Vault.")
        sys.exit(1)

    key_mode = "test" if api_key.startswith("sk_test_") else "live"
    print(f"  Stripe API key: {key_mode}-mode key loaded from Key Vault")

    if key_mode == "live":
        print("WARNING: This does not look like a test-mode key.")
        resp = input("Continue with live key? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            sys.exit(1)

    # --- Derive webhook URL from Function App hostname ---
    webhook_url = args.webhook_url
    if not webhook_url:
        webhook_url = _derive_webhook_url(args.vault_name)
    if not webhook_url:
        print("ERROR: Could not derive webhook URL. Pass --webhook-url explicitly.")
        sys.exit(1)
    print(f"  Webhook URL: {webhook_url}")

    import stripe

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
    webhook_secret = getattr(webhook, "secret", None)
    if webhook_secret:
        print("  Signing secret: (captured, will store in Key Vault)")
    else:
        print("  Signing secret: <already created — retrieve from Stripe Dashboard>")

    # ------------------------------------------------------------------
    # 4. Customer Portal
    # ------------------------------------------------------------------
    print("\n=== Customer Portal ===")
    portal = _create_portal_config(stripe, product.id)
    print(f"  Portal config ID: {portal.id}")

    # ------------------------------------------------------------------
    # 5. Tax note
    # ------------------------------------------------------------------
    print("\n=== Tax ===")
    print("  Stripe Tax is activated per-session via automatic_tax={'enabled': True}.")
    print("  No tax registration needed until turnover exceeds the VAT threshold (£90k).")
    print("  When you register: Stripe Dashboard → Tax → Registrations → add GB.")

    # ------------------------------------------------------------------
    # 6. Store results in Key Vault
    # ------------------------------------------------------------------
    print("\n=== Storing secrets in Key Vault ===")
    secret_names = ["stripe-price-id-pro-gbp", "stripe-price-id-pro-usd", "stripe-price-id-pro-eur"]
    secret_values = [price_ids["GBP"], price_ids["USD"], price_ids["EUR"]]
    if webhook_secret:
        secret_names.append("stripe-webhook-secret")
        secret_values.append(webhook_secret)

    for name, val in zip(secret_names, secret_values, strict=True):
        kv_client.set_secret(name, val)
        print(f"  ✓ {name}")

    print("\n=== Done ===")
    if not webhook_secret:
        print("  NOTE: webhook signing secret was not returned (already exists).")
        print("  If 'stripe-webhook-secret' is not yet in Key Vault, copy it from")
        print("  Stripe Dashboard → Developers → Webhooks → Signing secret.")
    print("  All other secrets stored in Key Vault. No manual steps needed.")


def _derive_webhook_url(vault_name: str) -> str:
    """Derive the webhook URL from the Function App in the same resource group."""
    import json
    import subprocess

    # Key Vault name follows kv-{project}-{env}, Function App is func-{project}-{env}
    suffix = vault_name.removeprefix("kv-")  # e.g. "kmlsat-dev"
    func_name = f"func-{suffix}"
    rg_name = f"rg-{suffix}"

    try:
        result = subprocess.run(
            [
                "az",
                "functionapp",
                "show",
                "--name",
                func_name,
                "--resource-group",
                rg_name,
                "--query",
                "defaultHostName",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            hostname = json.loads(result.stdout.strip())
            return f"https://{hostname}/api/billing/webhook"
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass  # Fall through to return empty — caller will prompt for manual URL
    return ""


def _find_or_create_product(stripe: Any) -> Any:
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


def _find_or_create_price(stripe: Any, product_id: str, currency: str, unit_amount: int) -> Any:
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


def _find_or_create_webhook(stripe: Any, url: str) -> Any:
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


def _create_portal_config(stripe: Any, product_id: str) -> Any:
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
