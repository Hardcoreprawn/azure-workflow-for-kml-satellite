"""One-time: Create CIAM user flow and link app.

Supports email/password, Google, and Microsoft Account identity providers.
Run _setup_sso_providers.py first to register social providers in the tenant.
"""

import sys

from _graph import APP_ID, SP_ID, TENANT_ID, TENANT_NAME, TOKEN, graph


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
            "displayName": "Canopex Sign Up/In",
            "onInteractiveAuthFlowStart": {
                "@odata.type": "#microsoft.graph.onInteractiveAuthFlowStartExternalUsersSelfServiceSignUp",
                "isSignUpAllowed": True,
            },
            "onAuthenticationMethodLoadStart": {
                "@odata.type": "#microsoft.graph.onAuthenticationMethodLoadStartExternalUsersSelfServiceSignUp",
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
                "@odata.type": "#microsoft.graph.onAttributeCollectionExternalUsersSelfServiceSignUp",
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
                                    "validationRegEx": "^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\\.[a-zA-Z0-9-]+)*$",
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
        beta=True,
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
        beta=True,
    )
    if link is not None:
        print("App linked to user flow successfully")
    else:
        print("Failed to link app to user flow")

    print("\n=== Summary ===")
    print(f"Tenant: {TENANT_NAME}.onmicrosoft.com")
    print(f"Tenant ID: {TENANT_ID}")
    print(f"App client ID: {APP_ID}")
    print(f"User flow ID: {flow_id}")
    print(f"Authority: https://{TENANT_NAME}.ciamlogin.com/")
    print(
        f"OIDC config: https://{TENANT_NAME}.ciamlogin.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
    )


if __name__ == "__main__":
    main()
