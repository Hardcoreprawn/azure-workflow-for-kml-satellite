"""One-time script: Register the Canopex app in the CIAM tenant.

DEPRECATED: The CIAM app registration is now managed by OpenTofu
(infra/tofu/ciam.tf).  Use ``tofu apply`` instead of running this script.
This script is retained only as a historical reference.

SWA built-in auth uses the server-side OpenID Connect flow, so the app
must be registered as a **web** application (not SPA).  The redirect URI
``/.auth/login/aad/callback`` is handled by the SWA platform.

This script bootstraps the initial web application registration only.
If SWA hostnames change later, update the CIAM app's web redirect URIs
and related auth settings separately; this module does not keep them in
sync automatically.
"""

from __future__ import annotations

import json
import sys

from _graph import TOKEN, graph


def main() -> None:
    if not TOKEN:
        print("ERROR: Set CIAM_TOKEN env var first")
        sys.exit(1)

    result = graph(
        "POST",
        "/applications",
        {
            "displayName": "Canopex",
            "signInAudience": "AzureADandPersonalMicrosoftAccount",
            # SWA built-in auth uses server-side OIDC — register as "web", not "spa".
            # The /.auth/login/aad/callback path is managed by the SWA platform.
            "web": {
                # TODO: parameterise redirect URIs per environment instead of hardcoding
                "redirectUris": [
                    "http://localhost:4280/.auth/login/aad/callback",
                    "https://green-moss-0e849ac03.2.azurestaticapps.net/.auth/login/aad/callback",
                    "https://canopex.hrdcrprwn.com/.auth/login/aad/callback",
                ],
                "implicitGrantSettings": {
                    "enableIdTokenIssuance": True,
                },
            },
            "requiredResourceAccess": [
                {
                    "resourceAppId": "00000003-0000-0000-c000-000000000000",  # Microsoft Graph
                    "resourceAccess": [
                        {
                            "id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
                            "type": "Scope",
                        },  # User.Read
                        {"id": "37f7f235-527c-4136-accd-4a02d197296e", "type": "Scope"},  # openid
                        {"id": "14dad69e-099b-42c9-810b-d002981feec1", "type": "Scope"},  # profile
                    ],
                }
            ],
        },
    )
    if result is None:
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
