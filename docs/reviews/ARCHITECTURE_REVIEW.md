# Architectural Review — v1 → v2 (TreeSight Multi-Tenant SaaS)

**Date:** 21 February 2026
**Scope:** Full codebase review against PID v2.0 direction
**Verdict:** The v1 processing engine is well-architected and most of the activity layer translates cleanly.  The primary migration cost is threading tenant context through a hardcoded container-name assumption that pervades 7+ locations, plus standing up entirely new layers (API, Cosmos DB, frontend, ML pipeline) that don't exist today.

---

## 1. Executive Summary

| Category | Rating | Notes |
| --- | --- | --- |
| **Activity layer** | ✅ Solid | Pure-function design, minimal infrastructure coupling |
| **Provider abstraction** | ✅ Solid | ABC + factory + caching — extend, don't modify |
| **Orchestrator / phases** | ✅ Good | Clean 3-phase decomposition, parallelism ready |
| **Models** | ⚠️ Minor changes | Missing `tenant_id`, `orchard_name` → `project_name` |
| **Blob path generation** | ⚠️ Minor changes | No tenant coupling (by design), terminology rename |
| **Container name hardcoding** | 🔴 Pervasive | Hardcoded in 7+ locations — migration-critical |
| **Infrastructure (Bicep)** | 🔴 Needs rework | Static 2-container layout, no Cosmos/Container Apps/Entra |
| **API layer** | 🔴 Missing | Only a debug status endpoint exists |
| **Analytical pipeline** | 🔴 Missing | NDVI, tree detection, change detection — all new |
| **Frontend** | 🔴 Missing | No UI — entirely new workstream |

---

## 2. What's Solid — Keep As-Is

### 2.1 Activity Functions — Pure-Logic Design ✅

Every activity (`parse_kml`, `prepare_aoi`, `acquire_imagery`, `download_imagery`, `post_process_imagery`, `poll_order`, `write_metadata`) follows the same pattern:

- **Input:** deserialised dict from Durable Functions
- **Processing:** pure domain logic with no global state
- **Output:** serialisable dict

This is exactly right for multi-tenant: activities don't care *whose* polygon they're processing. The tenant context flows through from the orchestrator input, and activities just need the correct output container passed to them. No activity function references a tenant concept directly — they'll work unmodified once the orchestrator threads the right container name to storage-touching activities.

**Files confirmed clean:**

- `kml_satellite/activities/parse_kml.py` — reads from `container_name` in the event (already dynamic)
- `kml_satellite/activities/prepare_aoi.py` — pure geometry, zero storage references
- `kml_satellite/activities/acquire_imagery.py` — provider interaction only
- `kml_satellite/activities/poll_order.py` — provider interaction only

### 2.2 Provider Abstraction ✅

The `ImageryProvider` ABC → `factory.py` → concrete adapters pattern is one of the strongest parts of the codebase:

- **Interface:** `search()` → `order()` → `poll()` → `download()` lifecycle
- **Factory:** Lazy-import registry with instance caching (thread-safe)
- **Extensibility:** `register_provider()` for test/custom adapters

This directly supports v2:

- Providers are **shared infrastructure** — all tenants use the same Planetary Computer adapter, just with different AOIs
- The same pattern can be extended for analytical "providers" (NDVI computation, tree detection models)
- No tenant coupling, by design

### 2.3 Orchestrator Phase Decomposition ✅

The 3-phase architecture in `phases.py` (Ingestion → Acquisition → Fulfillment) with typed `TypedDict` contracts (`IngestionResult`, `AcquisitionResult`, `FulfillmentResult`) is clean and extensible:

- Adding a **Phase 4: Analysis** (NDVI → tree detection → change detection) follows the same pattern — `yield from run_analysis_phase(context, ...)`
- Adding a **Phase 5: Catalogue** (upsert to Cosmos DB) is a single additional `yield context.call_activity("catalogue_acquisition", ...)`
- The parallel fan-out pattern (Issue #54/#55) with bounded batches works for analytical fan-out too

### 2.4 Exception Taxonomy ✅

The `PipelineError` hierarchy (Validation / Transient / Permanent / Contract) with `retryable` flag, structured `to_error_dict()`, and stage/code attributes is production-ready. No changes needed for multi-tenant.

### 2.5 Payload Offloading ✅

The `payload_offload.py` system (Issue #62) that redirects large feature lists to blob storage is a smart design. For multi-tenant it needs the offload container to be tenant-scoped or use a shared `system` container — but the mechanism itself is sound.

### 2.6 Defensive Coding Standards ✅

The codebase consistently applies:

- Input validation at every activity boundary
- Graceful degradation (bad features skipped, clip failures return raw image)
- Type-safe deserialization (`from_dict()` with explicit type checks)
- Frozen dataclasses for immutability
- Structured logging with correlation IDs

These standards translate directly to multi-tenant and are even more important when processing untrusted tenant uploads.

---

## 3. What Needs to Change — Migration-Critical

### 3.1 🔴 Hardcoded Container Names (7+ locations)

**This is the single biggest migration item.** The names `kml-input` and `kml-output` are baked into:

| Location | Current Value | Multi-Tenant Equivalent |
| --- | --- | --- |
| `core/constants.py` | `INPUT_CONTAINER = "kml-input"` | Derive from `tenant_id` |
| `core/constants.py` | `OUTPUT_CONTAINER = "kml-output"` | Derive from `tenant_id` |
| `core/config.py` | `kml_input_container = "kml-input"` | Dynamic per-event |
| `function_app.py` L68 | `if container != INPUT_CONTAINER:` | Pattern match `*-input` |
| `infra/modules/storage.bicep` | Fixed `kml-input`, `kml-output` containers | Dynamic provisioning |
| `infra/modules/event-grid.bicep` | `subjectBeginsWith: 'kml-input/'` | Remove or wildcard |
| `infra/modules/function-app.bicep` | App settings `KML_INPUT_CONTAINER`, `KML_OUTPUT_CONTAINER` | Remove or template |
| `activities/write_metadata.py` | `container=OUTPUT_CONTAINER` | Tenant container param |
| `activities/post_process_imagery.py` | `container: OUTPUT_CONTAINER` | Tenant container param |
| `providers/planetary_computer.py` | `config.extra_params.get("output_container", OUTPUT_CONTAINER)` | Tenant container |

**Recommended approach:**

```text
1. Extract tenant_id from the input container name:
   "{tenant_id}-input" → tenant_id

2. Compute output container:
   "{tenant_id}-output"

3. Thread output_container through the orchestrator
   into every storage-touching activity.

4. Replace the defence-in-depth trigger filter:
   container != INPUT_CONTAINER  →  not container.endswith("-input")

5. Keep INPUT_CONTAINER / OUTPUT_CONTAINER constants
   as the single-tenant fallback for local dev.
```

### 3.2 ⚠️ BlobEvent Model — Missing `tenant_id`

`models/blob_event.py` — the `BlobEvent` dataclass has no `tenant_id` field. The event already carries `container_name` which encodes the tenant, but there's no explicit extraction.

**Change needed:**

```python
@property
def tenant_id(self) -> str:
    """Extract tenant ID from container name ('{tenant_id}-input')."""
    if self.container_name.endswith("-input"):
        return self.container_name.removesuffix("-input")
    return ""
```

And `build_orchestrator_input()` in `ingress.py` should add `tenant_id` to the canonical payload.

### 3.3 ⚠️ Metadata Schema Drift

`models/metadata.py` has three mismatches with PID v2.0 Section 9.3:

| Field | Current | PID v2.0 |
| --- | --- | --- |
| `SCHEMA_VERSION` | `"aoi-metadata-v1"` | `"aoi-metadata-v2"` |
| `orchard_name` | Used throughout | `project_name` |
| `analysis` block | Missing | `ndvi_mean`, `canopy_cover_pct`, `tree_count`, etc. |
| `tenant_id` | Missing | Required |

The `_extract_orchard_name()` helper already looks for both `orchard_name` and `project_name` in metadata — so the rename is partially anticipated. But the field name on `AOIMetadataRecord` itself is still `orchard_name`.

### 3.4 ⚠️ Blob Path Terminology

`utils/blob_paths.py` — all path-building functions use `orchard_name` as a parameter name. PID v2.0 generalises this to `project_name` (a tenant's project could be a rainforest survey, not an orchard). This is a cosmetic rename but should be done for PID alignment:

- `build_kml_archive_path(source_filename, orchard_name=...)` → `project_name`
- `build_metadata_path(feature_name, orchard_name=...)` → `project_name`
- `build_imagery_path(feature_name, orchard_name=...)` → `project_name`
- `build_clipped_imagery_path(feature_name, orchard_name=...)` → `project_name`

### 3.5 ⚠️ Event Grid Subscription Filter

`infra/modules/event-grid.bicep` L42:

```bicep
subjectBeginsWith: '/blobServices/default/containers/kml-input/'
```

Multi-tenant has N containers (`tenant-a-input`, `tenant-b-input`, ...). Options:

| Option | Pros | Cons |
| --- | --- | --- |
| **Remove prefix filter** — rely only on `.kml` suffix | Simple, one subscription | Fires for all containers — code must filter |
| **Wildcard** — Event Grid doesn't support regex | N/A | Not available |
| **Per-tenant subscriptions** | Perfect filtering | Operational overhead at scale |

**Recommendation:** Remove the `subjectBeginsWith` filter. Keep `subjectEndsWith: '.kml'`. Strengthen the trigger function's defence-in-depth validation to check `container.endswith("-input")`.

### 3.6 ⚠️ IaC — Static Container Provisioning

`storage.bicep` creates exactly `kml-input` and `kml-output`. Tenant containers must be provisioned dynamically (via the API layer's tenant provisioning flow), not in Bicep. The static containers should remain for system use (deployment artifacts, shared models, etc.) but stop being the application's data containers.

**Recommendation:** Keep the Bicep module for the shared storage account + system containers. Add a tenant provisioning service (Container Apps API) that creates `{tenant_id}-input` + `{tenant_id}-output` containers and sets up SAS policies on tenant registration.

---

## 4. Architecture Gaps — New Components Needed

### 4.1 API Layer (Phase 4 — new)

No REST API exists beyond the debug `orchestrator_status` endpoint. v2 needs:

- **Tenant registration** — create containers, seed Cosmos tenant record
- **Project CRUD** — create/list/update projects within a tenant
- **KML upload** — presigned URL generation for direct browser upload
- **Imagery catalogue** — list acquisitions, browse NDVI history, view detections
- **Annotation API** — CRUD annotations on imagery tiles
- **Usage & billing** — query usage counters, manage subscriptions

**Technology:** Azure Container Apps (as per PID § 8)
**Auth:** Entra External ID (also per PID)

### 4.2 Cosmos DB Data Layer (Phase 4 — new)

No document store exists. v2 needs:

- `tenants` container — tenant profile, subscription tier, usage counters
- `projects` container — per-project metadata, AOI definitions
- `acquisitions` container — temporal catalogue (date → scene → blobs → NDVI stats)
- `annotations` container — user-placed labels on imagery tiles
- One logical database, partitioned by `tenant_id`

### 4.3 Analytical Pipeline (Phases 5-7 — new)

No analytical code exists. v2 needs:

| Component | Compute | Dependencies |
| --- | --- | --- |
| NDVI computation | Functions activity or Container Apps Job | `numpy`, `rasterio` (already in deps) |
| Canopy cover % | Same as NDVI (threshold on NDVI raster) | numpy |
| Tree detection | Container Apps Job (GPU optional) | PyTorch / ONNX Runtime (new dep) |
| Change detection | Functions activity | numpy, existing temporal catalogue |

**Note:** `rasterio` and `numpy`-adjacent functionality already exist in the project. The NDVI activity is likely the easiest analytical extension — it can be added as a new activity alongside `post_process_imagery` in the existing orchestrator pipeline.

### 4.4 Frontend (Phase 8 — new)

No UI. React/Next.js + MapLibre GL JS as per PID § 8. Separate repo or monorepo decision needed.

---

## 5. Risk Assessment

### 5.1 High Risk — Event Grid Multi-Container Routing

The current Event Grid subscription assumes a single source container. Multi-tenant either requires:

- A broad subscription (suffix-only filter) with robust code-level routing
- Dynamic subscription management (API creates/deletes subscriptions per tenant)

The broad subscription approach is simpler but means the trigger function fires for blobs in *any* container, including system containers, annotations uploads, etc. The trigger's defence-in-depth filter becomes the primary guard.

**Mitigation:** Strengthen trigger validation to be explicit about the container naming convention. Log and discard non-matching events with metrics for monitoring.

### 5.2 Medium Risk — Durable Functions State Isolation

Durable Functions stores orchestration state in Azure Storage tables/queues on the *shared* storage account. Orchestration history for all tenants is co-mingled. This isn't a data leak (orchestration state contains blob paths, not pixel data), but:

- One tenant's extremely high volume could impact another's orchestration throughput
- Purging a tenant's orchestration history requires selective deletion (not trivial)

**Mitigation:** This is acceptable for the initial multi-tenant launch. If tenant isolation of orchestration state becomes necessary, the Durable Functions task hub name can be parameterised per tenant — but this is heavy and probably not needed until Enterprise tier.

### 5.3 Medium Risk — Provider Rate Limiting Across Tenants

The provider factory caches adapter instances (thread-safe singleton per config). All tenants share the same Planetary Computer STAC client. If multiple tenants trigger large fan-outs simultaneously, they compete for:

- STAC API rate limits
- Download bandwidth
- Azure Functions scaling boundaries

**Mitigation:** The existing `poll_batch_size` and `download_batch_size` config already throttle per-orchestration. For cross-tenant throttling, consider a shared semaphore or rate limiter in the provider factory — but only when real contention is observed.

### 5.4 Low Risk — Metadata Schema Migration

Existing metadata JSON files in blob storage use `aoi-metadata-v1` schema. Any analytics pipeline that reads historical metadata must handle both v1 (without `analysis` block) and v2 (with it). The `SCHEMA_VERSION` field already supports this — just needs version-aware deserialization in consumers.

### 5.5 Low Risk — Lifecycle Policy Paths

`storage.bicep` lifecycle rules filter on `kml-output/imagery/raw/`. Multi-tenant won't use `kml-output` — imagery lives in `{tenant_id}-output/imagery/raw/`. The lifecycle rules need to either:

- Apply to all containers (account-level policy), or
- Be created per-tenant during provisioning

---

## 6. Dependency Analysis

### 6.1 Current Dependencies — Reusable for v2

| Dependency | Used By | v2 Status |
| --- | --- | --- |
| `azure-functions` | Function App entry point | ✅ Keep — processing engine stays on Functions |
| `azure-functions-durable` | Orchestrator, phases | ✅ Keep |
| `azure-storage-blob` | All storage operations | ✅ Keep |
| `azure-identity` | Managed identity auth | ✅ Keep |
| `azure-keyvault-secrets` | Provider API keys | ✅ Keep |
| `fiona` | KML parsing (primary) | ✅ Keep |
| `lxml` | KML parsing (fallback) | ✅ Keep |
| `shapely` | Geometry validation | ✅ Keep — also needed for tree detection post-processing |
| `pyproj` | CRS transformation, geodesic area | ✅ Keep |
| `rasterio` | GeoTIFF I/O, clip, reproject | ✅ Keep — also needed for NDVI computation |
| `pystac-client` | Planetary Computer search | ✅ Keep |
| `httpx` | Imagery download | ✅ Keep |
| `pydantic` | Metadata model | ✅ Keep — extend for Cosmos models |

### 6.2 New Dependencies for v2

| Dependency | Used By | Phase |
| --- | --- | --- |
| `azure-cosmos` | Tenant state, catalogue, annotations | Phase 4 |
| `numpy` | NDVI computation, array operations | Phase 5 |
| `torch` / `onnxruntime` | Tree detection inference | Phase 6 |
| `fastapi` or `quart` | API layer on Container Apps | Phase 4 |
| `stripe` | Billing integration | Phase 8 |

**Note:** `numpy` is already an indirect dependency (via rasterio/shapely). Making it explicit is trivial.

---

## 7. Recommended Migration Sequence

Based on the codebase review, here's the least-disruptive path from v1 → v2:

### Step 1: Thread `tenant_id` through the Pipeline (Backwards-Compatible)

**Scope:** Models, ingress, orchestrator, activities — code only, no IaC changes.

1. Add `tenant_id` property to `BlobEvent` (derive from container name)
2. Add `tenant_id` and `output_container` to `OrchestratorInput`
3. Thread `output_container` through orchestrator → phases → storage-touching activities
4. Default to `kml-output` when `tenant_id` is empty (backwards-compatible)
5. Rename `orchard_name` → `project_name` in models and path builders
6. Bump metadata schema to `aoi-metadata-v2`

**Impact:** All 712 existing tests continue to pass (single-tenant mode uses defaults). New tests validate multi-tenant path routing.

### Step 2: Broaden Event Grid Filter

**Scope:** IaC + trigger function.

1. Remove `subjectBeginsWith` from Event Grid subscription
2. Strengthen trigger function's container validation: `endswith("-input")`
3. Keep `kml-input` as the default dev/test container

### Step 3: API Layer + Cosmos DB + Tenant Provisioning

**Scope:** Entirely new code — separate service (Container Apps).

1. FastAPI app with Entra External ID auth
2. Cosmos DB client for tenant CRUD, project CRUD
3. Tenant provisioning endpoint (creates blob containers, seeds Cosmos)
4. KML upload endpoint (generates SAS URL for `{tenant_id}-input`)

### Step 4: Analytical Pipeline Extension

**Scope:** New activities + orchestrator phase 4.

1. NDVI computation activity (numpy + rasterio)
2. Catalogue activity (Cosmos upsert)
3. `run_analysis_phase()` in orchestrator
4. Temporal comparison when ≥ 2 acquisitions exist

### Step 5: Tree Detection + Change Detection

**Scope:** Container Apps Job + new activities.

1. ONNX model serving on Container Apps
2. Tree detection activity (calls Container Apps endpoint)
3. Change detection activity (ΔNDVI + tree count delta)

---

## 8. Code Quality Observations

### 8.1 Positive Patterns to Preserve

- **Frozen dataclasses** for all domain models — prevents mutation bugs in concurrent fan-outs
- **`to_dict()` / `from_dict()`** serialisation boundary — clean Durable Functions transport
- **Structured logging** with `feature=`, `order_id=`, `instance=` tags — essential for multi-tenant debugging
- **Graceful degradation** (skip bad features, fall back on clip failure) — tenant-friendly
- **Defence-in-depth** (trigger function re-validates what Event Grid filters) — even more important multi-tenant

### 8.2 Minor Technical Debt

| Item | Location | Priority |
| --- | --- | --- |
| `pydantic` used only for metadata model; rest are manual dataclasses | `models/` | Low — not blocking, but consider unifying |
| `_extract_orchard_name()` already tries `project_name` key — half-migrated | `metadata.py` | Low — finish the rename |
| `SkyWatchAdapter` is a stub that raises on construction | `skywatch.py` | Low — keep as-is until needed |
| Lifecycle policies hardcode `kml-output/` prefix | `storage.bicep` | Medium — broken for multi-tenant |
| `requirements.txt` missing `pydantic` (it's in `pyproject.toml` but not the pin file) | `requirements.txt` | Low — add before next deploy |

---

## 9. Conclusion

The v1 codebase is well-engineered for its original scope. The activity-based, event-driven architecture with typed contracts, structured exceptions, and provider abstraction translates directly to multi-tenant with minimal refactoring of existing code. The migration cost is concentrated in:

1. **Container name abstraction** — a mechanical but pervasive change across 7+ files
2. **Standing up new layers** — API, Cosmos DB, analytical pipeline, frontend — that are entirely additive (no existing code is discarded)

The recommended approach is to make the container-name change first (Step 1) because it's backwards-compatible and unblocks everything else. Steps 2-5 are then independent workstreams that can proceed in parallel once the tenant-aware foundation is in place.
