# TreeSight — System Specification

**Version:** 1.0.0  
**Date:** 17 March 2026  
**Status:** Canonical reference for re-implementation  

This specification captures the complete behaviour of the TreeSight KML
satellite imagery pipeline. It is language-agnostic and
infrastructure-agnostic. An implementation that satisfies every section
of this document is functionally equivalent to the current system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Domain Model](#2-domain-model)
3. [Pipeline Phases](#3-pipeline-phases)
4. [API Surface](#4-api-surface)
5. [Imagery Provider Abstraction](#5-imagery-provider-abstraction)
6. [Blob Storage Layout](#6-blob-storage-layout)
7. [KML Parsing](#7-kml-parsing)
8. [Configuration](#8-configuration)
9. [Error Handling](#9-error-handling)
10. [Observability](#10-observability)
11. [Security](#11-security)
12. [Website](#12-website)
13. [Deployment Topology](#13-deployment-topology)
14. [Data Contracts (JSON Schemas)](#14-data-contracts)

---

## 1. System Overview

TreeSight is a geospatial pipeline that:

1. Accepts a **KML file** containing one or more polygon features (orchards, vineyards, plantations).
2. **Parses** the KML into individual polygon features with metadata.
3. **Computes** an Area of Interest (AOI) for each feature: bounding box, buffered bounding box, geodesic area, centroid.
4. **Writes metadata** JSON for each AOI to blob storage.
5. **Searches** a satellite imagery provider for scenes covering each AOI.
6. **Orders** imagery and **polls** until fulfilment.
7. **Downloads** raw GeoTIFF imagery to blob storage.
8. **Post-processes** imagery: clips to AOI polygon boundary, reprojects to target CRS.
9. Exposes a **marketing website** with a live demo flow.

### 1.1 Processing Model

The pipeline is a **three-phase sequential workflow** with **fan-out parallelism** within each phase:

```
KML Upload
  │
  ▼
Phase 1: INGESTION (sequential parse → parallel AOI prep → parallel metadata write)
  │
  ▼  
Phase 2: ACQUISITION (parallel imagery search/order → batched concurrent polling)
  │
  ▼
Phase 3: FULFILMENT (batched parallel download → batched parallel clip/reproject)
  │
  ▼
Pipeline Summary
```

### 1.2 Key Invariants

- All coordinates are **WGS 84 (EPSG:4326)** at input. Reprojection is an output-side option.
- All areas are in **hectares**. All distances are in **metres**. All percentages are 0–100.
- Every pipeline run has a unique **correlation ID** propagated through all operations.
- Every activity is **idempotent** — re-running with the same input produces the same output.
- Failures are **isolated per item** — one failed download does not abort the batch.

---

## 2. Domain Model

### 2.1 Feature

A single polygon extracted from a KML file.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Placemark name (e.g. "Block A - Fuji Apple") |
| `description` | string | Placemark description text |
| `exterior_coords` | array of `[lon, lat]` | Exterior ring coordinates |
| `interior_coords` | array of arrays of `[lon, lat]` | Interior rings (holes) |
| `crs` | string | Always `"EPSG:4326"` for KML |
| `metadata` | map<string, string> | Key-value pairs from KML ExtendedData |
| `source_file` | string | Name of the source KML file |
| `feature_index` | int | Zero-based index within the source file |

**Derived properties:**

- `vertex_count`: length of `exterior_coords`
- `has_holes`: `interior_coords` is non-empty

### 2.2 AOI (Area of Interest)

A feature after geometric processing.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `feature_name` | string | — | Source feature name |
| `source_file` | string | — | Source KML filename |
| `feature_index` | int | — | Zero-based feature index |
| `exterior_coords` | `[[lon, lat], ...]` | degrees | Exterior ring |
| `interior_coords` | `[[[lon, lat], ...], ...]` | degrees | Interior rings (holes) |
| `bbox` | `[min_lon, min_lat, max_lon, max_lat]` | degrees | Tight bounding box |
| `buffered_bbox` | `[min_lon, min_lat, max_lon, max_lat]` | degrees | Bounding box + buffer |
| `area_ha` | float | hectares | Geodesic polygon area |
| `centroid` | `[lon, lat]` | degrees | Polygon centroid |
| `buffer_m` | float | metres | Buffer distance applied (default 100, range 50–200) |
| `crs` | string | — | Always `"EPSG:4326"` |
| `metadata` | map<string, string> | — | Preserved KML metadata |
| `area_warning` | string | — | Non-empty if area exceeds reasonableness threshold |

### 2.3 BlobEvent

The trigger payload when a KML file is uploaded to storage.

| Field | Type | Description |
|-------|------|-------------|
| `blob_url` | string | Full URL of the created blob |
| `container_name` | string | Container name (e.g. `kml-input`) |
| `blob_name` | string | Blob path within container |
| `content_length` | int | Size in bytes |
| `content_type` | string | MIME type |
| `event_time` | string (ISO 8601) | Timestamp of event |
| `correlation_id` | string | Unique trace ID (from event ID) |

**Derived properties:**

- `tenant_id`: extracted from container name. Pattern `{tenant_id}-input` → `tenant_id`. Legacy `kml-input` → `""`.
- `output_container`: `"{tenant_id}-output"` if tenant_id is non-empty, else `"kml-output"`.

### 2.4 ImageryFilters

Search criteria for satellite imagery.

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `max_cloud_cover_pct` | float | 20.0 | 0–100 |
| `max_off_nadir_deg` | float | 30.0 | 0–45 |
| `min_resolution_m` | float | 0.01 | ≥ 0.01 |
| `max_resolution_m` | float | 0.5 | ≥ 0.01, ≥ min_resolution_m |
| `date_start` | datetime? | null | ≤ date_end if both set |
| `date_end` | datetime? | null | ≥ date_start if both set |
| `collections` | string[] | [] | Provider-specific collection IDs |

### 2.5 SearchResult

A scene returned by a provider search.

| Field | Type | Description |
|-------|------|-------------|
| `scene_id` | string (non-empty) | Provider-specific scene identifier |
| `provider` | string (non-empty) | Provider name |
| `acquisition_date` | datetime | When the scene was captured |
| `cloud_cover_pct` | float (0–100) | Cloud cover percentage |
| `spatial_resolution_m` | float (≥ 0.01) | Ground sample distance in metres |
| `off_nadir_deg` | float (≥ 0) | Off-nadir angle in degrees |
| `crs` | string | Scene CRS (e.g. `"EPSG:32637"`) |
| `bbox` | `[min_lon, min_lat, max_lon, max_lat]` | Scene extent |
| `asset_url` | string | Direct download URL (if available) |
| `extra` | map<string, any> | Provider-specific metadata |

### 2.6 OrderState (Enum)

```
PENDING    = "pending"     — Order submitted, fulfilment in progress
READY      = "ready"       — Imagery available for download
FAILED     = "failed"      — Provider permanently rejected the order
CANCELLED  = "cancelled"   — Cancelled by timeout or user
```

### 2.7 WorkflowState (Enum)

```
READY       = "ready"
COMPLETED   = "completed"
SUCCESS     = "success"
PENDING     = "pending"
PROCESSING  = "processing"
FAILED      = "failed"
ERROR       = "error"
CANCELLED   = "cancelled"
UNKNOWN     = "unknown"
```

**Classification helpers:**

- `is_success(state)` → true for `ready`, `completed`, `success`
- `is_terminal(state)` → true for `ready`, `completed`, `success`, `failed`, `error`, `cancelled`
- `is_failure(state)` → true for `failed`, `error`, `cancelled`

---

## 3. Pipeline Phases

### 3.1 Phase 1 — Ingestion

**Input:** BlobEvent dict  
**Output:** `IngestionResult`

```
IngestionResult {
    feature_count: int
    offloaded: bool
    aois: AOI[]
    aoi_count: int
    metadata_results: MetadataResult[]
    metadata_count: int
}
```

**Steps:**

1. **Parse KML** (`parse_kml` activity)
   - Input: BlobEvent dict
   - Downloads the KML blob from storage
   - Parses using Fiona (primary) with lxml fallback
   - Extracts polygon features, normalises coordinates, validates geometry
   - Output: `Feature[]` or an offloaded payload reference (if >48 KiB serialised)

2. **Prepare AOIs** (fan-out, one per feature)
   - Input: single Feature dict (or offloaded ref + index)
   - Computes bounding box, buffered bbox, geodesic area, centroid
   - Output: AOI dict

3. **Write Metadata** (fan-out, one per AOI)
   - Input: AOI + processing_id + timestamp + tenant_id + source KML info
   - Serialises metadata JSON to blob storage
   - Archives source KML to output container
   - Output: `{ metadata: {...}, metadata_path: string, kml_archive_path: string }`

### 3.2 Phase 2 — Acquisition

**Input:** AOI list, BlobEvent (for provider config + polling overrides)  
**Output:** `AcquisitionResult`

```
AcquisitionResult {
    imagery_outcomes: ImageryOutcome[]
    ready_count: int
    failed_count: int
}
```

**Steps:**

1. **Acquire Imagery** (fan-out, one per AOI)
   - Input: `{ aoi, provider_name, provider_config, imagery_filters }`
   - Calls provider's `search()` then `order()`
   - Output: `{ order_id, scene_id, provider, cloud_cover_pct, acquisition_date, spatial_resolution_m, asset_url, aoi_feature_name }`

2. **Poll Orders** (concurrent in batches of `poll_batch_size`, default 10)
   - Each order gets its own concurrent polling loop
   - Polling loop:
     - Calls `poll_order` activity with `{ order_id, provider }`
     - On success: checks if terminal state → returns outcome
     - On transient error: exponential backoff (`retry_base × 2^(retry-1)` seconds), up to `max_retries` (default 3)
     - On non-retryable error: immediate failure
     - On timeout: returns `acquisition_timeout` state
     - Between polls: waits `poll_interval` seconds (default 30)
     - Overall deadline: `poll_timeout` seconds (default 1800 = 30 min)
   - Output per order: `ImageryOutcome`

```
ImageryOutcome {
    state: string          — "ready" | "failed" | "cancelled" | "acquisition_timeout"
    order_id: string
    scene_id: string
    provider: string
    aoi_feature_name: string
    poll_count: int
    elapsed_seconds: float
    error: string
}
```

### 3.3 Phase 3 — Fulfilment

**Input:** Ready outcomes (state == "ready"), AOI list, config  
**Output:** `FulfillmentResult`

```
FulfillmentResult {
    download_results: DownloadResult[]
    downloads_completed: int
    downloads_succeeded: int
    downloads_failed: int
    post_process_results: PostProcessResult[]
    pp_completed: int
    pp_clipped: int
    pp_reprojected: int
    pp_failed: int
}
```

**Steps:**

1. **Download Imagery** (batched parallel, `download_batch_size` default 10)
   - Input per item: `{ imagery_outcome, provider_name, provider_config, project_name, timestamp, output_container }`
   - Calls provider's `download()`, uploads GeoTIFF to blob storage
   - Output: `DownloadResult { order_id, scene_id, provider, aoi_feature_name, blob_path, adapter_blob_path, container, size_bytes, content_type, download_duration_seconds, retry_count }`
   - Failed downloads produce error dicts with same shape + `state: "failed"`, `error: "..."`

2. **Post-Process Imagery** (batched parallel, `post_process_batch_size` default 10, only on successful downloads)
   - Input per item: `{ download_result, aoi, project_name, timestamp, target_crs, enable_clipping, enable_reprojection, output_container }`
   - If `enable_clipping`: clips GeoTIFF to AOI polygon boundary
   - If `enable_reprojection` and source CRS ≠ target CRS: reprojects
   - Output: `PostProcessResult { order_id, source_blob_path, clipped_blob_path, container, clipped: bool, reprojected: bool, source_crs, target_crs, source_size_bytes, output_size_bytes, processing_duration_seconds, clip_error }`

### 3.4 Pipeline Summary

The final output aggregates all three phases:

```
PipelineSummary {
    status: "completed" | "partial_imagery"
    instance_id: string
    blob_name: string
    blob_url: string
    feature_count: int
    aoi_count: int
    metadata_count: int
    metadata_results: MetadataResult[]
    imagery_ready: int
    imagery_failed: int
    downloads_completed: int
    post_process_completed: int
    post_process_clipped: int
    post_process_reprojected: int
    imagery_outcomes: ImageryOutcome[]
    download_results: DownloadResult[]
    post_process_results: PostProcessResult[]
    message: string
}
```

**Status logic:**

- `"completed"` if: `imagery_failed == 0 AND downloads_failed == 0 AND downloads_succeeded == imagery_ready AND pp_failed == 0`
- `"partial_imagery"` otherwise

**Message format:**

```
"Parsed {feature_count} feature(s), prepared {aoi_count} AOI(s), wrote {metadata_count} metadata record(s), imagery ready={ready_count} failed={failed_count}, downloaded={downloads_completed}, clipped={pp_clipped} reprojected={pp_reprojected}."
```

---

## 4. API Surface

All endpoints return JSON unless otherwise specified.

### 4.1 Health & Readiness

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/health` | anonymous | Returns `{"status": "healthy"}` with 200 |
| GET | `/api/readiness` | anonymous | Returns `{"status": "ready", "api_version": "2026-03-15.1"}` with 200 |

### 4.2 Pipeline Trigger

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| — | Event Grid BlobCreated → blob trigger | system | Starts pipeline orchestration from KML upload |

**Trigger behaviour:**

1. Receives Event Grid BlobCreated event for `*-input` containers
2. Validates: blob name non-empty, `.kml` extension, container ends with `-input`, 0 < size ≤ 10 MiB
3. Builds canonical orchestrator input (BlobEvent → OrchestratorInput dict)
4. Starts durable orchestration with `instance_id = correlation_id`
5. Returns orchestration management URLs

### 4.3 Orchestration Status

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/orchestrator/{instance_id}` | anonymous | Returns direct JSON diagnostics (not management URLs) |

**Response shape:**

```json
{
    "instanceId": "string",
    "name": "string",
    "runtimeStatus": "string",
    "createdTime": "ISO 8601",
    "lastUpdatedTime": "ISO 8601",
    "customStatus": any,
    "output": {
        "status": "string",
        "message": "string",
        "blobName": "string",
        "featureCount": 0,
        "metadataCount": 0,
        "imageryReady": 0,
        "imageryFailed": 0,
        "downloadsCompleted": 0,
        "postProcessCompleted": 0,
        "artifacts": {
            "metadataPaths": ["string"],
            "rawImageryPaths": ["string"],
            "clippedImageryPaths": ["string"]
        }
    }
}
```

### 4.4 API Contract

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/contract` | anonymous | Returns `{"api_version": "2026-03-15.1"}` |

### 4.5 Marketing Contact Form

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/contact-form` | anonymous | Persists marketing interest |
| OPTIONS | `/api/contact-form` | anonymous | Returns 204 (CORS preflight) |

**Request body:**

```json
{
    "email": "string (required, validated pattern: ^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$)",
    "organization": "string (optional)",
    "use_case": "string (optional)"
}
```

**Validation:**

- `email` is required and must match the email pattern
- All string fields are trimmed and capped at 2000 characters
- Non-object bodies return 400

**Persistence:**

- Serialised to JSON blob at: `pipeline-payloads/contact-submissions/{submission_id}.json`
- `submission_id` is a UUID v4

**Response:** 200 with `{"status": "received", "submission_id": "..."}`

### 4.6 Demo Submission

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/demo-submit` | anonymous | Accepts email + KML for demo processing |
| OPTIONS | `/api/demo-submit` | anonymous | Returns 204 (CORS preflight) |

**Request body:**

```json
{
    "email": "string (required, validated)",
    "kml_content": "string (required, non-empty KML text)"
}
```

**Behaviour:**

1. Validates email format and KML content presence
2. Generates `submission_id` (UUID v4)
3. Stores KML to: `kml-input/demo/{submission_id}.kml`
4. Stores submission record to: `pipeline-payloads/demo-submissions/{submission_id}.json`
5. Returns 200 with `{"status": "submitted", "submission_id": "..."}`

**Submission record shape:**

```json
{
    "submission_id": "string",
    "email": "string",
    "submitted_at": "ISO 8601",
    "kml_blob_name": "demo/{submission_id}.kml",
    "kml_size_bytes": 0,
    "status": "submitted"
}
```

### 4.7 Valet Token System

Secure, time-limited access tokens for demo artifact downloads.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/demo-valet-tokens` | FUNCTION key | Mints valet tokens for a submission |
| GET | `/api/demo-artifacts` | anonymous | Downloads an artifact using a valet token |

#### Token Minting (`POST /api/demo-valet-tokens`)

**Request body:**

```json
{
    "submission_id": "string (required)",
    "recipient_email": "string (required)"
}
```

**Token structure:** `{base64url_payload}.{base64url_hmac_sha256_signature}`

**Token claims:**

```json
{
    "submission_id": "string",
    "submission_blob_name": "string",
    "artifact_path": "string",
    "recipient_hash": "sha256(lowercase(email))",
    "exp": unix_timestamp,
    "nonce": "uuid4_hex",
    "max_uses": 3,
    "output_container": "string"
}
```

**Token parameters (from environment):**

- `DEMO_VALET_TOKEN_SECRET`: HMAC-SHA256 secret (required)
- `DEMO_VALET_TOKEN_TTL_SECONDS`: token lifetime (default 86400 = 24h)
- `DEMO_VALET_TOKEN_MAX_USES`: replay limit (default 3)

#### Token Verification

1. Split on `.` → payload + signature
2. HMAC-SHA256 verify signature against payload using secret
3. Decode payload → JSON claims
4. Check `exp` > current time
5. Check replay count < `max_uses`

#### Artifact Download (`GET /api/demo-artifacts?token=...`)

1. Verify token
2. Extract `artifact_path` from claims
3. Stream blob from storage to response
4. Content-Type derived from file extension (default `application/octet-stream`)

---

## 5. Imagery Provider Abstraction

### 5.1 Provider Interface

Every imagery provider implements a four-step lifecycle:

```
search(aoi: AOI, filters: ImageryFilters) → SearchResult[]
order(scene_id: string) → order_id: string
poll(order_id: string) → OrderStatus { state, message, progress_pct, is_terminal }
download(order_id: string) → BlobReference { container, blob_path, size_bytes, content_type }
```

### 5.2 Provider Error Hierarchy

```
ProviderError (base)
├── retryable: bool (default false)
├── ProviderAuthError (non-retryable)
├── ProviderSearchError
├── ProviderOrderError
└── ProviderDownloadError
```

### 5.3 Provider Registry

- Providers are registered by name (e.g. `"planetary_computer"`)
- Factory pattern with **instance cache** keyed by `(name, api_base_url, auth_mechanism, keyvault_secret, extra_params)` — reuses HTTP sessions across calls
- Lazy imports: provider dependencies only loaded when the provider is selected
- Public API: `get_provider(name, config)`, `register_provider()`, `list_providers()`, `clear_provider_cache()`

### 5.4 Planetary Computer Provider

The current (and only) implemented provider.

**Behaviour:**

- `search()`: STAC API search via `pystac-client` against Microsoft Planetary Computer
  - Uses `planetary_computer.sign()` for SAS token signing on asset URLs
  - Filters by bounding box (from AOI `buffered_bbox`), cloud cover, date range
  - Default collection: `sentinel-2-l2a` (configurable)
- `order()`: Planetary Computer assets are immediately available (no order step) — returns a synthetic order ID
- `poll()`: Always returns `READY` immediately (PC is synchronous)
- `download()`: Downloads GeoTIFF via signed URL using `httpx`, uploads to blob storage

**Configuration:**

- `api_url`: STAC API base URL (default: `https://planetarycomputer.microsoft.com/api/stac/v1`)
- Authentication: Anonymous for search, SAS signing for downloads

---

## 6. Blob Storage Layout

### 6.1 Containers

| Container | Purpose |
|-----------|---------|
| `kml-input` | Incoming KML files (legacy/default) |
| `{tenant_id}-input` | Tenant-scoped input container |
| `kml-output` | All pipeline outputs (default) |
| `{tenant_id}-output` | Tenant-scoped output container |
| `pipeline-payloads` | Offloaded payloads, contact/demo submissions, operational captures |
| `deployments` | Deployment packages (not used at runtime) |

### 6.2 Output Paths

```
{output_container}/
├── imagery/
│   ├── raw/{project_name}/{timestamp}/{feature_name}/          ← raw GeoTIFF downloads
│   └── clipped/{project_name}/{timestamp}/{feature_name}/      ← clipped/reprojected GeoTIFF
├── metadata/
│   └── {project_name}/{timestamp}/{feature_name}.json          ← AOI metadata JSON
└── kml/
    └── {project_name}/{timestamp}/{source_file}                ← archived source KML
```

### 6.3 Pipeline Payloads Paths

```
pipeline-payloads/
├── payloads/{instance_id}/{hash}.json                          ← offloaded large payloads
├── contact-submissions/{submission_id}.json                    ← marketing contact forms
└── demo-submissions/{submission_id}.json                       ← demo submission records
```

### 6.4 Lifecycle Policies

| Rule | Path prefix | Action |
|------|-------------|--------|
| Delete offloaded payloads 7d | `pipeline-payloads/payloads/` | Delete after 7 days |
| Cool raw imagery 180d | `kml-output/imagery/raw/` | Move to Cool tier after 180 days |
| Archive raw imagery 365d | `kml-output/imagery/raw/` | Move to Archive tier after 365 days |

---

## 7. KML Parsing

### 7.1 Parser Strategy

**Primary:** Fiona (GDAL-backed, handles complex geometries + nested placemarks)  
**Fallback:** lxml (pure XML parsing, for when Fiona fails or GDAL is unavailable)

### 7.2 Supported KML Structures

- Single polygon placemarks
- Multiple polygon placemarks in a document
- Polygons with interior rings (holes)
- Nested folders containing placemarks
- `ExtendedData/Data` key-value metadata
- Schema-typed ExtendedData
- MultiPolygon geometries (split into individual polygons, one AOI each)

### 7.3 Coordinate Normalisation

- KML coordinates are `lon,lat,alt` — altitude is discarded
- All coordinates stored as `(lon, lat)` tuples (longitude first)
- CRS is always `EPSG:4326`

### 7.4 Validation Rules

- Polygon must have ≥ 3 exterior coordinates
- Polygon must be closed (first == last coordinate) — auto-closed if not
- Coordinate values must be numeric and within valid ranges
- Feature name defaults to `"Unnamed Feature {index}"` if absent

### 7.5 Payload Offload

When the serialised feature list exceeds **48 KiB** (Durable Functions history constraint):

- Features are written to blob storage at `pipeline-payloads/payloads/{instance_id}/{hash}.json`
- A reference dict is returned instead: `{ "ref": "blob_path", "count": N }`
- Downstream activities receive `{ "ref": "blob_path", "index": i }` and load individual features

---

## 8. Configuration

### 8.1 Pipeline Configuration

| Variable | Type | Default | Constraint | Description |
|----------|------|---------|------------|-------------|
| `DEFAULT_INPUT_CONTAINER` | string | `"kml-input"` | — | Fallback input container name |
| `DEFAULT_OUTPUT_CONTAINER` | string | `"kml-output"` | — | Fallback output container name |
| `IMAGERY_PROVIDER` | string | `"planetary_computer"` | registered name | Active imagery provider |
| `IMAGERY_RESOLUTION_TARGET_M` | float | `0.5` | > 0 | Target spatial resolution (metres) |
| `IMAGERY_MAX_CLOUD_COVER_PCT` | float | `20.0` | 0–100 | Max acceptable cloud cover |
| `AOI_BUFFER_M` | float | `100.0` | ≥ 0 | Buffer around AOI bounding box (metres) |
| `AOI_MAX_AREA_HA` | float | `10,000.0` | > 0 | Max AOI area (hectares) |

### 8.2 Polling Configuration (overridable per-run via BlobEvent)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `poll_interval_seconds` | int | 30 | Seconds between polls |
| `poll_timeout_seconds` | int | 1800 | Max total polling time |
| `max_retries` | int | 3 | Max retries on transient errors |
| `retry_base_seconds` | int | 5 | Exponential backoff base |
| `poll_batch_size` | int | 10 | Max concurrent polling operations |

### 8.3 Batch Configuration (overridable per-run via BlobEvent)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `download_batch_size` | int | 10 | Max concurrent downloads per batch |
| `post_process_batch_size` | int | 10 | Max concurrent post-process ops per batch |

### 8.4 Processing Overrides (per-run via BlobEvent)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enable_clipping` | bool | true | Clip imagery to AOI polygon |
| `enable_reprojection` | bool | true | Reproject if CRS differs |
| `target_crs` | string | `"EPSG:4326"` | Target CRS for reprojection |
| `provider_name` | string | `"planetary_computer"` | Which provider to use |
| `provider_config` | map? | null | Provider-specific overrides |
| `imagery_filters` | map? | null | Search filter overrides |

### 8.5 Security Configuration

| Variable | Type | Description |
|----------|------|-------------|
| `KEY_VAULT_URI` / `KEYVAULT_URL` | string | Azure Key Vault URI |
| `AzureWebJobsStorage` | string | Storage account connection string |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | string | App Insights telemetry |
| `DEMO_VALET_TOKEN_SECRET` | string | HMAC signing secret for valet tokens |
| `DEMO_VALET_TOKEN_TTL_SECONDS` | int (default 86400) | Token lifetime |
| `DEMO_VALET_TOKEN_MAX_USES` | int (default 3) | Replay limit per token |

### 8.6 Fail-Fast Validation

On startup, the configuration module validates:

- Resolution > 0
- Cloud cover 0–100
- Buffer ≥ 0
- Max area > 0

Invalid values raise `ConfigValidationError` immediately.

### 8.7 Defensive Integer Coercion

The `config_get_int(dict, key, default)` helper handles mixed types from JSON:

1. If value is `int` → return directly
2. If value is `str` or `float` → `int(float(value))` with try/except → fallback to default
3. Any other type → fallback to default

---

## 9. Error Handling

### 9.1 Exception Hierarchy

```
PipelineError (base)
├── stage: string          — which pipeline stage
├── code: string           — machine-readable error code
├── retryable: bool        — whether retry is appropriate
│
├── ContractError          — payload/input validation failures (stage="ingress")
├── ConfigValidationError  — invalid configuration at startup
├── ModelValidationError   — domain model invariant violation
│
└── ProviderError (base for all provider failures)
    ├── ProviderAuthError      — authentication failure (non-retryable)
    ├── ProviderSearchError    — search failed
    ├── ProviderOrderError     — order submission failed
    └── ProviderDownloadError  — download failed
```

### 9.2 Error Contract (Download Failures)

When a download fails, the error dict has 13 fields:

```json
{
    "state": "failed",
    "order_id": "", "scene_id": "", "provider": "", "aoi_feature_name": "",
    "blob_path": "", "adapter_blob_path": "", "container": "",
    "size_bytes": 0, "content_type": "", "download_duration_seconds": 0.0,
    "retry_count": 0, "error": "Human-readable message"
}
```

### 9.3 Error Contract (Post-Process Failures)

```json
{
    "state": "failed",
    "order_id": "", "source_blob_path": "", "clipped_blob_path": "",
    "container": "", "clipped": false, "reprojected": false,
    "source_crs": "", "target_crs": "", "source_size_bytes": 0,
    "output_size_bytes": 0, "processing_duration_seconds": 0.0,
    "clip_error": "message", "error": "message"
}
```

### 9.4 Ingress Validation Error Codes

| Code | Condition |
|------|-----------|
| `EMPTY_BLOB_NAME` | Blob name is empty |
| `INVALID_FILE_TYPE` | Not `.kml` extension |
| `EMPTY_CONTAINER_NAME` | Container name is empty |
| `INVALID_CONTAINER` | Container doesn't end with `-input` |
| `INVALID_CONTENT_LENGTH` | Negative content length |
| `EMPTY_BLOB` | Zero-byte blob |
| `FILE_TOO_LARGE` | Exceeds 10 MiB |
| `MISSING_ORCHESTRATOR_FIELDS` | Missing `blob_url`, `container_name`, or `blob_name` |
| `INVALID_JSON` | Activity input not valid JSON |
| `INVALID_INPUT_TYPE` | Wrong input type |
| `INVALID_BLOB_TYPE` | Expected BlobEvent object |

---

## 10. Observability

### 10.1 Structured Logging

All log messages use structured format:

```
phase={phase} step={step} | instance={id} | {key}={value} | blob={name}
```

**Phase-level logging:**

- Phase start: feature/AOI counts, offloaded status
- Phase complete: duration, success/failure counts, batch counts

**Poll logging:**

- Each poll result: state, poll_count
- Errors: retry count, backoff duration
- Timeout: total polls, timeout duration

### 10.2 Diagnostics Endpoint

`GET /api/orchestrator/{instance_id}` returns direct JSON (not management URLs) with:

- Runtime status, timestamps
- Output summary with artifact paths
- No authentication required (designed for operational readiness checks)

### 10.3 Correlation ID

Every pipeline run carries a `correlation_id` (sourced from Event Grid event ID) through:

- Orchestrator input
- All activity calls
- All log messages
- Metadata records
- Used as `instance_id` for the orchestration

---

## 11. Security

### 11.1 Authentication & Authorisation

| Endpoint Category | Auth Level |
|-------------------|------------|
| Health/readiness | Anonymous |
| Contract | Anonymous |
| Contact form | Anonymous |
| Demo submit | Anonymous |
| Orchestrator diagnostics | Anonymous |
| Demo valet token minting | Function key |
| Demo artifact download | Valet token (query parameter) |
| KML blob trigger | System (Event Grid) |

### 11.2 Valet Token Security

- HMAC-SHA256 signed (not encrypted — claims are visible but tamper-proof)
- Scoped to: single submission + single artifact + single recipient (by email hash)
- Time-limited: configurable TTL (default 24h)
- Replay-limited: configurable max uses (default 3)
- Recipient binding: SHA-256 hash of normalised email

### 11.3 Input Sanitisation

- All marketing form fields: trimmed, capped at 2000 characters
- Email validation: regex pattern `^[^@\s]+@[^@\s]+\.[^@\s]+$`
- KML file size: max 10 MiB enforced at ingress
- Container name validation: must end with `-input`
- Blob name validation: must end with `.kml`

### 11.4 Infrastructure Security

- Storage account: TLS 1.2 minimum, no public blob access, shared key enabled for Functions runtime
- Key Vault: RBAC-enabled, purge protection (prod), 90-day soft delete
- Function App → Storage: Managed Identity with Storage Blob Data Contributor role
- Function App → Key Vault: Managed Identity with Key Vault Secrets User role
- CORS: restricted to Static Web App hostname + localhost:1111

---

## 12. Website

### 12.1 Architecture

- **Static Web App** (Azure) hosting HTML/CSS/JS
- No build step — plain HTML with inline Tailwind-style custom CSS
- SPA-style routing (404 → `/index.html`)

### 12.2 Sections

1. **Hero** — status badge (polls `/api/readiness`), CTA buttons
2. **Problem/Solution** — 4-card grid + 6-feature capability grid
3. **Live Demo** — email + KML textarea form → `/api/demo-submit`; timelapse visualiser (Leaflet.js map with animated AOI overlays)
4. **Timeline** — 6-step workflow visualisation
5. **FAQ** — 8 Q&A pairs
6. **Early Access** — org + use case + email → `/api/contact-form`

### 12.3 API Integration

- **Contract enforcement**: On load, fetches `/api/contract` and checks `api_version == "2026-03-15.1"`. Disables demo submit button on mismatch.
- **Fallback origin**: If relative `/api/*` fails, falls back to hardcoded Function App URL (`DEFAULT_FALLBACK_ORIGIN`)
- **Status badge**: Polls `/api/readiness`, shows "Online"/"Offline" badge with animation

### 12.4 Timelapse Visualiser

- 24 synthetic frames with procedural cloud cover and vegetation vigour variations
- Leaflet.js map with animated AOI polygon overlays
- Frame metadata: cloud cover percentage, vegetation vigour score
- Playback controls: play/pause, frame scrubbing

### 12.5 Routing

| Route | Behaviour |
|-------|-----------|
| `/api/*` | Proxied to backend (anonymous) |
| `/*` | Serves static files |
| 404 | Falls back to `/index.html` |

---

## 13. Deployment Topology

> This section describes the current deployment for reference. A new
> implementation may choose a different topology.

### 13.1 Resources

| Resource | Type | Purpose |
|----------|------|---------|
| Resource Group | Container | All resources |
| Storage Account | Standard LRS | Blob storage for KML, imagery, payloads |
| Function App on Container Apps | Compute | API + pipeline worker |
| Container App Environment | Platform | Hosting environment with Log Analytics |
| Event Grid System Topic | Eventing | BlobCreated events from storage |
| Event Grid Subscription | Routing | Routes BlobCreated → Function App |
| Application Insights | Telemetry | Logging and metrics |
| Log Analytics Workspace | Logging | Backend for App Insights |
| Key Vault | Secrets | API keys, connection strings |
| Static Web App | Frontend | Marketing website (Free tier) |

### 13.2 Alerts

| Alert | Metric | Threshold | Severity |
|-------|--------|-----------|----------|
| Failed requests | `requests/failed` | > 5 per 5 min | 2 |
| High latency | `requests/duration` (avg) | > 5000ms per 5 min | 3 |

### 13.3 Multi-Tenant Model

- Tenant isolation via container naming: `{tenant_id}-input` / `{tenant_id}-output`
- Legacy (no tenant): `kml-input` / `kml-output`
- Tenant ID extracted from container name at ingress

---

## 14. Data Contracts (JSON Schemas)

### 14.1 AOI Metadata (v2)

Written to blob storage by the `write_metadata` activity.

```json
{
    "$schema": "aoi-metadata-v2",
    "schema_version": "2.0.0",
    "processing_id": "string (instance_id)",
    "timestamp": "ISO 8601",
    "tenant_id": "string",
    "feature": {
        "name": "string",
        "source_file": "string",
        "feature_index": 0,
        "description": "string"
    },
    "geometry": {
        "crs": "EPSG:4326",
        "bbox": [min_lon, min_lat, max_lon, max_lat],
        "buffered_bbox": [min_lon, min_lat, max_lon, max_lat],
        "centroid": [lon, lat],
        "area_ha": 0.0,
        "buffer_m": 100.0,
        "exterior_ring_vertex_count": 0,
        "interior_ring_count": 0,
        "area_warning": ""
    },
    "extended_data": {
        "key": "value"
    },
    "analysis": {
        "source": "kml_satellite",
        "pipeline_version": "string"
    }
}
```

### 14.2 Orchestration Input

```json
{
    "blob_url": "string",
    "container_name": "string",
    "blob_name": "string",
    "content_length": 0,
    "content_type": "string",
    "event_time": "ISO 8601",
    "correlation_id": "string",
    "tenant_id": "string",
    "output_container": "string",

    "provider_name": "string (optional)",
    "provider_config": {"key": "value"} | null,
    "imagery_filters": {"key": "value"} | null,
    "poll_interval_seconds": 30,
    "poll_timeout_seconds": 1800,
    "max_retries": 3,
    "retry_base_seconds": 5,
    "enable_clipping": true,
    "enable_reprojection": true,
    "target_crs": "EPSG:4326"
}
```

### 14.3 Contact Form Submission

```json
{
    "submission_id": "uuid",
    "email": "string",
    "organization": "string",
    "use_case": "string",
    "submitted_at": "ISO 8601",
    "source": "marketing_website",
    "ip_forwarded_for": "string (optional)"
}
```

### 14.4 Demo Submission Record

```json
{
    "submission_id": "uuid",
    "email": "string",
    "submitted_at": "ISO 8601",
    "kml_blob_name": "demo/{submission_id}.kml",
    "kml_size_bytes": 0,
    "status": "submitted"
}
```

---

## Appendix A: Constants

| Constant | Value | Unit |
|----------|-------|------|
| `MAX_KML_FILE_SIZE_BYTES` | 10,485,760 | bytes (10 MiB) |
| `PAYLOAD_OFFLOAD_THRESHOLD_BYTES` | 49,152 | bytes (48 KiB) |
| `DEFAULT_IMAGERY_RESOLUTION_TARGET_M` | 0.5 | metres |
| `DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT` | 20.0 | percent |
| `DEFAULT_AOI_BUFFER_M` | 100.0 | metres |
| `DEFAULT_AOI_MAX_AREA_HA` | 10,000.0 | hectares |
| `DEFAULT_MAX_OFF_NADIR_DEG` | 30.0 | degrees |
| `MAX_OFF_NADIR_DEG_LIMIT` | 45.0 | degrees |
| `MIN_RESOLUTION_M` | 0.01 | metres |
| `DEFAULT_POLL_INTERVAL_SECONDS` | 30 | seconds |
| `DEFAULT_POLL_TIMEOUT_SECONDS` | 1,800 | seconds |
| `DEFAULT_MAX_RETRIES` | 3 | count |
| `DEFAULT_RETRY_BASE_SECONDS` | 5 | seconds |
| `DEFAULT_POLL_BATCH_SIZE` | 10 | count |
| `DEFAULT_DOWNLOAD_BATCH_SIZE` | 10 | count |
| `DEFAULT_POST_PROCESS_BATCH_SIZE` | 10 | count |
| `API_CONTRACT_VERSION` | `"2026-03-15.1"` | — |

---

## Appendix B: Roadmap

### Target Personas

| Persona | Role | Key Need | Sample AOIs |
|---------|------|----------|-------------|
| **Conservation Analyst** | NGO / government monitoring | NDVI change detection, deforestation alerts, exportable timeline evidence | Nechako (logging), Carpathians (illegal logging), Pará (deforestation) |
| **Agricultural Advisor** | Agritech / crop insurance | Vegetation health trends, weather correlation, seasonal crop cycle tracking | Madera (orchards) |
| **ESG / Supply-Chain Compliance** | Corporate sustainability | Before/after change quantification, audit trail, deforestation-free sourcing proof | Borneo (palm oil), Pará (soy/cattle) |

### Phase 1 — Analysis & Enrichment (local)

| # | Feature | Description | Dependencies |
|---|---------|-------------|--------------|
| 1 | **NDVI layer toggle** | Compute NDVI from S2 B04/B08 bands via PC mosaic expression parameter. RdYlGn colour ramp. Toggle between RGB and NDVI per frame. | Frontend only — PC tile API supports band math |
| 2 | **Historical weather overlay** | Fetch temperature + precipitation from Open-Meteo API for AOI centroid, keyed to each timelapse frame's date window. Chart synced to playback. | Open-Meteo (free, no key) |
| 3 | **Insights panel** | Compute per-frame NDVI statistics (mean, delta). Flag significant changes (≥10% drop → potential clearing). Correlate with weather anomalies (drought, excess rain). | Builds on #1 and #2 |
| 4 | **NDVI change detection** | Pairwise frame differencing. Highlight pixels with large NDVI drops in red overlay. Quantify canopy loss area (ha). | Builds on #1 |
| 5 | **Long-term historical baselines** | Query Landsat archive (1985–present) via USGS or Google Earth Engine to compute decadal trend baselines for AOI region. Establish "normal" NDVI range, seasonal patterns, and historical extremes. Enable contextualization of recent Sentinel-2 data within 40+ year observed record. | EE API key; Landsat L2 collection; geospatial query optimization |
| 6 | **Regional climate & land-use history** | Integrate gridded datasets (NOAA CFS, ECMWF ERA5, MODIS MCD12Q1 land cover) to provide area-scale climate normals, long-term precipitation/temperature trends, and multi-year vegetation phenology maps. Show user canopy changes in context of historical meteorology and land-use transitions. | NOAA/ECMWF/USGS data ingestion; temporal alignment |

### Phase 2 — Infrastructure

| # | Feature | Description |
|---|---------|-------------|
| 7 | **Live STAC search** | Replace stub provider with real Planetary Computer queries — search, signed download, COG windowed reads |
| 8 | **Multi-polygon KML** | Handle KMLs with multiple placemarks → multiple AOIs → parallel pipeline runs |
| 9 | **CI/CD** | GitHub Actions: test → lint → Docker build → push to ACR |
| 10 | **Azure deployment** | Container Apps + Static Web App + Event Grid + Key Vault wiring |

### Phase 3 — AI Layer

| # | Feature | Description |
|---|---------|-------------|
| 11 | **Contextual AI summaries** | LLM-generated per-AOI narrative from NDVI trends + weather + open data ("12% canopy loss 2019–2022, coinciding with drought") |
| 12 | **Land-cover classification** | Pretrained model (SatlasPretrain / Clay Foundation) segments each frame into forest / cleared / agriculture / water. Enables quantified change metrics. |
| 13 | **Super-resolution upscaling** | SR4RS or equivalent upscales S2 10 m → ~2.5 m equivalent. Runs on downloaded COGs in fulfilment phase. Addresses small-AOI resolution gap. |
| 14 | **External data joins** | USDA NASS crop yield (US), FAO GAEZ (global), FIRMS active fire hotspots, Global Forest Watch alerts. Joined by bbox + date. |

### Phase 4 — Code Health (from code-review backlog)

| # | Feature | Description |
|---|---------|-------------|
| 15 | **Split enrichment module** | `enrichment.py` is ~500 lines handling weather, NDVI, mosaic registration, and timelapse manifests. Split into focused sub-modules (e.g. `enrichment/weather.py`, `enrichment/ndvi.py`, `enrichment/mosaic.py`). |
| 16 | **Extract PlanetaryComputerProvider stubs** | The provider class is 350+ lines with stub methods used only in tests. Move stubs to a dedicated test helper to keep production code lean. |
| 17 | **Distributed replay limiter** | `valet.py` tracks token replay counts in an in-memory `dict`. Replace with Azure Table Storage or Redis for correctness across multiple function instances. |
| 18 | **Blueprint activity decorator** | The orchestrator blueprint has significant boilerplate per activity (input extraction, error wrapping, storage instantiation). A thin decorator could eliminate repetition. |

## Appendix B: Blob URL Parsing

Both production and Azurite URLs must be handled:

- **Production:** `https://{account}.blob.core.windows.net/{container}/{blob_path}`
- **Azurite:** `http://127.0.0.1:10000/{account}/{container}/{blob_path}`

Detection: hostname is `127.0.0.1` or `localhost`, or port is 10000 → Azurite mode (skip first path segment as account name).

## Appendix C: Email Validation Pattern

```regex
^[^@\s]+@[^@\s]+\.[^@\s]+$
```

Applied to: contact form, demo submission, valet token recipient.
Normalisation for hashing: `lowercase(trim(email))`.
