# OpenTofu Infrastructure

This directory is the new Azure infrastructure source of truth for `dev` and `prd`.

## Ownership Rule

- `infra/tofu` owns all Azure resources for migrated environments.
- Do not run Bicep deployments against the same environment after cutover.

## Bootstrap (manual, one-time)

Create backend state resources before running OpenTofu in CI/CD:

1. Resource group for state (example): `rg-kmlsat-tofu-state`
2. Storage account for state (example): `stkmlsattofustate`
3. Blob container (example): `tfstate`
4. OIDC-enabled service principal/federated credential for GitHub Actions

You can automate this bootstrap with:

- `scripts/bootstrap_tofu_backend_and_oidc.ps1`

Example:

```powershell
./scripts/bootstrap_tofu_backend_and_oidc.ps1 \
  -SubscriptionId <SUBSCRIPTION_ID> \
  -TenantId <TENANT_ID> \
  -GitHubOwner <OWNER> \
  -GitHubRepo <REPO>
```

The script creates:

- state resource group
- state storage account + container
- Entra app registration + service principal
- federated credentials for `dev` and `prd` GitHub environments

Use that same GitHub Actions app registration client ID as `deploy_principal_client_id` whenever OpenTofu needs to manage CMK-backed storage resources.

## Required GitHub Environment Secrets

Configure for each environment (`dev`, `prd`):

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `TF_STATE_RESOURCE_GROUP`
- `TF_STATE_STORAGE_ACCOUNT`
- `TF_STATE_CONTAINER`
- `TF_STATE_KEY`

## Required GitHub Environment Secrets (CIAM/Bearer Token Auth)

Bearer-token authentication is mandatory. The CIAM tenant_id, authority, and
client_id are public values committed to `environments/<env>.tfvars`. Tofu
populates them as Key Vault secrets (`ciam-tenant-id`, `ciam-authority`,
`ciam-client-id`, `ciam-api-audience`) so both the Function App (via
`@Microsoft.KeyVault` env refs) and the SWA deploy step (via `az keyvault
secret show`) read from a single source of truth.

The remaining secrets you must set in each GitHub Environment are:

- `TF_VAR_CIAM_API_AUDIENCE` — API audience (Application ID URI) from the CIAM
  app registration's "Expose an API" blade. Required for JWT validation. Kept
  as a secret only because we have not confirmed its value is OK to commit.
- `TF_VAR_CIAM_DEPLOY_CLIENT_ID` — *Optional.* Client ID of a service
  principal **in the CIAM tenant** that has `Application.ReadWrite.OwnedBy`
  permission and is an Owner of the SPA app, with a federated GitHub OIDC
  credential trusting `repo:<owner>/<repo>:environment:<env>`. When set, Tofu
  manages the SPA app's redirect URIs (`azuread_application_redirect_uris`).
  When unset, redirect URI registration is skipped silently — see
  "CIAM deploy SP bootstrap" below.

The Function App validates the CIAM settings at startup and fails fast if any
are missing or unreadable from Key Vault.

## CIAM deploy SP bootstrap (one-time, manual)

To enable Tofu management of the CIAM SPA app's redirect URIs, a service
principal in the CIAM tenant is required (the workforce-tenant deploy SP
cannot manage CIAM-tenant resources). Until this is automated:

1. `az login --tenant <CIAM_TENANT_ID> --allow-no-subscriptions` as a CIAM
   tenant admin (typically the tenant owner identity).
2. Create the deploy SP in the CIAM tenant: `az ad app create --display-name
   "Canopex Tofu Deploy"`. Note its `appId` (this is `TF_VAR_CIAM_DEPLOY_CLIENT_ID`).
3. Grant it `Application.ReadWrite.OwnedBy` on Microsoft Graph and admin-consent.
4. Add it as an Owner of the SPA app (`6e2abd0a-…`):
   `az ad app owner add --id <SPA_APP_ID> --owner-object-id <DEPLOY_SP_OBJECT_ID>`.
5. Add a federated credential on the deploy SP for each GitHub Environment:
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:<owner>/<repo>:environment:<env>`
   - Audience: `api://AzureADTokenExchange`
6. Set `TF_VAR_CIAM_DEPLOY_CLIENT_ID` in the matching GitHub Environment.

Until step 6 is done, redirect URIs in the CIAM SPA app are not reconciled by
Tofu. To unblock sign-in for a new origin manually, run (after step 1):

```bash
az ad app update --id 6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6 \
  --set spa.redirectUris='["https://canopex.hrdcrprwn.com/","https://canopex.hrdcrprwn.com/app/","https://canopex.hrdcrprwn.com/eudr/"]'
```

## Local Usage

```bash
tofu init \
  -backend-config="resource_group_name=<TF_STATE_RESOURCE_GROUP>" \
  -backend-config="storage_account_name=<TF_STATE_STORAGE_ACCOUNT>" \
  -backend-config="container_name=<TF_STATE_CONTAINER>" \
  -backend-config="key=kml-satellite-dev.tfstate"

# Bearer-only auth (CIAM tenant_id, authority, client_id come from <env>.tfvars).
# Only api_audience is overridden via -var because it's not committed.
tofu plan \
  -var "subscription_id=<SUBSCRIPTION_ID>" \
  -var "deploy_principal_client_id=<AZURE_CLIENT_ID>" \
  -var "ciam_api_audience=<API_APP_ID_URI>" \
  -var-file="environments/dev.tfvars"

tofu apply -var "subscription_id=<SUBSCRIPTION_ID>" -var "deploy_principal_client_id=<AZURE_CLIENT_ID>" -var "ciam_api_audience=<API_APP_ID_URI>" -var-file="environments/dev.tfvars"
```

## Clean-Slate Migration Sequence (dev)

1. Open a PR with the infra/deploy changes you want to validate.
2. Manually delete the app-managed resources in `rg-kmlsat-dev` while preserving shared/bootstrap resources such as Key Vault.
3. Run the `Deploy` workflow on that PR branch using `workflow_dispatch` with `rebuild_after_manual_teardown=true`.
4. The workflow prunes stale `azapi` state for the manually deleted resources, reapplies `environments/dev.tfvars`, deploys the new image, reconciles the Event Grid webhook subscription, and validates the infra gate.
5. Confirm the website deployment completes and validate any product-path smoke checks you care about beyond the infra gate.

Supporting helpers:

- `scripts/reconcile_eventgrid_subscription.py` restores the blob-trigger webhook subscription using the current function host key.
- `scripts/validate_dev_infra_gate.py` checks health/readiness, Event Grid endpoint wiring, and the Log Analytics daily cap.

## Notes

- Function App on Container Apps and the Event Grid system topic are created via `azapi` resources for parity with current ARM/Bicep behavior.
- While the azapi identity-update bug remains, mutable Function App settings are applied via CLI from Terraform outputs so `infra/tofu` stays the single source of truth instead of the workflow reparsing tfvars.
- The deploy workflow verifies the live Function App contract after CLI mutation (app settings + container image) against OpenTofu outputs and fails fast on mismatch to surface drift in CI/review.
- The deploy workflow owns Event Grid webhook subscription reconciliation because it can verify host readiness, trigger indexing, and current webhook keys before making the subscription live.
- `enable_event_grid_subscription` defaults to `false` to avoid OpenTofu racing runtime indexing or publishing a stale webhook key.
- OpenTofu references Stripe secrets by stable Key Vault secret names only. The actual Stripe values are bootstrap/operator-managed by the setup scripts and must not be passed through tfvars or Terraform variables.
