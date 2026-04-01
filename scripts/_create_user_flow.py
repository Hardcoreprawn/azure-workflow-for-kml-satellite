"""One-time: Create CIAM user flow and link app.

Supports email/password, Google, and Microsoft Account identity providers.
Run _setup_sso_providers.py first to register social providers in the tenant.
"""

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("CIAM_TOKEN")
APP_ID = "6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6"
SP_ID = "1d43a846-7f56-46b3-b72b-6309c40a3bd7"


def graph(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"https://graph.microsoft.com/beta{path}",
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
            return {"_status": 204}
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"ERROR {e.code} on {method} {path}:")
        try:
            print(json.dumps(json.loads(body_text), indent=2))
        except Exception:
            print(body_text)
        return None


def main():
    if not TOKEN:
        print("ERROR: Set CIAM_TOKEN env var")
        sys.exit(1)

    # 1) Create external users self-service sign up flow
    print("=== Creating User Flow ===")
    flow = graph(
        "POST",
        "/identity/authenticationEventsFlows",
        {
            "@odata.type": "#microsoft.graph.externalUsersSelfServiceSignUpEventsFlow",
            "displayName": "TreeSight Sign Up/In",
            "onInteractiveAuthFlowStart": {
                "@odata.type": "#microsoft.graph.onInteractiveAuthFlowStartExternalUsersSelfServiceSignUp",  # noqa: E501
                "isSignUpAllowed": True,
            },
            "onAuthenticationMethodLoadStart": {
                "@odata.type": "#microsoft.graph.onAuthenticationMethodLoadStartExternalUsersSelfServiceSignUp",  # noqa: E501
                "identityProviders": [
                    {
                        "@odata.type": "#microsoft.graph.builtInIdentityProvider",
                        "id": "EmailPassword-OAUTH",
                    },
                    {
                        "@odata.type": "#microsoft.graph.builtInIdentityProvider",
                        "id": "MicrosoftAccount",
                    },
                    {
                        "@odata.type": "#microsoft.graph.socialIdentityProvider",
                        "id": "Google-OAUTH",
                    },
                ],
            },
            "onAttributeCollection": {
                "@odata.type": "#microsoft.graph.onAttributeCollectionExternalUsersSelfServiceSignUp",  # noqa: E501
                "attributes": [
                    {
                        "id": "email",
                        "displayName": "Email Address",
                        "description": "Email address of the user",
                        "userFlowAttributeType": "builtIn",
                        "dataType": "string",
                    },
                    {
                        "id": "displayName",
                        "displayName": "Display Name",
                        "description": "Display Name of the User.",
                        "userFlowAttributeType": "builtIn",
                        "dataType": "string",
                    },
                ],
                "attributeCollectionPage": {
                    "customStringsFileId": None,
                    "views": [
                        {
                            "title": None,
                            "description": None,
                            "inputs": [
                                {
                                    "attribute": "email",
                                    "label": "Email Address",
                                    "inputType": "text",
                                    "defaultValue": None,
                                    "hidden": True,
                                    "editable": False,
                                    "writeToDirectory": True,
                                    "required": True,
                                    "validationRegEx": "^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\\.[a-zA-Z0-9-]+)*$",  # noqa: E501
                                },
                                {
                                    "attribute": "displayName",
                                    "label": "Display Name",
                                    "inputType": "text",
                                    "defaultValue": None,
                                    "hidden": False,
                                    "editable": True,
                                    "writeToDirectory": True,
                                    "required": True,
                                    "validationRegEx": "^.*",
                                },
                            ],
                        }
                    ],
                },
            },
        },
    )

    if not flow:
        print("Failed to create user flow")
        sys.exit(1)

    flow_id = flow.get("id")
    print(f"User flow created: {flow_id}")

    # 2) Link the SPA app to the user flow
    print("\n=== Linking App to User Flow ===")
    link = graph(
        "POST",
        f"/identity/authenticationEventsFlows/{flow_id}/conditions/applications/includeApplications/$ref",
        {"@odata.id": f"https://graph.microsoft.com/beta/servicePrincipals/{SP_ID}"},
    )
    if link is not None:
        print("App linked to user flow successfully")
    else:
        print("Failed to link app to user flow")

    print("\n=== Summary ===")
    print("Tenant: treesightauth.onmicrosoft.com")
    print("Tenant ID: 92001438-8b42-4bd7-950f-0ed1775f87b7")
    print(f"App client ID: {APP_ID}")
    print(f"User flow ID: {flow_id}")
    print("Authority: https://treesightauth.ciamlogin.com/")
    print(
        "OIDC config: https://treesightauth.ciamlogin.com/92001438-8b42-4bd7-950f-0ed1775f87b7/v2.0/.well-known/openid-configuration"
    )


if __name__ == "__main__":
    main()
