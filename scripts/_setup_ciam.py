"""One-time: Create service principal + configure CIAM user flow for TreeSight SPA."""
import json
import os
import sys
import urllib.request
import urllib.error

TOKEN = os.environ.get("CIAM_TOKEN")
APP_ID = "6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6"
APP_OBJECT_ID = "7ce73a2a-b80a-4b6f-afb7-eccf74bfaf47"


def graph(method, path, body=None, beta=False):
    base = "https://graph.microsoft.com/beta" if beta else "https://graph.microsoft.com/v1.0"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        resp = urllib.request.urlopen(req)
        if resp.status == 204:
            return None
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"ERROR {e.code} on {method} {path}: {body_text}")
        return None


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
    import urllib.request as ur
    oidc_url = "https://treesightauth.ciamlogin.com/92001438-8b42-4bd7-950f-0ed1775f87b7/v2.0/.well-known/openid-configuration"
    try:
        resp = ur.urlopen(oidc_url)
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
            print(f"  - {p.get('displayName')} ({p.get('identityProviderType', p.get('@odata.type'))})")

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
