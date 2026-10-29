# Isolated bootstrap boundary

This standalone root implements #1625 and application governance #1628 under #1620. It is
**not wired into deployment** and does not authorize an Azure plan or apply.
The existing application root and shared deployment identity remain unchanged.

The accepted hosting direction is native Container Apps Functions with Durable
Task Scheduler and sleeping workers. DEV uses the Consumption scheduler SKU;
production SKU, region, operational limits and cloud spend remain separate
decisions. This root creates **no scheduler, application hosts or runtime data
services**. See [ADR 0008](../../../docs/adr/0008-supported-azure-hosting-and-deployment-ownership.md).

## Default-closed application governance (#1628)

The owner selected **governance-owned application RG and vault lifecycle** on
2026-10-29. Foundation owns its application key, encryption UAMI, audit resources
and storage, not vault control-plane writes or grants. `application.tf` is part
of this existing bootstrap root, not a second overlapping namespace/RBAC writer.
No Azure plan, apply, policy assignment, deployment or spending is authorized.

`application_phase` defaults to `disabled`. Existing bootstrap resources,
state-container grants and `bootstrap_contract` **schema v1 remain unchanged**.
Applications use the separately named, immutable
[application contract v1](../../contracts/application-governance/README.md).
The reserved `enable_application_governance` hard stop is replaced, not retained
as a compatibility switch.

| Governance phase | Declarations added | Earlier application artifacts |
| --- | --- | --- |
| `namespace` | Fresh protected application RG, dedicated RBAC vault, exact custom role and RG-scoped foundation assignment | none |
| `custody` | Foundation Crypto Officer at the application vault only | namespace, foundation prerequisites |
| `encryption` | Crypto Service Encryption User at the versionless application key ARM scope, assigned to the encryption UAMI only | namespace, prerequisites, custody, foundation key |

All application phases require bootstrap `state`, exact approved bootstrap JSON
bytes and SHA256, explicit producer/policy revisions, and explicit application
egress. Application egress is a subset of already validated bootstrap public IPv4
ranges: these IaC runners also need their own upstream state backend. The vault
denies other public traffic, permits Azure trusted services for authenticated CMK
use, enables RBAC, 90-day soft deletion and purge protection.
An application-only provider alias disables automatic recovery/adoption and purge
on destroy without changing the original bootstrap provider behavior.
RG/vault `prevent_destroy` guards accidental plans, not privileged cloud actions,
configuration removal or state repair.

### Vault authorization is an operation boundary, not field isolation

AzureRM **4.22.0** [uses Key Vault API 2023-02-01 and writes inline access policies
and authorization mode via vault PUT/PATCH](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/keyvault/key_vault_resource.go#L325).
The separate [access-policy resource](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/keyvault/key_vault_access_policy_resource.go)
uses add/replace/remove subresource operations. Excluding only that subresource
would not prevent inline policy writes.
The [selected API defaults a newly created vault to access-policy mode if RBAC
is omitted](https://github.com/Azure/azure-rest-api-specs/blob/9473ef10695a6393bdd1011ce61769a79775b1ee/specification/keyvault/resource-manager/Microsoft.KeyVault/KeyVault/stable/2023-02-01/keyvault.json#L1267);
Microsoft [warns that vault-write permission can self-grant in that mode](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-access-policy).
Microsoft [separately requires unrestricted roleAssignments/write when changing
an existing vault's authorization model](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide#enable-azure-rbac-permissions-on-key-vault).
We do not claim that existing-model check can be bypassed.

The selected solution gives foundation **only `Microsoft.KeyVault/vaults/read`**
on the control plane: no vault creation, write, deletion, recovery or access-policy
operation. Governance owns those operations and both key grants. No Azure Policy
workaround, Secrets Officer, governance application-key self-grant, workload/release
key grant, bootstrap-key access or broad permission fallback is introduced.
Crypto Officer is privileged key administration, not service-exclusive key use.
Inherited permissions remain a cloud gate: absence from an allowlist and
`NotActions` are not deny assignments.

### Exact control-plane allowlist and provider evidence

[actions.json](../../contracts/application-governance/actions.json) is the single
reviewed list, shared by the declaration and namespace artifact SHA256. All actions
are scoped to the application RG; no data actions or wildcard operations exist.
Sources below are the selected AzureRM **v4.22.0** implementation:

| Allowed operations | Provider reason |
| --- | --- |
| `Microsoft.Resources/subscriptions/resourceGroups/read` | Foundation may read the governed namespace; no create/update/delete/move permission. |
| `Microsoft.KeyVault/vaults/read` | [Key resource](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/keyvault/key_vault_key_resource.go) resolves the vault endpoint; key lifecycle uses its separate data-plane grant. |
| `Microsoft.ManagedIdentity/userAssignedIdentities/read`, `write`, `delete`, `assign/action` | [Encryption UAMI lifecycle](https://github.com/hashicorp/terraform-provider-azurerm/tree/v4.22.0/internal/services/managedidentity) and attaching that UAMI to CMK storage. No federated-credential operations. |
| `Microsoft.OperationalInsights/workspaces/read`, `write`, `delete` | [Workspace create/read/delete](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/loganalytics/log_analytics_workspace_resource.go). No log-query or shared-key grant. |
| `Microsoft.Insights/diagnosticSettings/read`, `write`, `delete` | [Vault/blob diagnostic lifecycle](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/monitor/monitor_diagnostic_setting_resource.go). No subscription-wide monitoring authority. |
| `Microsoft.Storage/storageAccounts/read`, `write`, `delete`; `blobServices/read`, `blobServices/write`; `fileServices/read` | [Storage control-plane create/refresh/update/delete](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/storage/storage_account_resource.go). Refresh reads file-service properties even though this slice creates no file-share resources. |
| `Microsoft.Storage/storageAccounts/blobServices/containers/read`, `write`, `delete` | [Container ARM lifecycle](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/storage/storage_container_resource.go#L254), selected by `storage_account_id`; no Blob data-plane grant. |

Foundation must configure
[`features.storage.data_plane_available=false`](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/provider/features.go#L318):
the [storage resource](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/storage/storage_account_resource.go#L1516)
gates data-plane startup probes and queue/static-website refresh on this feature.
Use `storage_use_azuread=true`, no provider registration, no queue/static website
configuration, and container `storage_account_id`, not the legacy name path.

Do **not** add list-keys/shared-keys permissions to suppress provider messages.
Storage refresh attempts ListKeys but explicitly tolerates 401/403 (lines
2068–2078). Workspace refresh attempts shared-key retrieval even with local auth
disabled but logs the error without failing the read (lines 491–510).
These reads must remain denied; successful inherited key retrieval is a failed
isolation gate. Nonfatal provider logging is not a reason to broaden permissions.

### Artifacts, preflight and later permission gates

The pinned external provider calls the shared stdlib parser **before application
writes**. The entire earlier prefix is validated against actual bootstrap
foundation identity/backend references, approved raw bootstrap SHA256 and explicit
revisions. Namespace/vault creation depends on that validation; later grants
consume only validated references. No completed foundation resource set, key,
storage account or hostname is required for namespace declaration.

Export `application_contract_json` with `tofu output -raw`, retaining exact bytes
including the trailing LF. `application_contract_context_json` supplies the
non-secret expected context for separate owner approval/custody; it must not be
treated as independently trusted merely because the producer emitted it.
The [shared API, stage fixtures and #1627 handoff](../../contracts/application-governance/README.md)
define the exact consumer contract. Governance never creates, reads or stores
application key material. Every artifact says `declared-not-activated`.

Before a separately authorized trial, record a **five-minute maximum per gate**,
at most **ten attempts**, and stop immediately on a wrong principal, scope, tenant,
subscription, artifact digest, unexpected success of a forbidden operation, or
non-permission error. A retry may address only bounded propagation; timeout stops
advancement, with no fixed-sleep readiness claim or credential fallback.
Verify permitted resource reads and diagnostics/network reachability; after
custody verify foundation key creation, and after encryption verify the service
identity's key use before storage creation. Use approved disposable negative
targets to prove denial of RG mutation/move/delete, fresh vault creation, inline
PUT/PATCH policy changes, mode changes, policy subresource add/replace/remove,
role/trust/policy administration, key retrieval and upstream access, including
inherited grants. No probe runner or Azure execution is enabled by this document.

## What this root owns

Use one independently custodied bootstrap state for each of `dev` and `prd`.

| Surface | Ownership and access |
| --- | --- |
| Bootstrap RG and state storage account | Bootstrap operator only; separate from application resources |
| `foundation` container | Foundation identity: Storage Blob Data Contributor on this container only |
| `workload` container | Workload identity: Storage Blob Data Contributor on this container only |
| Foundation, workload and release identities | Separate user-assigned identities; default state-only access. Explicit application phases add foundation's scoped authority/custody only; no Graph, upstream CMK or role-administration grants |
| Release identity | No state grant and no Azure resource deployment permissions yet |
| GitHub federated credentials | Disabled by default; distinct environment/layer subjects on activation |
| Dedicated bootstrap Key Vault/key | Approved bootstrap operator: Crypto Officer on this vault only; no deployment identity receives bootstrap CMK administration |
| Storage encryption identity | Separate from every deployment identity; Crypto Service Encryption User on the state key only |
| Dedicated audit workspace | Bootstrap-owned, Entra-only; no deployment-identity log access, no resource-only access |

Separate containers are the access boundaries; state keys alone would not
isolate access. Each backend uses `terraform.tfstate` inside its own container,
with Entra data authentication, OIDC and no Azure CLI authentication fallback.
Consumers receive identifiers, not access to the bootstrap state.

State storage disables shared-key authentication and public blobs, requires TLS
1.2/HTTPS, and enables infrastructure encryption, CMK encryption, versioning and
30-day blob/container soft deletion. The dedicated vault uses RBAC, purge
protection and 90-day soft deletion. The RSA key allows wrap/unwrap only, rotates
after 90 days and gives initial and rotated versions 180-day lifetimes, leaving
90 days for adoption after rotation. Initial expiry is computed from plan time;
there is no operator date input that can expire before the first rotation.
Storage uses the versionless key URI for rotation.
After creation, rotation owns expiry: OpenTofu ignores expiry drift and checks
the refreshed effective key's expiry, not a historic input date.
A healthy rotated key therefore permits maintenance and trust revocation;
an actually expired current key remains a blocking error.
`prevent_destroy` protects the RG, audit workspace, vault/key, storage account, containers and identities
while their declarations remain present. It is not a backup or protection
against deleting configuration, manual Azure actions or privileged state repair.

Storage and vault data endpoints default to deny and allow only explicitly
supplied IPv4 egress ranges. The vault also permits Azure trusted services for
Storage's authenticated CMK access; storage itself has no service bypass.
These are public endpoints with firewalls, **not private endpoints**. Broad
GitHub-hosted-runner access is not implicitly allowed. An approved private-only
policy needs a separate implemented network path, not relaxing these defaults.
LRS and the recovery/rotation intervals are reviewable code defaults, not approved
production durability or spend. Validate them during cloud authorization.

The bootstrap-owned Log Analytics workspace collects Key Vault `AuditEvent` and
blob `StorageRead`, `StorageWrite`, `StorageDelete` diagnostics. It has 30-day
retention and consumption billing (`PerGB2018`), without a silent ingestion cap.
Approve the cost ceiling, alerting and retention before cloud use. Do not expose
audit logs to deployment identities or publish them as non-secret handoff data.
Diagnostic declarations do not prove delivery; the cloud trial must exercise
successful and denied operations and verify their records arrive.

## Credential-free validation

Install OpenTofu **1.13.2** and run from the repository root:

```bash
make test-bootstrap
make scan-bootstrap
```

For an explicitly located binary:

```bash
make test-bootstrap TOFU=/absolute/path/to/tofu
```

The target checks formatting, initializes **without a backend**, verifies the
committed provider lock, validates the configuration and executes plan-only
mocked-provider tests. Provider installation needs registry access; Azure
credentials, Azure CLI login and a remote state account are not required.
It rejects leftover `errored_test.tfstate`, since a test cleanup failure must
not masquerade as success.
UUID letter case does not change the authenticated custodian or application
role identifier. Custodian/deployment/encryption identity separation also compares
UUIDs case-insensitively, so alternate spelling cannot bypass the exclusion.

The new root uses a newer validator than the unchanged legacy deployment
(1.8.0): that older mock implementation rejects AzureRM's required provider
configuration and per-instance overrides. Do not silently run this root with the
legacy CLI. AzureRM/random versions and checksums are pinned independently here.
The required CI Lint job runs this same test target without OIDC permission.
The Trivy IaC job also runs `make scan-bootstrap`, using the pinned scanner,
synthetic `tests/scan.tfvars` and the full `state` phase, then each explicit
application namespace/custody/encryption fixture. Medium/high/critical
findings fail it except for the three owner-approved, path-scoped entries in
`.trivyignore.yaml`, expiring **2026-11-27**:

- AZU-0010: retain the stricter `bypass=None` storage firewall; no trusted-service
  state access is required.
- AZU-0057: its implementation checks legacy queue logging. State uses blobs, with
  modern read/write/delete diagnostics and separate key audit logs.
- AZU-0014: the scanner cannot evaluate `plantimestamp()` in the computed initial
  expiry. Native tests assert the exact 180-day lifetime and 90-day rotation;
  the effective-key postcondition still rejects an expired key.

Review these exceptions before cloud authorization or expiry, whichever is first.
The repository-wide legacy exceptions do not apply to this blocking target.
Scanning only the default identity phase must not conceal later storage/key
resources. Never use scanner inputs for Azure.

With `TRIVY_FORMAT=sarif TRIVY_OUTPUT=trivy-bootstrap.sarif`, the blocking
target writes the state report to that path and application reports to
`.namespace`, `.custody` and `.encryption` suffixes. Scanning remains fail-fast.
Security CI uploads every report that exists, even after a failed phase or prior
upload, under distinct `trivy-bootstrap`, `trivy-bootstrap-namespace`,
`trivy-bootstrap-custody` and `trivy-bootstrap-encryption` categories. A missing
later report is not a passing scan; report publication never overrides failure.

Tests establish declared scopes, identity/subject separation, safe defaults,
output shape and input validation. They **do not** establish Azure availability,
effective permissions, inherited grants, eventual consistency, network access,
state locking/recovery or scale-from-zero.

## Before any owner-authorized bootstrap

1. Record tenant, subscription, environment, region, cost ceiling and the operator
   responsible for state custody/recovery. Pre-register required resource
   providers through governance; automatic subscription registration is disabled.
2. Approve an encrypted, access-controlled location for **bootstrap's own local
   backend**, independent from the resources it creates. Provider state can
   contain sensitive values even when public outputs do not. Keep encrypted
   backups and a tested recovery process; never publish the raw state.
3. Use separate working/backend data directories and distinct absolute state paths
   for DEV and PRD. Initialize the local backend with the approved `path` explicitly;
   never reuse a default state file by changing `environment`, and never use this
   account to host its own bootstrap state implicitly.
4. Approve the operator's narrowly scoped resource-creation and role-assignment
   permissions. Supply `bootstrap_operator_object_id`; a precondition checks it
   against the authenticated actor. This root explicitly grants that actor Crypto
   Officer on the dedicated bootstrap vault, not subscription Owner or rights to
   other vaults. Review this privileged bootstrap grant separately from the
   deployment identities, which receive no bootstrap CMK administration.
5. Review the real plan **only after separate authorization**, with
   `enable_github_oidc=false`. Confirm the fresh bootstrap namespace does not
   adopt existing resources or overlap an application root. Review optional
   provider-computed sensitive values as secrets, not handoff metadata.
6. Retain `DEPLOY_PAUSED` and the production freeze. No PR-branch deployment,
   automatic plan/apply workflow, state migration or environment cutover is
   included in this slice.

## Advance dependency phases deliberately

The default `bootstrap_phase="identity"` creates the RG, identities, dedicated
vault, audit workspace/vault diagnostics and the approved operator's vault-scoped
key-custodian grant. It creates no
key, state account, state grants or GitHub trust. Supply the approved operator/
runner egress ranges before verifying data-plane access from that actual network.

After an owner-authorized phase apply, verify the custodian's effective key access
and network path with bounded checks. Then explicitly choose `bootstrap_phase="key"`
after approving the 90-day rotation/180-day lifetime policy. This creates key material and grants
the **storage-encryption identity only** wrap/unwrap access at key scope. No state
account or federation exists yet.
Use a fresh plan for each authorized phase; never apply an old saved plan whose
calculated key expiry no longer leaves the approved rotation/adoption window.

Before explicitly choosing `bootstrap_phase="state"`, verify the encryption
identity/role and approved data access path. Storage provisioning must validate
the CMK binding; failures stop progress. Do not equate role-assignment existence
with effective permission propagation, add fixed sleeps, or retry indefinitely.
Document bounded retry/stop criteria in the authorized trial. Verify actual
state read/write/locking and key rotation/recovery before activating trust.
Retain every key version required for state and backup recovery: expiry or
rotation alone does not establish recoverability. Never delete or purge key
material as a shortcut to repairing state.

Terraform dependency edges are ordering, not readiness. The phases provide
operator-controlled stopping points; no unattended workflow advances them.
Do not downgrade phases as a teardown mechanism: protected resources reject
destruction. Removing a vault/key can render retained state unreadable.

## Activate trust separately

The exact subjects for DEV end in `environment:dev-foundation`,
`environment:dev-workload` and `environment:dev-release`; PRD substitutes `prd`.
All are bound to `Hardcoreprawn/azure-workflow-for-kml-satellite`, GitHub's token
issuer and the `api://AzureADTokenExchange` audience.

Trust is rejected outside the `state` phase. Before setting
`enable_github_oidc=true`, the owner must verify **each** GitHub
environment exists, restrict deployment to approved protected refs, require the
appropriate owner approvals and disallow unauthorized bypass. Environment names
alone are not enforcement. Jobs without these protections must not be able to
request a token accepted by a more privileged layer.

This root deliberately does not create GitHub environments or attest to their
protection. Existing `dev`/`prd` jobs do not match these subjects and must not be
rewired as a convenience. Infrastructure creation permissions and the protected
host reconciler require subsequent reviewed issues.

Revoking `enable_github_oidc` removes the federation, not existing Azure token
lifetimes or role grants. Follow the incident process for issued-token exposure;
do not assume immediate revocation. Do not destroy state storage to disable trust.

## Versioned handoff

After an authorized bootstrap, publish only:

```bash
tofu -chdir=infra/tofu/bootstrap output -json bootstrap_contract
```

Use the same approved backend/data directory as the apply. Publish that JSON as
an immutable access-controlled artifact, recording its producer revision. Do not
commit state, saved plans, credentials or account keys.

Contract version 1 contains `schema_version`, `phase`, `environment`, `tenant_id`,
`subscription_id`, `oidc_enabled`, `encryption`, `identities` and `backends`.
Encryption metadata contains only vault/key URIs and the storage identity ARM ID,
not key material. The key URI is null in the initial identity phase; backend
entries are empty until the state phase. These are explicit incomplete phases,
not release-ready outputs. Identity entries
contain ARM/client/principal IDs and the exact GitHub environment name. Backend
entries contain only resource names, key, identity/tenant/subscription IDs and
explicit Entra/OIDC authentication flags. There is no release backend entry.

Subsequent consumers must reject unknown versions, mismatched environment/
subscription/tenant, wrong layer identities, missing fields and any phase other
than `state` before writes. Disabled trust is valid for offline declaration
artifacts but must block later OIDC execution; validation does not activate trust.
A successful export is **not** deployment readiness. The current
workflow consumes none of this contract; do not copy it into legacy secrets and
assume a safe cutover.

## Required disposable-cloud evidence

Before calling this an effective isolation boundary, a separately authorized
trial must show:

- Each layer can lock/read/write **only** its own state container; the release
  identity cannot access either, and none can read bootstrap state.
- Cross-layer/cross-environment subjects and unapproved refs cannot assume the
  identities; inherited RBAC does not defeat the declared scopes.
- None of these identities can grant roles, administer trust or mutate upstream
  bootstrap resources beyond their own state-container access. Foundation's
  explicit application resource/key authority is separate; workload/release
  identities receive none of it.
- The bootstrap encryption identity can use only its state key, cannot administer
  it, and has no state-data access. Deployment identities cannot use or administer
  the bootstrap key.
- Successful and denied state blob operations and key operations appear in the
  dedicated audit workspace; deployment identities cannot query these records.
- Reapplying converges without changes; state recovery from a deliberate
  disposable deletion/version change works within the approved retention policy.
  A rotation/recovery drill proves old state remains decryptable; test only
  disposable keys/data, never destructive key operations against retained state.

Negative tests must use disposable resources, not customer data. #1528 stays
blocked/no-autopilot until its other implementation and cloud-authorization
prerequisites are satisfied.
