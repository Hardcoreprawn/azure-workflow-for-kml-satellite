"""Patch the CIAM app registration for SWA built-in auth.

The original registration used the SPA platform, but SWA built-in auth
uses server-side OIDC which sends ``response_type=id_token``.  This
requires:

1. Redirect URIs under the **web** platform (not SPA)
2. ``enableIdTokenIssuance = true`` on the web platform

Without this patch the CIAM tenant rejects sign-in with:
    AADSTS700054: response_type 'id_token' is not enabled for the application

Usage:
    CIAM_TOKEN="<bearer-token>" python scripts/patch_ciam_web_redirect.py

The bearer token must have Application.ReadWrite.All permission on the
CIAM tenant.  Obtain one from https://developer.microsoft.com/graph/graph-explorer
or via ``az account get-access-token --resource https://graph.microsoft.com``.
"""

from __future__ import annotations

import json
import sys

from _graph import APP_OBJECT_ID, TOKEN, graph


def main() -> None:
    if not TOKEN:
        print("ERROR: Set CIAM_TOKEN env var first")
        sys.exit(1)

    # Step 1: Read the current app registration
    app = graph("GET", f"/applications/{APP_OBJECT_ID}")
    if app is None:
        print("Failed to read current app registration")
        sys.exit(1)

    print(
        "Current SPA redirectUris:",
        json.dumps(app.get("spa", {}).get("redirectUris", []), indent=2),
    )
    print(
        "Current Web redirectUris:",
        json.dumps(app.get("web", {}).get("redirectUris", []), indent=2),
    )
    print(
        "Current implicitGrantSettings:",
        json.dumps(app.get("web", {}).get("implicitGrantSettings", {}), indent=2),
    )

    # Step 2: Patch — move redirect URIs to web platform with ID token grant
    # SWA built-in auth callback path is always /.auth/login/aad/callback
    web_redirect_uris = [
        "http://localhost:4280/.auth/login/aad/callback",
        "https://green-moss-0e849ac03.2.azurestaticapps.net/.auth/login/aad/callback",
        "https://canopex.hrdcrprwn.com/.auth/login/aad/callback",
    ]

    result = graph(
        "PATCH",
        f"/applications/{APP_OBJECT_ID}",
        {
            # Clear SPA redirect URIs — SWA doesn't use the SPA platform
            "spa": {"redirectUris": []},
            # Set web platform with correct callback URIs + ID token grant
            "web": {
                "redirectUris": web_redirect_uris,
                "implicitGrantSettings": {
                    "enableIdTokenIssuance": True,
                },
            },
        },
    )

    if result is None:
        print("PATCH failed — see error above")
        sys.exit(1)

    print("\nPATCH succeeded.")
    print("Web redirectUris set to:", json.dumps(web_redirect_uris, indent=2))
    print("enableIdTokenIssuance: true")
    print("\nSign-in should work now. Test at: https://canopex.hrdcrprwn.com/.auth/login/aad")


if __name__ == "__main__":
    main()
