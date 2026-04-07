"""One-time: Grant the deploy SP access to the CIAM tenant for redirect URI management.

Prerequisites:
  1. You must be a Global Administrator in the CIAM tenant (treesightauth).
  2. The deploy service principal must already exist in the subscription tenant.
  3. Set CIAM_TOKEN to a Graph API bearer token for the CIAM tenant
     (get one from https://developer.microsoft.com/graph/graph-explorer
      scoped to the CIAM tenant, with Application.ReadWrite.All).

What this script does:
  1. Consents the deploy SP into the CIAM tenant (creates a service principal).
  2. Adds an OIDC federation credential for the GitHub repo.
  3. Grants Application.ReadWrite.OwnedBy so the SP can update the Canopex SPA
     app registration's redirect URIs at deploy time.

After running this, the deploy workflow can authenticate to the CIAM tenant
using OIDC (no stored secrets) and sync redirect URIs automatically.

Usage:
  CIAM_TOKEN=<token> DEPLOY_CLIENT_ID=<sp-client-id> python scripts/setup_ciam_deploy_access.py

Environment:
  CIAM_TOKEN         — Bearer token with admin consent rights in CIAM tenant
  DEPLOY_CLIENT_ID   — Client ID of the deploy service principal (AZURE_CLIENT_ID)
  GITHUB_REPO        — Optional, defaults to Hardcoreprawn/azure-workflow-for-kml-satellite
"""

from __future__ import annotations

import os
import sys

# Re-use the graph helper from the existing CIAM scripts
sys.path.insert(0, os.path.dirname(__file__))
from _graph import APP_OBJECT_ID, TENANT_ID, graph

GITHUB_REPO = os.environ.get("GITHUB_REPO", "Hardcoreprawn/azure-workflow-for-kml-satellite")

# Microsoft Graph app role: Application.ReadWrite.OwnedBy
# This is the least-privilege role that allows updating apps the SP owns.
APP_READWRITE_OWNED_BY_ROLE_ID = "18a4783c-866b-4cc7-a460-3d5e5662c884"
GRAPH_RESOURCE_ID = "00000003-0000-0000-c000-000000000000"


def main() -> int:
    token = os.environ.get("CIAM_TOKEN", "")
    deploy_client_id = os.environ.get("DEPLOY_CLIENT_ID", "")

    if not token:
        print("ERROR: Set CIAM_TOKEN env var (Graph API token for the CIAM tenant)")
        return 1
    if not deploy_client_id:
        print("ERROR: Set DEPLOY_CLIENT_ID env var (the deploy SP's client/app ID)")
        return 1

    # ── 1. Consent deploy SP into CIAM tenant ──
    print("=== Step 1: Consent deploy SP into CIAM tenant ===")
    sp = graph("POST", "/servicePrincipals", {"appId": deploy_client_id})
    if sp:
        sp_object_id = sp["id"]
        print(f"  Created service principal: {sp_object_id}")
    else:
        # May already exist
        existing = graph("GET", f"/servicePrincipals?$filter=appId eq '{deploy_client_id}'")
        if existing and existing.get("value"):
            sp_object_id = existing["value"][0]["id"]
            print(f"  Service principal already exists: {sp_object_id}")
        else:
            print("  ERROR: Could not create or find service principal")
            return 1

    # ── 2. Add OIDC federation credential ──
    print("\n=== Step 2: Add OIDC federation credential ===")
    # Check for existing federation credentials
    existing_creds = graph("GET", f"/applications?$filter=appId eq '{deploy_client_id}'&$select=id")
    if not existing_creds or not existing_creds.get("value"):
        print("  NOTE: The deploy app registration is in a different tenant.")
        print("  OIDC federation must be configured on the app registration in its home tenant.")
        print("  If the app is multi-tenant, this SP will automatically trust the federation")
        print("  credentials configured in the home tenant.")
        print()
        print("  Ensure the app registration in the subscription tenant has:")
        print("    - signInAudience: AzureADMultipleOrgs")
        print(f"    - Federated credential for: repo:{GITHUB_REPO}:environment:dev")
    else:
        app_object_id = existing_creds["value"][0]["id"]
        fed_cred = graph(
            "POST",
            f"/applications/{app_object_id}/federatedIdentityCredentials",
            {
                "name": f"github-deploy-ciam-{GITHUB_REPO.split('/')[-1]}",
                "issuer": "https://token.actions.githubusercontent.com",
                "subject": f"repo:{GITHUB_REPO}:environment:dev",
                "audiences": ["api://AzureADTokenExchange"],
                "description": "GitHub Actions OIDC for deploy workflow (CIAM tenant)",
            },
        )
        if fed_cred:
            print(f"  Added federation credential: {fed_cred.get('id')}")
        else:
            print("  Federation credential may already exist (or requires home tenant config)")

    # ── 3. Make SP owner of the Canopex SPA app ──
    print("\n=== Step 3: Add deploy SP as owner of Canopex SPA app ===")
    owner_ref = f"https://graph.microsoft.com/v1.0/directoryObjects/{sp_object_id}"
    result = graph(
        "POST",
        f"/applications/{APP_OBJECT_ID}/owners/$ref",
        {"@odata.id": owner_ref},
    )
    if result is not None:
        print("  Added deploy SP as owner of Canopex SPA app")
    else:
        # Check if already owner
        owners = graph("GET", f"/applications/{APP_OBJECT_ID}/owners?$select=id")
        if owners and any(o.get("id") == sp_object_id for o in owners.get("value", [])):
            print("  Deploy SP is already an owner")
        else:
            print("  WARNING: Could not add owner. You may need to do this manually.")

    # ── 4. Grant Application.ReadWrite.OwnedBy (app role) ──
    print("\n=== Step 4: Grant Application.ReadWrite.OwnedBy ===")
    # Find the Graph SP in CIAM tenant
    graph_sp = graph("GET", f"/servicePrincipals?$filter=appId eq '{GRAPH_RESOURCE_ID}'")
    if not graph_sp or not graph_sp.get("value"):
        print("  ERROR: Could not find Microsoft Graph service principal in CIAM tenant")
        return 1
    graph_sp_id = graph_sp["value"][0]["id"]

    role_assignment = graph(
        "POST",
        f"/servicePrincipals/{sp_object_id}/appRoleAssignments",
        {
            "principalId": sp_object_id,
            "resourceId": graph_sp_id,
            "appRoleId": APP_READWRITE_OWNED_BY_ROLE_ID,
        },
    )
    if role_assignment:
        print("  Granted Application.ReadWrite.OwnedBy")
    else:
        print("  Role may already be assigned (or requires admin consent)")

    # ── Summary ──
    print("\n=== Summary ===")
    print(f"  CIAM Tenant ID:      {TENANT_ID}")
    print(f"  Deploy SP Client ID: {deploy_client_id}")
    print(f"  Deploy SP Object ID: {sp_object_id}")
    print(f"  Canopex App Object:  {APP_OBJECT_ID}")
    print()
    print("  Next steps:")
    print(
        "  1. Ensure the deploy app registration is multi-tenant (signInAudience: AzureADMultipleOrgs)"
    )
    print(f"  2. Add CIAM_TENANT_ID={TENANT_ID} to the 'dev' environment secrets in GitHub")
    print("  3. The deploy workflow will now use OIDC to authenticate to the CIAM tenant")
    print("  4. No CIAM_TOKEN secret needed — the workflow acquires tokens via OIDC")

    return 0


if __name__ == "__main__":
    sys.exit(main())
