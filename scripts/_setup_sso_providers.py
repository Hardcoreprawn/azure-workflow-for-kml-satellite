"""Register social identity providers (Google, Microsoft) in the CIAM tenant.

Prerequisites:
  - CIAM_TOKEN env var: Graph API bearer token with IdentityProvider.ReadWrite.All
  - GOOGLE_CLIENT_ID env var: OAuth client ID from Google Cloud Console
  - GOOGLE_CLIENT_SECRET env var: OAuth client secret from Google Cloud Console

Run once per tenant, or to verify existing configuration.

Usage:
  CIAM_TOKEN=... GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... \\
    python scripts/_setup_sso_providers.py
"""

import os
import sys

from _graph import TENANT_NAME, TOKEN, graph


def list_providers():
    """List all identity providers in the tenant."""
    result = graph("GET", "/identity/identityProviders", beta=True)
    providers = {}
    if result:
        for p in result.get("value", []):
            ptype = p.get("identityProviderType", p.get("@odata.type", ""))
            display = p.get("displayName", "")
            pid = p.get("id", "")
            providers[ptype] = pid
            print(f"  - {display} (type={ptype}, id={pid})")
    return providers


def setup_google():
    """Register Google as a social identity provider."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("SKIP: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not set")
        print("  To create Google OAuth credentials:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Create an OAuth 2.0 Client ID (Web application)")
        print("  3. Add authorized redirect URI:")
        print(
            f"     https://{TENANT_NAME}.ciamlogin.com/{TENANT_NAME}.onmicrosoft.com/federation/oauth2"
        )
        print("  4. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars")
        return False

    result = graph(
        "POST",
        "/identity/identityProviders",
        {
            "@odata.type": "#microsoft.graph.socialIdentityProvider",
            "displayName": "Google",
            "identityProviderType": "Google",
            "clientId": client_id,
            "clientSecret": client_secret,
        },
        beta=True,
    )
    if result and result.get("id"):
        print(f"Google provider created: id={result['id']}")
        return True
    print("Failed to create Google provider (may already exist)")
    return False


def setup_microsoft():
    """Enable Microsoft Account as a built-in identity provider.

    In Entra External ID, the Microsoft Account provider is built-in
    and available without additional client credentials.
    """
    # Microsoft Account is a built-in provider — it doesn't need to be
    # created, just referenced in the user flow.  Verify it exists.
    result = graph("GET", "/identity/identityProviders", beta=True)
    if result:
        for p in result.get("value", []):
            if p.get("identityProviderType") == "MicrosoftAccount":
                print(f"Microsoft Account provider already available: id={p['id']}")
                return True

    # If not found, it may need to be enabled via portal or created.
    print("Microsoft Account provider not found in tenant.")
    print("  In Entra External ID, navigate to:")
    print("  Identity > External Identities > All identity providers")
    print("  and enable 'Microsoft Account'.")
    return False


def main():
    if not TOKEN:
        print("ERROR: Set CIAM_TOKEN env var")
        sys.exit(1)

    print("=== Current Identity Providers ===")
    providers = list_providers()
    if not providers:
        print("  (none found)")

    print("\n=== Setting Up Google SSO ===")
    if "Google" in providers:
        print(f"Google already registered: id={providers['Google']}")
    else:
        setup_google()

    print("\n=== Verifying Microsoft Account ===")
    setup_microsoft()

    print("\n=== Enterprise Federation (M365 / Entra ID) ===")
    print("Enterprise SSO requires per-organization configuration:")
    print("  1. Azure Portal > Entra External ID > Cross-tenant access")
    print("  2. Add organization tenant by domain or tenant ID")
    print("  3. Configure inbound trust settings")
    print("  4. Users from that org can then sign in with work accounts")
    print("  See: https://learn.microsoft.com/entra/external-id/cross-tenant-access-overview")

    print("\n=== Updated Provider List ===")
    list_providers()

    print("\nNext step: Run _create_user_flow.py to link providers to the user flow.")


if __name__ == "__main__":
    main()
