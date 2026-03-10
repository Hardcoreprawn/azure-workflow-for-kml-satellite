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

1. Delete existing `dev` resource group.
2. Run `tofu apply` using `environments/dev.tfvars`.
3. Deploy application image/workloads.
4. Run the deploy workflow to prove runtime readiness and reconcile the Event Grid webhook subscription.
5. Validate static site and lead form ingestion.

Optional helper script:

- `scripts/redeploy_dev_tofu.ps1` executes delete + init + plan + apply in one flow.

## Notes

- Function App on Container Apps and the Event Grid system topic are created via `azapi` resources for parity with current ARM/Bicep behavior.
- The deploy workflow owns Event Grid webhook subscription reconciliation because it can verify host readiness, trigger indexing, and current webhook keys before making the subscription live.
- `enable_event_grid_subscription` defaults to `false` to avoid OpenTofu racing runtime indexing or publishing a stale webhook key.
