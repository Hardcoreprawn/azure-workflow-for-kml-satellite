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

## Required GitHub Environment Secrets

Configure for each environment (`dev`, `prd`):

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `TF_STATE_RESOURCE_GROUP`
- `TF_STATE_STORAGE_ACCOUNT`
- `TF_STATE_CONTAINER`
- `TF_STATE_KEY`

## Local Usage

```bash
tofu init \
  -backend-config="resource_group_name=<TF_STATE_RESOURCE_GROUP>" \
  -backend-config="storage_account_name=<TF_STATE_STORAGE_ACCOUNT>" \
  -backend-config="container_name=<TF_STATE_CONTAINER>" \
  -backend-config="key=kml-satellite-dev.tfstate"

tofu plan -var "subscription_id=<SUBSCRIPTION_ID>" -var-file="environments/dev.tfvars"
tofu apply -var "subscription_id=<SUBSCRIPTION_ID>" -var-file="environments/dev.tfvars"
```

## Clean-Slate Migration Sequence (dev)

1. Open a PR with the infra/deploy changes you want to validate.
2. Manually delete the app-managed resources in `rg-kmlsat-dev` while preserving shared/bootstrap resources such as the CIAM directory and Key Vault.
3. Run the `Deploy` workflow on that PR branch using `workflow_dispatch` with `rebuild_after_manual_teardown=true`.
4. The workflow prunes stale `azapi` state for the manually deleted resources, reapplies `environments/dev.tfvars`, deploys the new image, reconciles the Event Grid webhook subscription, and validates the infra gate.
5. Confirm the website deployment completes and validate any product-path smoke checks you care about beyond the infra gate.

Supporting helpers:

- `scripts/reconcile_eventgrid_subscription.py` restores the blob-trigger webhook subscription using the current function host key.
- `scripts/validate_dev_infra_gate.py` checks health/readiness, Event Grid endpoint wiring, and the Log Analytics daily cap.

## Notes

- Function App on Container Apps and the Event Grid system topic are created via `azapi` resources for parity with current ARM/Bicep behavior.
- While the azapi identity-update bug remains, mutable Function App settings are applied via CLI from Terraform outputs so `infra/tofu` stays the single source of truth instead of the workflow reparsing tfvars.
- The deploy workflow owns Event Grid webhook subscription reconciliation because it can verify host readiness, trigger indexing, and current webhook keys before making the subscription live.
- `enable_event_grid_subscription` defaults to `false` to avoid OpenTofu racing runtime indexing or publishing a stale webhook key.
- OpenTofu references Stripe secrets by stable Key Vault secret names only. The actual Stripe values are bootstrap/operator-managed by the setup scripts and must not be passed through tfvars or Terraform variables.
