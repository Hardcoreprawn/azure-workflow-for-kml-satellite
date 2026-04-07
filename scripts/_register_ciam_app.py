"""One-time script: Register the Canopex SPA app in the CIAM tenant.

After initial registration, redirect URIs are kept in sync automatically
by sync_ciam_redirect_uris.py (called from the deploy workflow).
"""

import json
import sys

from _graph import TOKEN, graph


def main():
    if not TOKEN:
        print("ERROR: Set CIAM_TOKEN env var first")
        sys.exit(1)

    result = graph(
        "POST",
        "/applications",
        {
            "displayName": "Canopex SPA",
            "signInAudience": "AzureADandPersonalMicrosoftAccount",
            "spa": {
                # TODO: parameterise redirect URIs per environment instead of hardcoding
                "redirectUris": [
                    "http://localhost:4280",
                    "https://green-moss-0e849ac03.2.azurestaticapps.net",
                    "https://canopex.hrdcrprwn.com",
                ]
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
