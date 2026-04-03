"""One-time: Create service principal + configure CIAM user flow for TreeSight SPA."""

import json
import sys
import urllib.request

from _graph import APP_ID, TENANT_ID, TENANT_NAME, TOKEN, graph


def main():
    if not TOKEN:
        print("ERROR: Set CIAM_TOKEN env var")
        sys.exit(1)

    # 1) Create service principal
    print("=== Creating service principal ===")
    sp = graph("POST", "/servicePrincipals", {"appId": APP_ID})
    if sp:
        print(f"Service principal created: {sp.get('id')}")
    else:
        print("Service principal may already exist, checking...")
        existing = graph("GET", f"/servicePrincipals?$filter=appId eq '{APP_ID}'")
        if existing and existing.get("value"):
            print(f"Found existing SP: {existing['value'][0]['id']}")

    # 2) Check OIDC discovery endpoint
    print("\n=== OIDC Discovery ===")
    oidc_url = (
        f"https://{TENANT_NAME}.ciamlogin.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
    )
    try:
        resp = urllib.request.urlopen(oidc_url)
        config = json.loads(resp.read())
        print(f"Issuer: {config.get('issuer')}")
        print(f"JWKS URI: {config.get('jwks_uri')}")
        print(f"Token endpoint: {config.get('token_endpoint')}")
        print(f"Authorization endpoint: {config.get('authorization_endpoint')}")
    except Exception as e:
        print(f"OIDC discovery not yet available: {e}")

    # 3) List identity providers (beta)
    print("\n=== Identity Providers ===")
    idps = graph("GET", "/identity/identityProviders", beta=True)
    if idps:
        for p in idps.get("value", []):
            name = p.get("displayName")
            kind = p.get("identityProviderType", p.get("@odata.type"))
            print(f"  - {name} ({kind})")

    # 4) List existing user flows (beta)
    print("\n=== Existing User Flows ===")
    flows = graph("GET", "/identity/authenticationEventsFlows", beta=True)
    if flows:
        for f in flows.get("value", []):
            print(f"  - {f.get('displayName')} ({f.get('id')})")
        if not flows.get("value"):
            print("  (none)")

    print("\nDone. App client ID for config:", APP_ID)


if __name__ == "__main__":
    main()
