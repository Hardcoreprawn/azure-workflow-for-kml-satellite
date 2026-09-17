# API and Interface Reference

Canonical checked-in interface reference. OpenAPI owns machine-readable HTTP
schemas; this document explains activity and storage semantics. Neither proves
live deployment. Product requirements belong in the PID, not this contract.

Known contract gap: the OpenAPI inventory and method/auth/payload coverage are
not yet exhaustive. [#1530](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/1530)
tracks completing them against registered public and operational interfaces.

## Public HTTP Endpoints

### Quick Verification Reference

Retrieve the current Function App base URL from the Azure portal or via
`tofu output -raw function_app_orch_default_hostname` after provisioning.

Production API base URL: `https://{productionHost}/api`

| Method | Path | Auth | Expected (unauthed) | Purpose |
| --- | --- | --- | --- | --- |
| GET | /api/health | anonymous | 200 JSON | Liveness probe |
| GET | /api/readiness | anonymous | 200 JSON | Dependency readiness probe |
| GET | /api/contract | anonymous | 200 JSON | OpenAPI/contract metadata |
| GET | /api/catalogue | CIAM bearer | 401 | User analysis catalogue |
| POST | /api/analysis/submit | CIAM bearer | 401 | Accept KML for asynchronous processing (202) |
| POST | /api/timelapse-analysis | CIAM bearer | 401 | Timelapse analysis |
| POST | /api/eudr-assessment | CIAM bearer | 401 | EUDR evidence assessment |
| GET | /api/monitoring | CIAM bearer | 401 | AOI monitoring |
| GET | /api/billing/status | CIAM bearer | 401 | Billing status |
| POST | /api/billing/checkout | CIAM bearer | 401 | Stripe checkout |
| POST | /api/billing/portal | CIAM bearer | 401 | Stripe portal redirect |
| POST | /api/billing/webhook | Stripe signature | 400 without valid signature | Stripe webhook |
| POST | /api/contact-form | anonymous | — | Contact form |
| GET | /api/orchestrator/{id} | anonymous | 200/404 | Durable diagnostics (with telemetry-backed phase recovery when Durable status is stale) |
| GET | /api/analysis/history | CIAM bearer | 401 | Analysis history (`scope=user` default, `scope=org` for portfolio summary) |
| POST | /api/analysis/notes | CIAM bearer | 401 | Save/delete a parcel note; run-access authorization also required |
| POST | /api/analysis/override | CIAM bearer | 401 | Record/revert a human override; creation reasons require at least 20 characters |
| GET | /api/analysis/{id}/review | CIAM bearer | 401 | Latest `reviews` and append-only `review_history`; run access required |
| POST | /api/analysis/{id}/parcel/{aoi_index}/review | CIAM bearer | 401 | Append a review/revert revision; `override` is a JSON boolean; run access required |
| POST | /api/convert-coordinates | CIAM bearer | 401 | Coordinate conversion |
| GET | /api/export/{id}/{fmt} | CIAM bearer | 401 | Export artifacts |

This table is a quick reference, not an exhaustive route inventory. Protected
routes validate bearer tokens server-side; Functions `AuthLevel.ANONYMOUS` alone
does not describe application authentication. Explicit test-principal configuration
is not a production authentication method.

Diagnostics currently have no authentication or ownership check and may disclose
filenames, artifact paths and failure details to a caller with an instance ID.
Owner decision (2026-09-16): require authentication and run-access authorization
before leaving local development (#1527). The current anonymous contract remains until
that change is implemented and tested; it is not approved for public promotion.

A submission `202` means the ticket and KML were accepted into blob storage, not
that Durable execution has started. Event Grid admits the run asynchronously;
an initial diagnostics `404` can precede admission. The response uses `instance_id`,
while diagnostics uses `instanceId`, `customStatus`, and camelCase output fields.

## Trigger and Orchestrator Entry Points

### Completion Semantics

Durable `runtimeStatus: Completed` means orchestration code returned, not that all
requested evidence is complete. Consumers must also inspect pipeline output
status. `completed` requires nonempty AOI work, distinct metadata records for every
AOI and concrete serverless output identities: distinct nonempty raw/clipped
paths, one post-process source per raw download, and no raw/clipped path overlap.
Successful imagery/transfer records must match reported counts, and serverless
post-processing must be complete. A valid search with no imagery is
`partial_imagery`; available metadata remains accessible, but no complete imagery
evidence is claimed. Batch successes are counted separately; the summary
does not independently read Batch artifacts. Missing or unsuccessful evidence
produces `partial_imagery`. Malformed, missing, duplicate, or unexpected progressive
child results fail aggregation instead of contributing zero. Original child
exceptions remain chained. This does not certify imagery quality, enrichment
completeness, or EUDR compliance.

Progressive child results now include the original `aoi_ref` (`ref`, `key`) for
expected-set reconciliation. Namespace timestamps use recorded orchestration time
so replay retains the namespace. Drain in-flight runs before deploying these
internal pre-live contract/replay changes; old child results lack the reference.
No auth, quota, billing, or public request shape is changed.

### Progressive Failure Semantics

If progressive child fan-in fails, the parent re-raises the original failure
(preserving the cause chain) without automatically replaying the AOI. The existing
`customStatus` object records `phase: failed`, `step: aoi_pipeline`, the parent
`instance_id`, `failed_child_instance_id` (null if a thrown failure cannot be
attributed), `completed_aois`, `total_aois`, and
`recovery_action: inspect_failure_then_resubmit`. Completed counts are only the
results validated by the parent, not a claim that remaining children stopped.
`runtimeStatus: Failed` is authoritative; partial outputs are not complete evidence.
Raw failure details remain in diagnostics, not the added custom-status fields.
Consumers should inspect the correlated failure and outstanding child work before
submitting a new run. A killed parent invocation may bypass this application
handler; do not require custom status for every possible failure. No request,
auth, quota, or billing contract changes. See the worker-exit runbook section.

- Event Grid trigger: `blob_trigger` (blueprints/pipeline/blob_trigger.py)
- Main orchestrator: `treesight_orchestrator` (blueprints/pipeline/orchestrator.py)

### Event Delivery Identity

For API-managed `analysis/{submission_id}.kml|kmz` blobs, the submission UUID is
the Durable instance identity. A redelivered Event Grid notification reuses the
existing instance and does not start a second execution generation, including
after completion. Concurrent deliveries resolve to the instance admitted first.
Admission is guarded by a write-once Blob Storage marker created with
`overwrite=false`; the marker winner is the only delivery allowed to call
`start_new`. If start fails before Durable admission, that delivery removes its
own marker so Event Grid can retry. A marker conflict is a duplicate, not a new
attempt.
An explicit user retry must create a new submission ID; it is not represented by
redelivering the original blob event. Storage-native uploads without a submission
UUID continue to use their Event Grid event ID and do not receive this API-managed
deduplication contract.

## Activity Functions and Contracts

Durable activities are defined in [activities.py](../blueprints/pipeline/activities.py).
All receive dictionary payloads. This inventory includes retained entrypoints;
registration does not imply every activity is used by the main pipeline. Exact
optional fields live in the implementation and
[payload builders](../blueprints/pipeline/_payloads.py).

| Activity | Input Contract | Output Contract |
| --- | --- | --- |
| `parse_kml` | BlobEvent fields | Feature dictionaries or offloaded `{ref, count}` |
| `load_offloaded_features` | `ref` | Feature dictionaries |
| `prepare_aoi` | `feature`, optional `buffer_m` | AOI dictionary |
| `store_aoi_claims` | `instance_id`, `aois` | Claim references `{claim_id, ref, key}` |
| `load_aoi_claim` | `aoi_ref` or `ref` | AOI dictionary |
| `write_metadata` | AOI/claim, source, processing ID, timestamp, output container | Metadata and archive paths |
| `acquire_imagery` | AOI/claim, provider and filters | Acquisition outcome |
| `acquire_composite` | AOI/claim, filters, temporal count | Acquisition outcomes |
| `check_order_status` | `order_id`, provider and source identity | Single-shot state and `is_terminal` |
| `download_imagery` | Outcome, source asset, AOI bounds, output namespace | Download result and stored blob path |
| `post_process_imagery` | Download result, AOI/claim, output namespace, flags | Post-process result and output path |
| `run_enrichment` | Coordinates, per-AOI coordinates, dates, output namespace | Combined enrichment result |
| `enrich_data_sources` | Coordinates, dates, cadence, EUDR mode | Weather/event/dataset results |
| `enrich_imagery` | Coordinates, dates, output namespace | Imagery/NDVI/change results |
| `enrich_single_aoi` | `aoi_entry`, `aoi_index`, dates, output namespace | Per-AOI enrichment result |
| `enrich_finalize` | Data-source, imagery and per-AOI results, output namespace | Merged manifest result |
| `submit_batch_fulfilment` | Outcome, asset URL, output namespace | Batch job/task tracking dictionary |
| `poll_batch_fulfilment` | `job_id`, `task_id` | Batch task state |
| `complete_billing` | `user_id`, `instance_id` | `{completed: true}` (retained ledger activity) |
| `fail_billing` | `user_id`, `instance_id`, optional reason | `{refunded: true}` (retained ledger activity) |
| `finalize_run_completed` | `org_id`, `instance_id` | Org accounting finalization result |
| `finalize_run_failed` | `org_id`, `instance_id` | Org accounting refund/finalization result |
| `write_pipeline_stats` | Run identity, counts, timing, enrichment | `{written: true}` or reason for not writing |

Acquisition waiting uses Durable timers in
[_phase_acquisition.py](../blueprints/pipeline/_phase_acquisition.py), not a
blocking `poll_order` activity. Batch registration is not proof of an installed
SDK, provisioned pool, working worker command or verified artifact.

## ImageryProvider Contract

Base interface: treesight/providers/base.py

Required methods:

- search(aoi, filters) -> list[SearchResult]
- order(scene_id) -> str
- poll(order_id) -> OrderStatus
- download(order_id) -> BlobReference

Failure model:

- ProviderError (base)
- ProviderAuthError
- ProviderSearchError
- ProviderOrderError
- ProviderDownloadError

Acquisition/fulfilment activities use the provider, not replayed orchestration code.
A provider `BlobReference` is not proof of a stored artifact: Planetary Computer
returns adapter metadata; fulfilment transfers bytes and records the actual
destination separately from `adapter_blob_path`.

## Metadata JSON Schema

Canonical model: treesight/models/aoi.py

Formal schema file:

- docs/schemas/aoi-metadata-v2.schema.json

## Blob Path Conventions

Path owners are [ingestion](../treesight/pipeline/ingestion.py),
[fulfilment](../treesight/pipeline/fulfilment.py), and
[enrichment](../treesight/pipeline/enrichment/runner.py), not the storage transport.

- API input: `analysis/{submission_id}.kml` and `.tickets/{submission_id}.json`.
- Source archive: `kml/{source_stem}/{timestamp}/{source_file}`.
- AOI metadata: `metadata/{source_stem}/{timestamp}/{safe_feature}.json`.
- Download: `imagery/{raw|detail}/{project}/{timestamp}/{safe_feature}/{scene_id}.tif`.
- Post-process: corresponding `clipped` or `framed` output paths.

Feature sanitization replaces spaces/slashes and retains case; do not infer a
global lowercase-slug policy. An archive path can be returned when source bytes
were unavailable and no archive was written. Validate actual artifacts rather
than treating a constructed path as evidence. Per-AOI enrichment paths include
AOI identity; consumers should follow manifests rather than reconstructing paths.
