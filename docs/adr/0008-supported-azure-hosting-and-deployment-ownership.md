# ADR 0008: Supported Azure Hosting and Deployment Ownership

## Status

**Accepted in part**, 2026-10-28, following explicit owner decisions after #1624
merged the proposal for #1622 under #1620:

- Expensive workers must sleep; the proposed warm-worker/AzureStorage direction
  is rejected.
- Use native Container Apps Functions with Durable Task Scheduler (DTS).
- Use DTS **Consumption for the eventual DEV trial only**. Production scheduler
  SKU, availability policy and cloud-trial authorization remain separate.
- Begin the offline bootstrap/state-and-identity boundary as #1625. This accepts
  the layered ownership direction, not blanket privileges or cloud provisioning.
- For bootstrap state, use a dedicated Key Vault/key and a separate storage
  encryption identity. Keep key custody with the explicitly approved bootstrap
  operator, never with foundation/workload/release identities.
- Include dedicated bootstrap blob/key audit diagnostics. Keep the stricter
  state firewall and use only explicitly approved, scoped scanner exceptions
  (AZU-0010/AZU-0057 plus AZU-0014 for computed initial key expiry), expiring
  2026-11-27 or reviewed before cloud use.
  This approves code scope, not workspace spend or claims of delivered logs.
- Approve #1627's bounded application Blob, dedicated CMK and audit scope, with
  the protection defaults below. Foundation administers only its application
  key; governance controls its grants.
- Governance owns the application RG and establishes scoped foundation authority
  through #1628. Foundation consumes that namespace, without subscription-wide
  authority or namespace lifecycle/role-administration permissions.

Neither this acceptance nor a PR merge authorizes cloud spend, changes the live
hosting/state/permissions, or lifts `DEPLOY_PAUSED` or the production freeze.
The owner confirms there is no current Azure deployment.
All observations below are repository or vendor-documentation evidence, not live
Azure inventory. #1621 closed #884 with a bounded fail-fast guard, not a successful
deployment proof.

## Context and evidence

The primary persona is the operator supporting ESG/EUDR organisations: release
reliable assessment and evidence processing without competing configuration
writers, accidental privilege escalation, or work that requires a browser request
to wake it. Conservation and agricultural workflows share that requirement.

The [approved target](../ARCHITECTURE_OVERVIEW.md#approved-target) retains the
Azure-integrated engine, lightweight admission and independent heavy workers.
It prefers sleeping expensive workers, but approves neither a hosting product,
latency SLO nor warm-instance budget.

### Repository facts

- [Host declarations](../../infra/tofu/main.tf) create two
  `Microsoft.Web/sites@2024-04-01` resources, with
  `kind=functionapp,linux,container,azurecontainerapps`, then ignore subsequent
  `identity` and entire `body` changes.
- [Deployment](../../.github/workflows/deploy.yml) updates images/settings/CORS,
  assumes a same-name, same-resource-group `Microsoft.App/containerApps` backing
  resource, and patches its scaling. #1621 rejects an absent/mismatched resource;
  it does not establish that this update target is supported.
- The Durable backend is `AzureStorage`. The existing scale rule watches
  `durable-workitems`. Compute owns **both orchestration listeners and activities**;
  the host named `orchestrator` is admission and a Durable client. See
  [pipeline registration](../../blueprints/pipeline/__init__.py) and
  [shared registration](../../function_registration.py); monitoring's scheduler
  also runs on compute.
- One environment root currently mixes data services, hosts, role assignments,
  optional tenant identity ownership and subscription policy. Infrastructure and
  website jobs use the same configured Azure identity.
- [Origins and redirects](../../infra/tofu/locals.tf) depend on the SWA hostname.
  Dev/prd reference a shared SPA registration but calculate environment-specific
  redirect sets. Independent writers could replace one another's registrations.
- Production enables Tofu's Event Grid subscription while deployment also
  reconciles it. Runtime configuration outside the CLI subset can drift under the
  broad body ignore. Existing workflow rollback restores images, not a complete
  infrastructure/configuration revision.

### Vendor support statements

Sources were retrieved on 2026-10-28. These statements constrain the proposal;
they do not certify availability in our eventual region, image or account.

| Source | Relevant support boundary |
| --- | --- |
| [Microsoft.Web Functions integration](https://learn.microsoft.com/en-us/azure/azure-functions/functions-container-apps-hosting#managed-resource-groups) | Backing resources live in protected managed resource groups. Use documented Function App controls, not guessed peer ARM IDs or edits to protected implementation resources. |
| [Native Container Apps Functions](https://learn.microsoft.com/en-us/azure/container-apps/functions-overview#event-driven-scaling) | `Microsoft.App` with `kind=functionapp` is a distinct model. Documented automatic Durable scaling supports Microsoft SQL Server and Durable Task Scheduler, not AzureStorage. Unsupported trigger autoscaling requires nonzero replica capacity. |
| [Functions scaling override](https://learn.microsoft.com/en-us/azure/container-apps/functions-scale-rule-override) | Native custom rules require `properties.template.scale.allowScalingRuleOverride` and API `2026-03-02-preview` or newer. This is not permission to patch the integrated model's protected backing resource. |
| [Durable Azure Storage provider](https://learn.microsoft.com/en-us/azure/durable-task/durable-functions/durable-functions-azure-storage-provider) | Activity work-item queues and orchestration control queues have different roles. Timers and orchestration lifecycle/responses involve control queues; watching activity work alone cannot prove recovery. |
| [OpenTofu remote state](https://opentofu.org/docs/language/state/remote-state-data/) | Access to outputs through remote state entails access to the whole snapshot. Publish a separately access-controlled interface instead. |
| [OpenTofu dependencies](https://opentofu.org/docs/language/meta-arguments/depends_on/) | Expression references express ordinary dependencies; explicit dependencies cover hidden ordering. Neither demonstrates effective permissions or runtime readiness. |
| [AzureRM backend](https://opentofu.org/docs/language/settings/backends/azurerm/) | State uses Blob locking. Direct Entra data-plane authentication requires the corresponding backend configuration; OIDC alone does not select it or prove adequate data access. |
| [GitHub/Azure OIDC](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect) | Federated trust and scoped Azure authorization are separate setup requirements. Environment claims alone do not provide GitHub branch restrictions or approval protection. |
| [Storage CORS](https://learn.microsoft.com/en-us/rest/api/storageservices/cross-origin-resource-sharing--cors--support-for-the-azure-storage-services) and [redirect URIs](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url) | Browser origins and registered return destinations are explicit configuration. CORS is not authorization. |

## Options and accepted direction

| Option | Advantage | Unresolved cost/support consequence |
| --- | --- | --- |
| Retain Microsoft.Web integration; use documented controls only | Least runtime change; retain AzureStorage | Replace the unsupported backing-resource write assumption. Prove background wake-up or explicitly approve warm capacity. |
| Native Microsoft.App Functions; retain AzureStorage | First-class resource ownership; no immediate persistence migration | A new hosting/API/identity contract, not an ARM-ID substitution. No automatic Durable scale-from-zero claim; approve and validate a warm-worker configuration. |
| Native Functions with SQL/DTS Durable backend | Candidate for documented automatic Durable scaling | Separate persistence, identity, recovery, compatibility and cost decision. No silent backend migration. |
| Other container-capable Functions hosting, such as Premium/Dedicated | Alternative supported warm execution | Different cost and hosting constraints. Flex is not a drop-in custom-container replacement. Keep as fallback, not a parallel implementation. |

The owner selected **native Functions with DTS**, requiring sleeping workers.
Retaining AzureStorage with warm heavy workers is not the accepted alternative.
The current application still uses AzureStorage; migrating the host/backend is
a subsequent tested slice, not a side effect of this decision or the bootstrap PR.

Current Microsoft [native hosting documentation](https://learn.microsoft.com/en-us/azure/container-apps/functions-overview#event-driven-scaling)
lists automatic Durable scaling for SQL and DTS. The
[DTS Python quickstart](https://learn.microsoft.com/en-us/azure/durable-task/scheduler/quickstart-durable-task-scheduler)
requires extension bundle 4.32.0 or later and the `azureManaged` provider.
The [DTS identity guidance](https://learn.microsoft.com/en-us/azure/durable-task/scheduler/durable-task-scheduler-identity)
supports user-assigned identities and task-hub-scoped roles. These are future
binding requirements, not configuration changes made here.

Before migration, test the actual pipeline against DTS payload/completion limits,
instance-ID constraints and retention behavior; do not assume AzureStorage history
or large in-memory activity results transfer unchanged. Use the existing payload
offloading surfaces where appropriate and validate them with the DTS emulator
before any authorized cloud proof.

[DTS Consumption](https://learn.microsoft.com/en-us/azure/durable-task/scheduler/durable-task-scheduler-billing)
bills dispatched actions without a base fee, but is limited to 500 actions/second,
30-day history retention and no Dedicated high-availability option. This is a DEV
choice, not approval of production availability or compliance retention. Evidence
artifacts remain separate from orchestration history. Compute, Blob/Cosmos,
logging, network and other residual meters still cost money; sleeping workers
do not imply a zero-cost stack.

SQL remains an unselected alternative: it adds database operation/capacity, and
its [Container Apps guide](https://learn.microsoft.com/en-us/azure/durable-task/durable-functions/durable-functions-mssql-container-apps-hosting)
currently documents connection-string authentication rather than managed identity
for the SQL connection. DTS better fits the selected managed, usage-based direction.

Vendor documentation is not fully consistent: the broad
[provider comparison](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-storage-providers)
still labels DTS extension-bundle/KEDA support "Coming soon", unlike the specific
quickstart/native hosting pages above. Pin and test actual host/bundle/platform
versions in the migration and authorized DEV proof; do not turn this documentary
support statement into a claim of proven scale-from-zero.

The `durable-workitems` rule alone is not that design. Validate initial
orchestration, activity responses, durable timers and external events independently.
Monitoring's ordinary timer trigger needs its own hosting-specific assessment.
HTTP readiness probes and browser polling must not mask missing background
wake-up. CPU scaling is not a substitute for waking a zero-replica listener.

## Proposed ownership and layers

Split by trust and lifecycle, not one state per component. Modules organize code;
state separation limits blast radius only when credentials and permissions also
separate. No consumer reads an upstream state snapshot.

### Accepted application-foundation boundary

The owner approved these code-scope decisions on 2026-10-28:

- Application storage requires Entra authentication, deny-default endpoint
  firewalls, infrastructure/CMK encryption, versioning and 30-day Blob/container
  recovery. The dedicated vault has 90-day recovery and purge protection; initial
  and rotated keys have 180-day lifetimes with 90-day rotation. Dedicated audit
  retention is 30 days. These are engineering defaults, not legal-retention or
  production-budget approval; bootstrap scanner exceptions are not inherited.
- Governance owns the application RG and grants foundation a reviewed
  application-scoped control-plane allowlist, not generic RG Contributor.
  Foundation must not be able to modify/delete the governance-owned RG, manage
  access grants/trust, or administer upstream bootstrap resources.
- Governance grants foundation Crypto Officer on the dedicated application vault
  and the encryption identity Crypto Service Encryption User on the application's
  versionless key scope. Foundation owns key lifecycle, not either assignment.
  Crypto Officer is privileged administration, not read-only access. Neither
  foundation nor application release gains access to bootstrap state keys.
- Vault-write authority is not field-level isolation. Implementation must verify
  the selected API/provider checks for RBAC-mode changes and inline/subresource
  access-policy mutation. Require RBAC authorization and a reviewed enforcement
  design before merge. If RBAC cannot enforce governance-exclusive grant control,
  require a separately reviewed enforceable control or revised ownership boundary.
  Effective negative tests, including inherited authority, gate cloud use;
  configuration and CI alone cannot prove this protection.
- Workload/release identities receive no application key-administration grant.
  Other foundation families and runtime grants remain separate future slices.

Implementation order is #1628 (governance/interface prerequisite), then #1627
(the 11-resource Blob core, excluding RG and role-assignment ownership).
Both remain offline work; actual authority and permission propagation need
separately approved cloud evidence.

| Layer / sole authority | Owns | Receives and publishes |
| --- | --- | --- |
| Subscription bootstrap/governance | Backend accounts, state ACLs/recovery, OIDC trust, subscription policy; application RG and foundation/key authority; privileged recovery | Versioned namespace and staged grant references; no application secret outputs |
| Environment foundation | Persistent services, log sinks/action group/budget, SWA control plane, application key lifecycle and runtime identities; later runtime bindings require separate review | Governed namespace/permissions; publishes allowlisted resource IDs/endpoints, identity IDs and exact browser origins |
| Shared tenant identity | CIAM registration/SP/owners/federation and the complete approved redirect set | Explicit origins from every supported environment; publishes public auth configuration |
| Environment workload platform | Host environment and supported host resources, ingress, identity attachment, probes, resource/scale policy, Event Grid topic and host/topic-dependent alerts/tests | Foundation and identity contracts; publishes supported host IDs/kind, API hostname and configuration policy |
| Restricted host reconciler | One authoritative host configuration writer after initial creation | Validates platform policy plus release intent; applies only the selected hosting model's supported API |
| Application release/publisher | Immutable image intent, application-config revision, frontend content | Published contracts, no upstream state; emits deployment evidence and invokes approved reconciliation |
| Integration reconciler | Entire Event Grid subscription and restricted endpoint-key acquisition | Topic/host identities plus readiness evidence; activation only after verified readiness |
| Runtime / secret custodian | Runtime owns blobs, records and Durable history/queues; custodian owns secret values/rotation | Scoped data access / versioned secret references, never infrastructure administration |

Separate foundation and workload states/principals per environment; shared
subscription and CIAM resources have one owner each, not dev/prd copies.
The bootstrap backend is not application storage. State keys alone are not an
ACL: scope each principal to its own state and required resources, prove upstream
state reads are denied, and keep state recovery out of routine deployment.

Prefer stable, foundation-created user-assigned runtime identities if the chosen
hosting model supports every required binding. Grants can then exist before host
creation. This is a **proposed identity change**, not current behavior. If
system-assigned identities must remain, a separately authorized post-creation
binding phase must own their grants; do not create a cyclic foundation/host apply
or give the release job role-assignment rights.

### Acyclic dependency and readiness sequence

1. Owner establishes protected environments, scoped federation and state recovery.
2. Foundation creates persistent services, runtime identities and SWA control
   plane. SWA hostname plus approved custom domains produce exact browser origins.
   DNS/domain validation belongs to its named owner, not content publishing.
3. Foundation reconciles Blob CORS; shared CIAM reconciles the **complete union**
   of approved redirect URIs without deleting another environment's entries.
   Preview and localhost inclusion require an explicit environment policy.
4. Workload platform consumes those contracts and creates/configures hosts.
   API CORS and application origin policy consume the same approved origin set.
   Website content consumes the resulting API hostname and public auth settings.
   Thus SWA resource creation does not depend on API content publication.
5. Prove effective runtime/registry permissions with bounded retries and explicit
   timeouts, image pull, trigger indexing and readiness. A fixed sleep or ARM
   provisioning success is insufficient.
6. The integration reconciler acquires only the required key, redacts it, and
   activates the subscription. There must not also be a Tofu subscription writer.
7. Run authenticated smoke and record correlated release/run evidence. Failure
   blocks promotion; rollback/config recovery remains separately governed by #1327.

For the approved Blob slice, the governance/foundation steps are explicitly
staged: governed namespace -> foundation vault/identity/audit prerequisites ->
governance custody grant -> foundation key -> governance service-encryption grant
-> foundation storage. Each stage consumes only a prior immutable artifact.
Namespace creation must not depend on a completed foundation manifest.
Synthetic stage fixtures allow #1628's implementation to precede #1627 without
a reverse issue dependency; resource-level permission readiness is still separate.

### Versioned interfaces and permission limits

Publish immutable, allowlisted, access-controlled manifests with `schema_version`,
environment, tenant/subscription, producer revision and configuration-policy
revision. Foundation supplies exact resource/identity IDs and storage/service
endpoints; identity supplies public client/audience/authority and approved
redirects; workload supplies hosting kind, exact host IDs, API hostname, resource
limits and allowed config keys. Release adds image digests and an application
config revision; activation records the matching readiness evidence.

Consumers reject unsupported versions, missing fields, environment/subscription
mismatches, unapproved origins, unknown config keys and mutable image references.
Do not discover substitutes by name, replay an entire ARM GET body, expose raw
Tofu outputs wholesale or publish connection strings, account/host keys, registry
passwords, tokens or secret values. Secret URIs/versions are references; resolution
uses the runtime or dedicated custodian identity and must be redacted from logs.

Azure RBAC is not generally a per-property write boundary. A principal with broad
host write permission cannot be described as image-only merely because a script
uses it that way. The proposal therefore mediates release intent through an
approved policy-enforcing reconciler; its own code, trust and execution approvals
are privileged. The publisher cannot change that policy or obtain its credential.
The implementation must prove this boundary rather than just split workflow jobs.

Routine releases cannot modify foundations, subscription Defender settings,
CIAM trust/consent/owners, RBAC grants, CMKs, upstream state or state recovery.
Infrastructure identities must not gain unrestricted subscription ownership as
a convenience. Exact custom roles/scopes and effective deny tests are an owner
review gate, not granted by this document.

### Host configuration: one writer and explicit deletion

Platform policy owns identity, ingress, probes, resources, scale policy, registry
access and immutable host topology. Application release owns image/config intent,
not an independent ARM writer. Host creation and later reconciliation must use
the same complete desired configuration schema; initial creation hands authority
to the reconciler once, without Tofu subsequently replaying stale fields.

The following inventories the current setting names; it does not preserve
unnecessary settings or approve their current privileges:

| Desired configuration group | Current names | Source of truth |
| --- | --- | --- |
| Host/runtime | `FUNCTIONS_WORKER_RUNTIME`, `FUNCTIONS_EXTENSION_VERSION`, `WEBSITES_ENABLE_APP_SERVICE_STORAGE`, `AzureFunctionsJobHost__extensions__durableTask__storageProvider__type`, `PIPELINE_ROLE` | Platform policy; explicit role and backend, no accidental listener change |
| Storage, telemetry and vault | `AzureWebJobsStorage__accountName`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `KEY_VAULT_URI`, `KEYVAULT_URL`, `DEFAULT_INPUT_CONTAINER`, `DEFAULT_OUTPUT_CONTAINER` | Foundation references plus platform binding policy |
| Public auth and origins | `CORS_ALLOWED_ORIGINS`, `PRIMARY_SITE_URL`, `REQUIRE_AUTH`, `CIAM_AUTHORITY`, `CIAM_TENANT_ID`, `CIAM_API_AUDIENCE` | Shared identity/origin policy; no release-time auth weakening |
| Operator/billing policy | `OPS_DASHBOARD_KEY`, `BILLING_ALLOWED_USERS`, `TIER_EMULATION_ALLOWED_USERS` | Approved restricted config; secret custodian for key value |
| Application services | `IMAGERY_PROVIDER`, `COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME` | Versioned app intent plus foundation endpoints |
| Optional AI | `AZURE_AI_ENDPOINT`, `AZURE_AI_API_KEY`, `AZURE_AI_DEPLOYMENT` | Enabled-feature contract; secret reference for key |
| Optional billing | `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_PRO_GBP`, `STRIPE_PRICE_ID_PRO_USD`, `STRIPE_PRICE_ID_PRO_EUR` | Custodian references and approved pricing configuration |
| Optional communications | `COMMUNICATION_SERVICES_CONNECTION_STRING`, `EMAIL_SENDER_ADDRESS`, `NOTIFICATION_EMAIL` | Enabled-feature contract; secret reference for connection string |

Also cover image/registry credentials, native or integrated host CORS, identity
attachment, resource sizes, replicas/rules, revision/traffic control, activation
keys, generated `/api-config.json` and CIAM page configuration. Do not infer
equivalence between Microsoft.Web site configuration and native Container Apps
templates. Select and pin the supported API only with the hosting decision.

Absent optional keys must be removed deliberately when a feature is disabled;
required keys cannot disappear. Unknown keys fail validation rather than being
silently preserved. The reconciler owns the complete app-settings collection,
removes previously managed obsolete entries and checks the resulting desired
state. No broad `ignore_changes = [identity, body]` without a named replacement
authority and tested create/update/delete handoff. Capture image **and config**
revision for recovery; image rollback alone cannot claim configuration rollback.

## Current resource-address ownership inventory

This accounts for declarations in the current root, including conditional
resources, actions and helpers; instance suffixes (`[0]`, `for_each`) are omitted.
It is a proposed destination map, **not** state-move/import authorization.
Foundation/runtime distinction applies to data inside every listed service.

| Proposed authority | Current declared addresses |
| --- | --- |
| Governance: application namespace | `azurerm_resource_group.main` |
| Foundation: naming/storage | `random_string.storage_suffix`, `azurerm_storage_account.main`, `azurerm_storage_container.kml_input`, `azurerm_storage_container.kml_output`, `azurerm_storage_container.deployments`, `azurerm_storage_container.pipeline_payloads`, `azurerm_storage_management_policy.main`, `azurerm_monitor_diagnostic_setting.storage_blob` |
| Foundation: operations sinks/budget | `azurerm_log_analytics_workspace.main`, `azurerm_application_insights.main`, `azurerm_monitor_action_group.ops`, `azurerm_consumption_budget_resource_group.main` |
| Workload platform: dependent operations bindings | `azurerm_monitor_metric_alert.failed_requests`, `azurerm_monitor_metric_alert.high_latency`, `azurerm_monitor_metric_alert.eventgrid_dropped_events`, `azurerm_application_insights_standard_web_test.site_ping` |
| Foundation: CMK/vault lifecycle | `azurerm_key_vault.main`, `azurerm_user_assigned_identity.storage_cmk`, `azurerm_key_vault_key.storage_cmk` |
| Governance: replace legacy key grants with approved principals/scopes | `azurerm_role_assignment.deployer_key_vault_crypto_officer`, `azurerm_role_assignment.storage_cmk_kv_crypto_user` |
| Retire fixed propagation helper; replace with readiness gates | `time_sleep.deployer_key_vault_crypto_officer_propagation` |
| Foundation: optional communications/AI | `azurerm_communication_service.main`, `azurerm_email_communication_service.main`, `azurerm_email_communication_service_domain.azure_managed`, `azapi_update_resource.acs_link_email`, `azurerm_cognitive_account.openai`, `azurerm_cognitive_deployment.gpt4o_mini` |
| Foundation: Cosmos | `azurerm_cosmosdb_account.main`, `azurerm_cosmosdb_sql_database.main`, `azurerm_cosmosdb_sql_container.runs`, `azurerm_cosmosdb_sql_container.subscriptions`, `azurerm_cosmosdb_sql_container.users`, `azurerm_cosmosdb_sql_container.monitors`, `azurerm_cosmosdb_sql_container.catalogue`, `azurerm_cosmosdb_sql_container.orgs`, `azurerm_cosmosdb_sql_container.feature_flags`, `azurerm_cosmosdb_sql_container.feature_flag_overrides` |
| Foundation: browser control plane | `azurerm_static_web_app.main`, `azurerm_static_web_app_custom_domain.main` |
| Future runtime bindings: separately reviewed authority, never release permissions | `azurerm_role_assignment.storage_blob_data_owner`, `azurerm_role_assignment.storage_queue_data_contributor`, `azurerm_role_assignment.storage_table_data_contributor`, `azurerm_role_assignment.storage_account_contributor`, `azurerm_role_assignment.key_vault_secrets_user`, `azurerm_role_assignment.orch_storage_blob_data_owner`, `azurerm_role_assignment.orch_storage_queue_data_contributor`, `azurerm_role_assignment.orch_storage_table_data_contributor`, `azurerm_role_assignment.orch_storage_account_contributor`, `azurerm_role_assignment.orch_key_vault_secrets_user`, `azurerm_role_assignment.key_vault_secrets_officer`, `azurerm_cosmosdb_sql_role_assignment.function_app`, `azurerm_cosmosdb_sql_role_assignment.function_app_orch` |
| Workload platform / host handoff above | `azurerm_container_app_environment.main`, `azapi_resource.function_app`, `azapi_resource.function_app_orch`, `azapi_resource.event_grid_system_topic` |
| Integration reconciler; remove competing declaration on implementation | `azapi_resource_action.function_host_keys`, `azapi_resource.event_grid_subscription` |
| Shared tenant identity | `data.azuread_application.ciam`, `azuread_application_registration.ciam`, `azuread_service_principal.ciam`, `azuread_application_owner.ciam_deploy_sp`, `azuread_application_redirect_uris.ciam_spa`, `azuread_application_federated_identity_credential.ciam_deploy_sp`, `terraform_data.validate_ciam_vars` |
| Subscription governance: Defender enabled and disabled tiers | `azurerm_security_center_subscription_pricing.app_services`, `azurerm_security_center_subscription_pricing.storage_accounts`, `azurerm_security_center_subscription_pricing.key_vaults`, `azurerm_security_center_subscription_pricing.discovery`, `azurerm_security_center_subscription_pricing.foundational_cspm`, `azurerm_security_center_subscription_pricing.virtual_machines`, `azurerm_security_center_subscription_pricing.sql_servers`, `azurerm_security_center_subscription_pricing.sql_server_virtual_machines`, `azurerm_security_center_subscription_pricing.kubernetes_service`, `azurerm_security_center_subscription_pricing.container_registry`, `azurerm_security_center_subscription_pricing.arm`, `azurerm_security_center_subscription_pricing.dns`, `azurerm_security_center_subscription_pricing.open_source_relational_databases`, `azurerm_security_center_subscription_pricing.containers`, `azurerm_security_center_subscription_pricing.cosmos_dbs`, `azurerm_security_center_subscription_pricing.api` |
| Each isolated provider context | `data.azurerm_client_config.current`; provider versions, variables, backend configuration and locals move with their consumer, never export credentials |

The three existing import blocks (SWA, CIAM registration and CIAM redirects)
belong to their destination owners and require explicit adoption/recovery
approval. Fixed RBAC propagation sleep is a current helper, not the proposed
readiness proof. Host/topic-dependent alerts and web tests belong to workload
state alongside those targets, consuming foundation log/action-group IDs. They
must not create a reverse prerequisite for foundation creation or grant workloads
foundation write access.

## Owner decision ledger

The direction below is accepted only where stated. Record the remaining owner
decisions and evidence before implementing or activating the affected boundary.

| Decision | Required evidence / explicit choice |
| --- | --- |
| Hosting/API/region | Native Container Apps Functions accepted; exact API/image/bindings and regional availability still require verification |
| Backend and idle policy | DTS and sleeping workers accepted; Consumption for DEV only; production SKU/HA and backend migration remain gated |
| Cost and latency | No cloud budget or latency thresholds approved; size/scale limits and residual costs must be bounded before trial |
| State/identity boundaries | Layered direction and offline bootstrap slice accepted; #1625 implements isolated state and deployment identities, not application resource grants or runtime identity cutover |
| Application namespace and custody | #1628 owns namespace and grant declarations; #1627 consumes them and owns application key/data lifecycle. Bounded scope/protection defaults accepted; exact role actions and real execution still need review/evidence |
| Host write enforcement | Protected reconciler, policy ownership and denied bypass paths, not imaginary field-level RBAC |
| Origins/shared resources | One complete CIAM writer, subscription Defender owner and SWA/DNS/CORS policy |
| Activation and recovery | Single Event Grid owner, configuration recovery, rollback authority and release evidence retention |
| Disposable cloud trial | Named DEV subscription/RG, owner approval, budget, expiry/teardown and stopping conditions; production remains frozen |

## Ordered follow-ons and acceptance

Do not create autonomous implementation assignments until the relevant owner
decisions are accepted. #1619's bootstrap documentation fix is independent.

The first bounded implementation, #1625, merged in #1626: an independent bootstrap root with
foundation/workload state containers, separate deployment identities, default-closed
OIDC and a versioned non-secret handoff. It grants no application/role-administration
permissions and does not rewire the legacy deployment. Foundation services,
DTS/task-hub/runtime identities and workload roots remain follow-on slices.
Bootstrap advances through explicit identity, key and state phases so permission
readiness can be checked before dependent resources. Vault-scoped custodian and
key-scoped encryption grants are bootstrap-only, not downstream deployment rights.

1. **Bootstrap/foundation boundary:** implement selected states, scoped identities
   and published contracts. #1628 precedes #1627; bootstrap state isolation is
   already implemented by #1626. Test manifest rejection and denied upstream access;
   isolated backend-disabled validation first. No real state move or apply here.
2. **Supported host/config contract:** implement one chosen model and complete
   create/update/delete schema. Replace the backing-resource assumption with
   executable contract regressions. Coordinate #1526's actual API/worker isolation
   rather than duplicating that runtime scope.
3. **Release/integration consumers:** separate artifact publication from privileged
   reconciliation and activation. Consume digests/config identity from #1503;
   coordinate complete recovery with #1327. Test removal of disabled settings and
   absence of competing Event Grid/CIAM writers.
4. **Separately approved disposable DEV proof:** use #1528 for wake-up/cost
   measurement and #708 for the authenticated journey. No cloud permission is
   implied by completing steps 1-3 or passing local tests.

### Experiment-unblocking milestone

Issue #1528 must not depend on completion of umbrella #1620: the umbrella consumes
its results. Replace that blanket issue-body blocker with #1622 as the immediate
proposal prerequisite, retaining #1528's other dependencies and its `blocked`
and `no-autopilot` labels. Closing the proposal issue alone cannot unblock it.

Before assigning the experiment, the owner must accept a supported **experimental
hosting/ownership contract**, including state/identity boundaries and budgeted
replica/resource limits. This authorizes a design for a bounded trial, not final
warm-capacity/SLO decisions, which can depend on #1528's measurements. The
orchestrator must then put the concrete implementation-child prerequisites from
steps 1-3 into #1528's issue body as `Blocked by #N`, and order them ahead of it
on the Project. Do this when those children are created, not after starting work.

Only after those prerequisites pass and the owner separately approves the named
DEV environment, spend ceiling, expiry/teardown and experiment plan may the
orchestrator remove `blocked`. Keep `no-autopilot` for the human-controlled cloud
trial. #1620 stays open while the experiment runs and closes only after accepting
its evidence. Proposal merge, implementation completion and cloud authorization
are three different milestones; none silently implies the next.

Proposed executable acceptance for those implementation issues:

- An empty authorized environment converges, and a second identical apply is a
  no-op. Deliberate disposable drift is detected and repaired by its sole owner.
- Image-only releases do not change foundation plans/configuration. The actual
  publisher identity is denied upstream state reads, role/trust changes, CMK and
  foundation writes; negative tests target disposable objects, never real data.
- Missing/incompatible manifests, unpropagated grants, image-pull failures,
  missing triggers and unhealthy hosts block activation with explicit evidence.
  Freeze checks reject unauthorized runs before writes.
- Run at least **10 proposed trials per wake-up path**: initial orchestration,
  queued activity, activity response, durable timer and external event. Require
  zero stranded/lost runs and capture every latency, replica count and billed
  cost. Thresholds and sample size require owner acceptance. If a path is not
  used, demonstrate that from runtime registration; do not silently skip it.
- Measure the ordinary monitoring scheduler separately. During background-wake
  trials, exclude HTTP traffic/probes capable of warming the worker; use
  out-of-band platform telemetry. A nonzero heavy-worker floor is not the accepted
  design and cannot be substituted to make the cold-recovery gate pass.
- Verify compute ingress isolation, authenticated KML/KMZ upload through complete
  artifacts/exports, retries and an approved image/config recovery drill. No
  zero-check or anonymous-200-only acceptance.

Local documentation checks and required CI validate this proposal's consistency,
not these future Azure properties. #1620 remains open until accepted decisions,
bounded implementation and explicitly approved runtime evidence satisfy it.
