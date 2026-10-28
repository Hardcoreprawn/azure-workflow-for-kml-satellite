# Isolated bootstrap boundary

This standalone root implements the first slice of #1625 under #1620. It is
**not wired into deployment** and does not authorize an Azure plan or apply.
The existing application root and shared deployment identity remain unchanged.

The accepted hosting direction is native Container Apps Functions with Durable
Task Scheduler and sleeping workers. DEV uses the Consumption scheduler SKU;
production SKU, region, operational limits and cloud spend remain separate
decisions. This root creates **no scheduler, application hosts or runtime data
services**. See [ADR 0008](../../../docs/adr/0008-supported-azure-hosting-and-deployment-ownership.md).

## What this root owns

Use one independently custodied bootstrap state for each of `dev` and `prd`.

| Surface | Ownership and access |
| --- | --- |
| Bootstrap RG and state storage account | Bootstrap operator only; separate from application resources |
| `foundation` container | Foundation identity: Storage Blob Data Contributor on this container only |
| `workload` container | Workload identity: Storage Blob Data Contributor on this container only |
| Foundation, workload and release identities | Separate user-assigned identities; no Graph, CMK, infrastructure or role-administration grants |
| Release identity | No state grant and no Azure resource deployment permissions yet |
| GitHub federated credentials | Disabled by default; distinct environment/layer subjects on activation |
| Dedicated bootstrap Key Vault/key | Approved bootstrap operator: Crypto Officer on this vault only; no deployment identity receives CMK administration |
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
after 90 days and gives new versions a 180-day expiry; the initial future expiry
must be supplied by the owner. Storage uses the versionless key URI for rotation.
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

The new root uses a newer validator than the unchanged legacy deployment
(1.8.0): that older mock implementation rejects AzureRM's required provider
configuration and per-instance overrides. Do not silently run this root with the
legacy CLI. AzureRM/random versions and checksums are pinned independently here.
The required CI Lint job runs this same test target without OIDC permission.
The Trivy IaC job also runs `make scan-bootstrap`, using the pinned scanner,
synthetic `tests/scan.tfvars` and the full `state` phase. Medium/high/critical
findings fail it except for the two owner-approved, path-scoped entries in
`.trivyignore.yaml`, expiring **2026-11-27**:

- AZU-0010: retain the stricter `bypass=None` storage firewall; no trusted-service
  state access is required.
- AZU-0057: its implementation checks legacy queue logging. State uses blobs, with
  modern read/write/delete diagnostics and separate key audit logs.

Review these exceptions before cloud authorization or expiry, whichever is first.
The repository-wide legacy exceptions do not apply to this blocking target.
Scanning only the default identity phase must not conceal later storage/key
resources. Never use scanner inputs for Azure.

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
   deployment identities, which receive no CMK administration.
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
and a future `state_key_expiration_date`. This creates key material and grants
the **storage-encryption identity only** wrap/unwrap access at key scope. No state
account or federation exists yet.

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
subscription/tenant, wrong layer identities, missing fields, any phase other than
`state`, or disabled trust
before writes. A successful export is **not** deployment readiness. The current
workflow consumes none of this contract; do not copy it into legacy secrets and
assume a safe cutover.

## Required disposable-cloud evidence

Before calling this an effective isolation boundary, a separately authorized
trial must show:

- Each layer can lock/read/write **only** its own state container; the release
  identity cannot access either, and none can read bootstrap state.
- Cross-layer/cross-environment subjects and unapproved refs cannot assume the
  identities; inherited RBAC does not defeat the declared scopes.
- None of these identities can grant roles, administer trust, mutate foundational
  resources or access runtime secrets through unintended permissions.
- The encryption identity can use only its key, cannot administer it, and has no
  state-data access. Deployment identities cannot use or administer the key.
- Successful and denied state blob operations and key operations appear in the
  dedicated audit workspace; deployment identities cannot query these records.
- Reapplying converges without changes; state recovery from a deliberate
  disposable deletion/version change works within the approved retention policy.
  A rotation/recovery drill proves old state remains decryptable; test only
  disposable keys/data, never destructive key operations against retained state.

Negative tests must use disposable resources, not customer data. #1528 stays
blocked/no-autopilot until its other implementation and cloud-authorization
prerequisites are satisfied.
