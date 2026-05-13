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

Bearer-token authentication is mandatory. All public CIAM values
(`ciam_tenant_subdomain`, `ciam_tenant_id`, `ciam_client_id`,
`ciam_api_audience`) live in `environments/<env>.tfvars` — they ship in the
deployed page HTML and in JWTs the SPA hands to the API, so they are not
secrets. Tofu surfaces them as plain Function App app settings and as a
`ciam_page_config` output that the SWA deploy step injects into the page HTML
at deploy time. Key Vault is no longer used for these values.

The only CIAM-related GitHub Environment secret you must set is:

- `TF_VAR_CIAM_DEPLOY_CLIENT_ID` — *Optional.* Client ID of a service
  principal **in the CIAM tenant** that has `Application.ReadWrite.OwnedBy`
  permission and is an Owner of the SPA app, with a federated GitHub OIDC
  credential trusting `repo:<owner>/<repo>:environment:<env>`. When set, Tofu
  manages the SPA app's redirect URIs (`azuread_application_redirect_uris`).
  When unset, redirect URI registration is skipped silently — see
  "CIAM deploy SP bootstrap" below.

The Function App validates the CIAM settings at startup and fails fast if any
are missing.

## CIAM deploy SP bootstrap (one-time, done)

**Status (May 2026):** Bootstrap complete. Deploy SP `canopex-tofu-deploy`
(appId `3753e9c8-8969-443a-9377-a7716f1f25a5`) exists in CIAM tenant
`92001438-8b42-4bd7-950f-0ed1775f87b7` with `Application.ReadWrite.OwnedBy`
(admin-consented), Owner of SPA app `6e2abd0a-…`, and federated GitHub OIDC
credentials for `repo:Hardcoreprawn/azure-workflow-for-kml-satellite:environment:{dev,prd}`.
Both GitHub Environments have `TF_VAR_CIAM_DEPLOY_CLIENT_ID` set. Tofu now
manages `azuread_application_redirect_uris.ciam_spa[0]` from
`local.ciam_spa_redirect_uris` in `locals.tf`.

If the deploy SP needs to be re-created (e.g. for a new tenant or rotated):

1. `az login --tenant <CIAM_TENANT_ID> --allow-no-subscriptions` as a CIAM
   tenant admin (typically the tenant owner identity).
2. Create the deploy SP in the CIAM tenant: `az ad app create --display-name
   "Canopex Tofu Deploy"`. Note its `appId` (this is `TF_VAR_CIAM_DEPLOY_CLIENT_ID`).
3. Grant it `Application.ReadWrite.OwnedBy` on Microsoft Graph and admin-consent.
4. Add it as an Owner of the SPA app (`6e2abd0a-…`) via Microsoft Graph
   (`POST /applications/<spa-objectId>/owners/$ref`).
5. Add a federated credential on the deploy SP for each GitHub Environment:
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:<owner>/<repo>:environment:<env>`
   - Audience: `api://AzureADTokenExchange`
6. Set `TF_VAR_CIAM_DEPLOY_CLIENT_ID` in the matching GitHub Environment.

For an emergency redirect-URI fix without running Tofu (e.g. to add a new
origin immediately), after step 1 above:

```bash
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/<spa-objectId>" \
  --headers "Content-Type=application/json" \
  --body '{"spa":{"redirectUris":["https://canopex.hrdcrprwn.com/", ...]}}'
```

## Local Usage

```bash
tofu init \
  -backend-config="resource_group_name=<TF_STATE_RESOURCE_GROUP>" \
  -backend-config="storage_account_name=<TF_STATE_STORAGE_ACCOUNT>" \
  -backend-config="container_name=<TF_STATE_CONTAINER>" \
  -backend-config="key=kml-satellite-dev.tfstate"

# Bearer-only auth: all CIAM values (tenant_id, authority, client_id,
# api_audience) come from <env>.tfvars. Only deploy_client_id is a secret.
tofu plan \
  -var "subscription_id=<SUBSCRIPTION_ID>" \
  -var "deploy_principal_client_id=<AZURE_CLIENT_ID>" \
  -var-file="environments/dev.tfvars"

tofu apply -var "subscription_id=<SUBSCRIPTION_ID>" -var "deploy_principal_client_id=<AZURE_CLIENT_ID>" -var-file="environments/dev.tfvars"
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
