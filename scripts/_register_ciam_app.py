"""One-time script: Register the TreeSight SPA app in the CIAM tenant."""
import json
import os
import sys
import urllib.request
import urllib.error


def main():
    token = os.environ.get("CIAM_TOKEN")
    if not token:
        print("ERROR: Set CIAM_TOKEN env var first")
        sys.exit(1)

    data = json.dumps({
        "displayName": "TreeSight SPA",
        "signInAudience": "AzureADandPersonalMicrosoftAccount",
        "spa": {
            "redirectUris": [
                "http://localhost:4280",
                "https://polite-glacier-0d6885003.4.azurestaticapps.net",
            ]
        },
        "requiredResourceAccess": [
            {
                "resourceAppId": "00000003-0000-0000-c000-000000000000",
                "resourceAccess": [
                    {"id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d", "type": "Scope"},
                    {"id": "37f7f235-527c-4136-accd-4a02d197296e", "type": "Scope"},
                    {"id": "14dad69e-099b-42c9-810b-d002981feec1", "type": "Scope"},
                ],
            }
        ],
    }).encode()

    req = urllib.request.Request(
        "https://graph.microsoft.com/v1.0/applications",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        print(json.dumps(result, indent=2))
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"ERROR {e.code}: {body}")
        sys.exit(1)


if __name__ == "__main__":
    main()
