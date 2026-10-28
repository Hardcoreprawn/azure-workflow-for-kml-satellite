# Isolated bootstrap boundary

This standalone root implements the first slice of #1625 under #1620. It is
**not wired into deployment** and does not authorize an Azure plan or apply.
The existing application root and shared deployment identity remain unchanged.

The accepted hosting direction is native Container Apps Functions with Durable
Task Scheduler and sleeping workers. DEV uses the Consumption scheduler SKU;
production SKU, region, operational limits and cloud spend remain separate
decisions. This root creates **no scheduler, application hosts or runtime data
services**. See [ADR 0008](../../../docs/adr/0008-supported-azure-hosting-and-deployment-ownership.md).

## Application governance: blocked before authority is declared (#1628)

The approved ownership direction makes governance the sole owner of the fresh
application RG and application key grants. Foundation would own its dedicated
vault, encryption identity, application key and persistent services. **That
direction is not yet an implemented or enforceable permission boundary.**
`enable_application_governance` defaults to `false` and rejects `true` in both
DEV and PRD. It is a hard stop, not an operator acknowledgement switch.
This root declares no application namespace, custom role or application grant.
Existing bootstrap resources and state-container grants are unchanged.

### Selected provider/API evidence (verified 2026-10-28)

The selected provider is the committed AzureRM **4.22.0**, not a hypothetical
newer API with different defaults:

| Evidence | Consequence for the proposed foundation role |
| --- | --- |
| [AzureRM vault resource, v4.22.0](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/keyvault/key_vault_resource.go), import at line 21; create at lines 325–379; update at lines 482–522 and 638 | Uses Key Vault management API **2023-02-01**. Vault PUT serializes both `AccessPolicies` and `EnableRbacAuthorization`; PATCH can update both. Foundation vault lifecycle needs `Microsoft.KeyVault/vaults/write`, which is not field-restricted. |
| [AzureRM access-policy resource, v4.22.0](https://github.com/hashicorp/terraform-provider-azurerm/blob/v4.22.0/internal/services/keyvault/key_vault_access_policy_resource.go), lines 163–164, 237–238 and 364–365 | Separately uses `UpdateAccessPolicy` with `add`, `replace` and `remove`. Omitting `Microsoft.KeyVault/vaults/accessPolicies/write` addresses this subresource path, **not inline vault PUT/PATCH policies**. |
| [Microsoft API 2023-02-01 schema](https://github.com/Azure/azure-rest-api-specs/blob/9473ef10695a6393bdd1011ce61769a79775b1ee/specification/keyvault/resource-manager/Microsoft.KeyVault/KeyVault/stable/2023-02-01/keyvault.json), `VaultProperties.enableRbacAuthorization` and `VaultPatchProperties.enableRbacAuthorization` | New vaults default to **false** if omitted; true ignores access policies for data authorization. PATCH omission preserves the existing model. Management actions always use RBAC. Ignoring policies does not prove that policy mutation is prohibited. |
| [Microsoft RBAC guide, “Enable Azure RBAC permissions on Key Vault”](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide#enable-azure-rbac-permissions-on-key-vault) | Changing an existing permission model requires unrestricted `Microsoft.Authorization/roleAssignments/write`, in addition to vault write. Foundation must not receive that action. This documented switch restriction does **not** establish that foundation cannot create a fresh access-policy vault in its writable RG. |
| [Microsoft RBAC vs access policies warning](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-access-policy) | A role containing `Microsoft.KeyVault/vaults/write` can self-grant data access through access policies on an access-policy vault. The provider's `enable_rbac_authorization = true` declaration is not an authorization restriction on the principal. |

This is a blocked authorization proof, not a claim that the existing-model switch
can bypass Microsoft's documented authorization check. Excluding
`roleAssignments/write`, `accessPolicies/write` and using no wildcard actions
does not prove governance-exclusive grants across the whole vault lifecycle.
`NotActions` also cannot deny inherited permissions. Native mocks and static
scanners cannot settle server-side authorization behavior.

### Required owner decision before completing #1628

Select and separately review an enforceable control, for example:

1. A governance-owned Azure Policy deny boundary covering fresh vault creation,
   updates and relevant policy-write paths, with no foundation exemption/policy
   administration and with effective negative-test evidence; **or**
2. A revised ownership boundary in which governance or an approved mediated writer
   owns vault control-plane writes and foundation receives only its explicitly
   approved key data-plane authority.

These are options, **not approved designs or permission to create policy**.
Merely making an RBAC vault immutable in Tofu, adding CI validation, changing API
defaults, or adding an acknowledgement flag is insufficient. Neither a complete
control-plane allowlist nor a grant is published before that decision. The first
required action (`Microsoft.KeyVault/vaults/write`) already fails the current
boundary proof; additional resource actions must be derived after ownership is
settled. Do not grant generic Contributor, grant administration, upstream access
or a permission fallback to unblock it.

### #1627 consumer stop and remaining interfaces

`bootstrap_contract` remains **schema v1 with its original meaning** (state and
deployment identity references only). There is **no v2 application artifact,
parser/schema API or application readiness output to consume**. Do not synthesize
namespace/key IDs or treat this gate as completion of #1628. No full phase
scanner fixtures or contract mutation tests are claimed by this blocked slice.

After the owner decision, #1628 must deliver strict immutable, allowlisted
artifacts in this order, without requiring future resources:

1. Governance namespace and scoped foundation authority.
2. Foundation vault/encryption-identity/audit references, without a key/storage.
3. Governance vault-scoped foundation Crypto Officer declaration.
4. Foundation application-key references, after a separately verified custody gate.
5. Governance versionless-key-scoped Crypto Service Encryption User declaration,
   followed by a separately verified encryption gate before foundation storage.

Each schema must bind the expected earlier digest, environment, tenant,
subscription, producer/policy revisions, namespace, foundation principal and
backend. Reject unknown versions/fields, wrong principal/layer/ancestry,
versioned key ARM scopes and skipped phases. Hashes and declared grants cannot
claim effective permissions. Crypto Officer is privileged key administration,
not service-exclusive cryptographic access.

Before any separately authorized trial, the reviewed design must specify bounded
permission/network probes with deadlines and explicit denial/timeout stops.
The negative matrix must cover fresh access-policy vault creation, inline PUT
and PATCH policy changes, RBAC-mode switching, subresource add/replace/remove,
role-assignment administration, RG mutation/deletion and upstream reads, including
inherited grants. Verify expected principal and scope without credential fallback;
prove permitted key creation and service key use only at the corresponding stage.
No Azure command, policy deployment, role change, sleep-based readiness claim or
cloud authorization is included here.

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

The new root uses a newer validator than the unchanged legacy deployment
(1.8.0): that older mock implementation rejects AzureRM's required provider
configuration and per-instance overrides. Do not silently run this root with the
legacy CLI. AzureRM/random versions and checksums are pinned independently here.
The required CI Lint job runs this same test target without OIDC permission.
The Trivy IaC job also runs `make scan-bootstrap`, using the pinned scanner,
synthetic `tests/scan.tfvars` and the full `state` phase. Medium/high/critical
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
