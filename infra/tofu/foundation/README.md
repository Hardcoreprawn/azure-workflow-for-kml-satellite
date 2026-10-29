# Persistent Blob foundation — not activated (#1627)

This independent root serves the ESG/EUDR analyst's evidence-custody job: routine
application releases must not control persistent inputs/evidence or their keys.
It is **not** a deployable environment, admission service, legal retention policy,
or cloud authorization. No Azure-connected plan/apply, imports, migrations,
deployment workflows, runtime data grants or automatic provider registration are
included. Keep deployment pause and production freeze intact.

## Ownership and exact inventory

Governance owns the application **resource group and dedicated vault**, including
control-plane lifecycle and permission mode. It alone owns the foundation's
vault-scoped Crypto Officer and the encryption UAMI's key-scoped Crypto Service
Encryption User grants. Foundation has no role/policy/access-policy administration,
vault lifecycle permission, subscription/RG lifecycle permission or bootstrap key
access. Declarations do not prove these effective boundaries.

Exactly ten resource declarations:

| Address | Lifecycle |
| --- | --- |
| `random_string.storage_suffix` | Application storage naming |
| `azurerm_user_assigned_identity.storage_cmk` | Dedicated storage-encryption identity |
| `azurerm_log_analytics_workspace.main` | Dedicated application audit sink |
| `azurerm_monitor_diagnostic_setting.vault` | Governance-vault `AuditEvent` diagnostic extension |
| `azurerm_key_vault_key.storage_cmk` | Application key/data-plane lifecycle |
| `azurerm_storage_account.main` | Persistent application Blob account |
| `azurerm_storage_container.kml_input` | Private input data |
| `azurerm_storage_container.kml_output` | Private evidence output |
| `azurerm_storage_container.pipeline_payloads` | Private pipeline payloads |
| `azurerm_monitor_diagnostic_setting.storage_blob` | Blob Read/Write/Delete diagnostics |

The names are new-root declarations, **not adoption/import instructions**.
All ten have `prevent_destroy`. These guards reject planned destruction, replacement
and phase regression while configuration remains present; they do not protect against
configuration removal, state tampering, privileged Azure deletion, account loss or
cryptographic key loss. Soft deletion/versioning are recovery controls, not immutable
legal holds or backups. Governance owns vault recovery/purge protection.

Deferred: Cosmos/database containers, SWA/browser binding, CIAM, DTS/task hubs,
hosts/environments, Event Grid, runtime identities/grants, image/config release,
App Insights/general alerts/action groups/budgets, communication/AI services and
subscription Defender policy. Browser origins remain empty. This does not complete
the #1620 umbrella or unblock #1528, #708, #1503, #1526 or #1327.

## Mandatory raw handoff gates

The [shared governance API](../../contracts/application-governance/README.md)
owns bootstrap v1 and the five application stages. Foundation extends it through
`scripts.validate_foundation_contract`, not a parallel bootstrap parser or sixth
governance stage. Raw received bytes are hashed without re-encoding. The caller
supplies an independently approved immutable expected context, including revisions,
tenant/subscription/environment, foundation ARM/client/principal IDs, exact GitHub
environment, selected backend, bootstrap SHA256 and bootstrap-principal exclusions.

`data.external.inputs` runs the real standard-library validator before resources
can write. Native tests mock AzureRM/random only, **not** this validator.
The AzureRM provider explicitly sets `features.storage.data_plane_available=false`;
ARM container operations remain selected through `storage_account_id`. The native
plan gate verifies this provider setting, not merely the manifest's readiness flag.
Unknown/duplicate fields, versions, types, identities, ancestry, digests, revisions,
phase skipping and foreign backends fail closed. Backend selection is early-bound
to the same context (OpenTofu's backend-variable support); use its exact approved
context at initialization and planning, never overriding with a foreign
`-backend-config`. No backend is initialized by offline gates.

Each artifact retains the shared 65,536-byte bound. The shared transport decoders
separately bound the ordered artifact array to 2 MiB and the external-provider
request to 16 MiB, allowing a valid multi-artifact bundle without truncating it at
one artifact's limit. Actual CLI regressions exercise large digest-bound bundles
and still reject individually oversized artifacts.
UUID spelling is compared using governance's UUID-only comparator; the final
schema accepts either UUID letter case while non-UUID fields remain exact.
Provider identity/ARM bindings compare case-insensitively. Original bootstrap and
predecessor bytes are never rewritten before SHA256 calculation.

Both `writes_enabled=false` (default) and disabled bootstrap federation reject a
write plan. CLI inspection may accept trust-disabled **state-phase** fixtures,
reporting `write_ready=false`, `cloud_authorized=false`. A trust-enabled declaration
is still **not** evidence of permission propagation, protected GitHub environments,
network reachability, repository/subject custody, or approval to operate Azure.
Fixture IDs/revisions are synthetic and must never be supplied to Azure.

| Foundation phase | Required immutable application prefix | Own resources present / output |
| --- | --- | --- |
| `prerequisites` | `namespace` | Four declarations: suffix/UAMI/workspace/vault diagnostic; validated `prerequisites` artifact, echoing governance vault |
| `key` | `namespace → prerequisites → custody` | Five declarations including key; validated `key` artifact, no storage references |
| `storage` | `namespace → prerequisites → custody → key → encryption` | All ten; separate `persistent-blob-core` / `not-activated` manifest |

Between phases, governance must consume the preceding actual foundation artifact
and issue the next grant declaration. Separate owner-authorized bounded permission
and network checks are required before key creation and before storage creation.
There is no sleep, auto-advance, substitute identity, fabricated future resource
reference or completed-foundation dependency at namespace creation.

`foundation_artifact` is canonical raw JSON ending in one LF. The output's external
producer validates **actual generated references** with the same semantic validator
used for fixtures. It deliberately fails rather than publishing a plausible but
incorrect manifest. The JSON
[schema](../../../docs/schemas/foundation-persistent-blob-core-v1.schema.json)
documents structural fields; semantic validation additionally checks the complete
five-stage prefix and exact context-bound values. It includes only resource/identity
references, versionless vault/key references, revisions/digests and empty origins:
no secret values, keys/SAS, connection strings, runtime hosts or invented services.
`storage.data_plane_available=false` is unconditional.

Inspect the synthetic DEV fixture (substitute `prd` consistently for PRD):

```bash
python3 -m scripts.validate_foundation_contract validate \
  --context tests/fixtures/foundation/dev/context.json \
  --bootstrap tests/fixtures/foundation/dev/bootstrap.json \
  --artifact tests/fixtures/foundation/dev/namespace.json \
  --artifact tests/fixtures/foundation/dev/prerequisites.json \
  --artifact tests/fixtures/foundation/dev/custody.json \
  --artifact tests/fixtures/foundation/dev/key.json \
  --artifact tests/fixtures/foundation/dev/encryption.json \
  --manifest tests/fixtures/foundation/dev/manifest.json \
  --storage-name kmlsatdevappabc123
```

## Security and recovery defaults

- Entra-only Blob access, no shared keys/public containers, HTTPS/TLS 1.2,
  infrastructure encryption and a versionless CMK with a dedicated UAMI.
- Public endpoint with deny-default firewall, **no trusted-services bypass**,
  and explicit owner-approved IPv4 egress; no implicit GitHub-hosted-runner access.
  Empty egress blocks the storage phase. No extra networking services are created.
- Blob versioning and 30-day Blob/container recovery. No CORS or lifecycle deletion.
- RSA application key: 180-day initial/rotated expiry, 90-day rotation, 30-day
  notification. `plantimestamp()` computes the initial date; `ignore_changes` keeps
  Azure rotation authoritative thereafter. A resource postcondition rejects an
  expired/invalid **refreshed effective** expiry. This is not proof rotation ran;
  do not skip refresh in future authorized operations.
- Dedicated 30-day workspace with local authentication disabled and resource-only
  log query access disabled; Blob Read/Write/Delete plus vault AuditEvent diagnostics.
  Actual audit delivery, storage/log ingestion costs and legal retention remain unproven.

## Offline validation and remaining gates

OpenTofu **1.13.2**, AzureRM **4.22.0**, random **3.6.3**, and the stdlib adapter's
external provider **2.3.5** are pinned in this root and its checked-in lock.
No cloud authentication is needed. Initialization is backend-disabled and lockfile
read-only; all native runs are `command = plan`.

```bash
make test-fast TESTS="tests/test_foundation_contract.py tests/test_foundation_native_plans.py"
make test-foundation
make test-foundation-mutations
make scan-foundation
make test-bootstrap
make scan-bootstrap
make lint-actions
make check
```

`test-foundation` exports evaluated native plans under ignored `.validation/`,
rejects all configuration module calls/planned child modules, checks the exact
per-phase inventory/provider feature and validates every generated artifact.
Some data-source reads are deferred by OpenTofu because managed-resource
preconditions depend on pending changes; the runner executes their fully evaluated
candidate through the **same** producer/validator instead of mocking a success.
`scan-foundation` scans all three actual evaluated plans with Trivy's
`terraformplan-json` scanner, so computed expiry is real plan data, not a scanner-only
dummy date. The canonical CI composite action invokes that same blocking target.
Only the dedicated [foundation policy](.trivyignore.yaml) is used, never global or
bootstrap exceptions.

**Owner-approved scanner disposition, 2026-10-29:**
[approval](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/1633#issuecomment-6493579386)
covers only `AVD-AZU-0010` (retain stricter `bypass=None`) and `AVD-AZU-0057`
(retain Blob Read/Write/Delete diagnostics instead of adding unrelated Queue logging).
Scope is the foundation evaluated-plan directory and scanner-reported `main.tf`.
Both expire at **2026-11-27 00:00 UTC**. The file uses JSON-form YAML with an
explicit UTC timestamp so both the stdlib metadata validator and Trivy interpret
the same expiry. There is **no key-expiry exception**.

`scan-foundation` first validates exact IDs/path/approval/expiry metadata, then
runs Trivy and mandatory real-scanner proofs: approved policy passes; `/dev/null`
baseline, expired-policy copy and wrong-path copy each produce both findings with
exit 1. Missing/invalid/expired/broadened metadata fails even without findings.
Evidence is retained in `.validation/foundation/exception-proofs/`.
Each proof deletes its previous report before invoking Trivy and rejects missing
or invalid fresh JSON, so a failed rerun cannot reuse earlier evidence.
`test-foundation-mutations` rejects ten actual source regressions, including removal
of the provider data-plane setting and an extra resource hidden in a real local module.

Owner review and complete required hosted CI/security/integration/Pipeline checks
remain mandatory. Before any future cloud work, separately authorize and prove
effective scoped RBAC/denied upstream access, key custody/use separation, protected
OIDC subjects, state locking/recovery, endpoint reachability, actual audit delivery,
rotation/recovery, refresh behavior and a no-change second apply. Passing mocks or
contract validation does not supply that evidence or authorize spend.
