# C4 Architecture Deep Review

**Date:** May 2026  
**Scope:** Full system walkthrough (Context → Container → Component → Code) with duplicate detection, complexity analysis, and idiomaticity assessment.  
**Audience:** Engineers making deployment, refactoring, or scaling decisions.

---

## Level 1 — System Context

### Purpose

Canopex is an EUDR/ESG compliance platform that ingests parcel boundaries (KML/KMZ), acquires satellite imagery from multiple sources, performs vegetation analysis (NDVI, change detection), and generates audit-ready evidence reports (PDF, GeoJSON, CSV).

### Users & Actors

1. **Conservation Organizations** — Upload AOIs, assess deforestation risk, export evidence for compliance.
2. **Agricultural Advisors** — Batch parcel processing, historical timelapse, integration with farm management systems.
3. **Compliance/Audit Teams** — Review evidence, cross-reference with EUDR, generate regulatory filings.
4. **System Operators** — Monitor pipeline, handle exceptions, adjust quotas and capacity.

### External Systems

| System | Protocol | Purpose | Risk |
|--------|----------|---------|------|
| **Microsoft Planetary Computer (STAC API)** | HTTPS + SAS tokens | Sentinel-2 L2A (10 m), NAIP (0.6 m) imagery search & download | Single vendor; fallback to Sentinel-2 only |
| **Azure Cosmos DB** | Native client + AAD | Records, metadata, billing ledger, org/tenant config | Manual schema versioning; no migrations tooling |
| **Azure Blob Storage** | REST + SAS | Input (KML), output (reports, TIFFs), claim-check payloads | Single region; no disaster recovery SLA |
| **Azure Durable Functions** | Event Grid + Control Queue | Orchestration, activity coordination, retry policy | Task hub locked to region; multi-region failover manual |
| **Stripe API** | REST + API keys | Subscription billing, invoice webhooks | Webhook signature validation required |
| **Azure Static Web App** | HTTPS | Frontend (landing, EUDR app, dashboard) | Depends on frontend auth (CIAM/MSAL) |
| **Azure Entra (CIAM)** | OAuth2 + MSAL | User authentication, token issuance | Scope drift; redirect URI manual management pre-#776 |

### Data Flow (Macro)

```
User (browser) 
  ↓
Frontend (Static Web App) 
  ├→ CIAM (sign-in, token) 
  └→ Function App (HTTP API)
      ↓
    Orchestrator FA
      ├→ Activities FA (parse, acquire, fulfil, enrich)
      ├→ Blob Storage (KML input, TIFFs, reports output)
      ├→ Cosmos DB (metadata, ledger, config)
      └→ Planetary Computer (imagery search & download)
```

### System Constraints

- **No multi-region**: Single Azure region (UK South). No async cross-region replication.
- **Quota-first**: Billing is per-parcel or per-month; quota gate enforced at submission time.
- **Long-running**: Pipeline phases (acquire, fulfil) can take hours. Durable Functions handles retries and resumption.
- **Imagery latency**: Sentinel-2 processing lag (5–7 days post-acquisition). NAIP infrequent (2–3 year cycles).

---

## Level 2 — Container Architecture

### Deployment Topology

```
┌─────────────────────────────────────────────────────────┐
│                    Azure Subscription                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Static Web App (frontend)                               │
│  ├─ Landing page (/)                                     │
│  ├─ EUDR app (/eudr/)                                    │
│  ├─ Signed-in dashboard (/app/)                          │
│  └─ Analytics (Application Insights)                     │
│                                                           │
│  Azure Entra (CIAM)                                      │
│  ├─ User identities                                      │
│  ├─ MSAL token issuance                                  │
│  └─ Redirect URIs (URL-based, now Tofu-managed #776)    │
│                                                           │
│  Function Apps (compute & orchestrator)                  │
│  ├─ function_app.py (compute image)                      │
│  │  ├─ All blueprints                                    │
│  │  └─ All activity functions                            │
│  ├─ function_app_orch.py (orchestrator image)            │
│  │  ├─ HTTP + durable blueprints                         │
│  │  └─ No activity functions (lighter footprint)         │
│  └─ Shared dependencies: treesight.*, blueprints.*       │
│                                                           │
│  Durable Functions (orchestration)                       │
│  ├─ Task hub: DurableFunctionsHub (shared between both FA)│
│  ├─ Control queue (Azure Queue Storage)                  │
│  └─ Orchestration history: Azure Storage backend         │
│     (storageProvider__type=AzureStorage in main.tf)      │
│                                                           │
│  Blob Storage (containers)                               │
│  ├─ kml-input        (uploaded KML/KMZ submissions)      │
│  ├─ kml-output       (rendered reports, TIFFs, exports)  │
│  ├─ pipeline-payloads (claim-check / offload staging)    │
│  └─ other containers (config, backups)                   │
│                                                           │
│  Cosmos DB                                               │
│  ├─ Database: canopex                                    │
│  ├─ Container: records (submissions, runs, metadata)     │
│  ├─ Container: ledger (billing events)                   │
│  ├─ Container: orgs (tenant config, owners, quotas)      │
│  └─ Container: cache (rate limits, replay tokens)        │
│                                                           │
│  Azure Queue Storage (support)                           │
│  ├─ Durable control queue                                │
│  └─ Dead-letter queue (failed messages)                  │
│                                                           │
│  Application Insights (monitoring)                       │
│  ├─ Function app traces, metrics                         │
│  ├─ Custom events (pipeline phase transitions)           │
│  └─ Dependency tracking (Cosmos, Blob, Planetary PC)     │
│                                                           │
└─────────────────────────────────────────────────────────┘

External:
  ├─ Planetary Computer (STAC API)
  ├─ Stripe API (billing webhooks)
  └─ Internet (user traffic, imagery downloads)
```

### Function Apps: Design Pattern

| Image | Entry Point | Blueprints | Activities | Purpose |
|-------|-------------|-----------|-----------|---------|
| **Compute** | `function_app.py` | All 13 | ✅ Registered | Process KML, search imagery, render reports |
| **Orchestrator** | `function_app_orch.py` | All 13 | ❌ Skipped | Coordinate phases, retry, fan-out/fan-in |

**Current state**: Both function apps register **all blueprints** via `function_registration.py`. The role split is currently driven by `PIPELINE_ROLE` (`full` vs `orchestrator`), which only gates whether the durable `activities` submodule is imported — it does *not* gate HTTP blueprint registration. The orchestrator hostname is the browser-facing API base (`/api-config.json`), so HTTP routes deliberately live there today.

```python
# function_registration.py (current)
def _shared_blueprints():
    return (
        health_bp,      # ✅ both — readiness/liveness
        billing_bp,     # ✅ both — Stripe webhooks + invoice queries
        analysis_bp,    # 🟡 browser-facing; only the orchestrator FA needs it
        export_bp,      # 🟡 browser-facing; only the orchestrator FA needs it
        eudr_bp,        # 🟡 browser-facing; only the orchestrator FA needs it
        ...
    )
```

**Why this matters:**
- The compute image registers HTTP routes it should never serve, increasing attack surface and image size.
- Each route pulls dependencies (e.g., `export.py` imports TIF rendering libs even if never called from compute).
- Harder to reason about which FA is responsible for which logic.

**Proposed state** — Issue #779: stop the **compute** image from registering browser-facing HTTP blueprints. Keep `health_bp`, `pipeline_bp` activity triggers, and `monitoring_bp` on compute. Leave `analysis_bp`, `export_bp`, `eudr_bp`, `catalogue_bp`, `contact_bp`, `demo_bp`, `ops_bp`, `org_bp`, `upload_bp` on the orchestrator FA (which already fronts the browser). `billing_bp` and `health_bp` stay registered on both. Implementation can extend the existing `PIPELINE_ROLE` env var rather than introducing a new one.

---

## Level 3 — Component Architecture

### Blueprint Structure

Line counts captured from `main` at the time of writing — regenerate via `wc -l blueprints/*.py` if drift is suspected.

| Blueprint | File | Lines | HTTP Routes | Purpose | Notes |
|-----------|------|-------|-------------|---------|-------|
| **pipeline** | `blueprints/pipeline/` | 700+ | `/api/submit`, `/api/status/{id}`, triggers | Durable orchestration | Core logic; well-separated phases |
| **analysis** | `blueprints/analysis.py` | 755 | `/api/analysis/*` | AI-based analysis (NDVI, phenology) | Helper functions like `_run_analysis_impl` have multiple concerns |
| **export** | `blueprints/export.py` | 1529 | `GET /api/export/{instance_id}/{format}` (+ OPTIONS) | GeoJSON, CSV, PDF rendering | **🔴 TOO LARGE** — mixes blob I/O, data munging, format rendering |
| **eudr** | `blueprints/eudr.py` | 701 | `/api/eudr/*` | EUDR compliance UI, billing, evidence | Heavy lifting for org lookup, billing, usage tracking |
| **upload** | `blueprints/upload.py` | 567 | `/api/upload/token`, `/api/upload/status` | SAS token minting, submission records | Orchestrates auth, quota, EUDR checks, storage writes |
| **billing** | `blueprints/billing.py` | 576 | `/api/billing/*` | Invoice history, subscription endpoints | Stripe webhook handling, ledger queries |
| **catalogue** | `blueprints/catalogue.py` | 201 | `/api/catalogue/*` | Historical records, AOI metadata | Simple CRUD; delegation to storage layer |
| **org** | `blueprints/org.py` | 300 | `/api/org`, `/api/org/invite`, `/api/org/members` | Org management, owner checks | Multi-tenancy logic; some duplication with EUDR |
| **health** | `blueprints/health.py` | 211 | `/health`, `/health/deep` | Readiness, liveness, dependency checks | Clean separation of concerns |
| **monitoring** | `blueprints/monitoring.py` | 405 | Scheduler + `/metrics` | Timer-triggered tasks, quota resets | Scheduler registration conditional on compute image |
| **contact** | `blueprints/contact.py` | 29 | `/api/contact/` | Email forwarding to support | Simple relay; minor integration |
| **demo** | `blueprints/demo.py` | 200 | `/api/proxy` | Proxy for live data; sample report generation | 🟡 SSRF risk in `/api/proxy` — needs audit (#784) |
| **ops** | `blueprints/ops.py` | 403 | Admin routes (internal) | Quota override, manual interventions | Minimal documentation of who should call |

### Core Library: `treesight/`

```
treesight/
├── __init__.py
├── config.py               (env vars, schema, validation)
├── constants.py            (magic numbers, limits, defaults)
├── log.py                  (structured logging, trace context)
├── errors.py               (exception hierarchy)
├── enums.py                (WorkflowState, OrderState, etc.)
├── models/
│   ├── aoi.py              (Area of Interest: geometry, computed properties)
│   ├── imagery.py           (SearchResult, ImageryFilters)
│   ├── records.py           (RunRecord, OrderRecord, BillingRecord)
│   ├── blob_event.py        (Event Grid blob trigger parsing)
│   └── ...
├── parsers/                (KML/KMZ detection, Fiona/lxml fallback)
│   ├── __init__.py          (dispatcher)
│   ├── fiona_parser.py      (primary; GDAL-based)
│   └── lxml_parser.py       (fallback; XXE-safe)
├── pipeline/               (orchestration logic)
│   ├── ingestion.py         (KML parsing, AOI prep, fan-out)
│   ├── acquisition.py       (imagery search, order polling)
│   ├── fulfillment.py       (TIF rendering: NDVI, change detect, SCL)
│   ├── enrichment.py        (contextual data: weather, flood risk, labels)
│   ├── orchestrator.py      (phase coordinator, claim-check payload mgmt)
│   └── ...
├── providers/              (imagery data sources)
│   ├── base.py              (abstract ImageryProvider)
│   ├── planetary_computer.py (STAC API: Sentinel-2, NAIP)
│   ├── geo_router.py        (provider selection by geography)
│   └── stub_provider.py     (test fixtures)
├── security/               (auth, quotas, billing)
│   ├── auth.py              (MSAL token validation, scope checking)
│   ├── orgs.py              (multi-tenancy: owner lookup, quota gates)
│   ├── quotas.py            (consumption tracking, tier enforcement)
│   ├── billing.py           (invoice generation, overage calc)
│   ├── hmac_auth.py         (valet token HMAC replay protection)
│   └── ...
├── storage/                (data access)
│   ├── cosmos.py            (singleton CosmosClient + AAD)
│   ├── client.py            (BlobStorageClient: upload, download, SAS)
│   ├── offload.py           (claim-check: blob staging for large payloads)
│   └── cache.py             (in-memory + Cosmos rate-limit buckets)
└── services/               (domain orchestrators, helpers)
    ├── change_detector.py   (temporal NDVI diff logic)
    ├── enrichment_runner.py (weather, flood, label APIs)
    └── ...
```

### Key Modules: Responsibilities

#### 🟢 **Clean Separation**

- **`treesight/models/`**: Pure data classes (Pydantic). No I/O. No coupling to infrastructure.
- **`treesight/security/auth.py`**: Token validation only. Delegates to CIAM, doesn't mock tokens.
- **`treesight/providers/base.py`**: Abstract interface. Implementations plug in without ceremony.

#### 🟡 **Acceptable Coupling**

- **`treesight/pipeline/`**: Calls activities, storage, providers. Orchestration by nature has broad reach.
- **`blueprints/pipeline/`**: HTTP routes + Durable Functions decorators. Necessary binding.

#### 🔴 **Too Much Responsibility**

- **`blueprints/export.py` (1529 LOC)**: Blob I/O + data extraction + CSV/JSON building + PDF rendering + HTTP routing. Should be split into:
  - `treesight/exports/geojson_builder.py` — build GeoJSON dict from manifest.
  - `treesight/exports/csv_builder.py` — build CSV rows.
  - `treesight/exports/pdf_renderer.py` — render PDF (external or library).
  - `blueprints/export.py` (refactored, ~150 LOC) — HTTP routes, SAS, error handling.

- **`blueprints/analysis.py` (400+ LOC)**: Multiple concerns in `_run_analysis_impl`:
  - Auth check ✓ (needed).
  - Rate-limiting ✓ (needed).
  - Body size validation ✓ (needed).
  - JSON parsing ✓ (needed).
  - Conditional NDVI requirement (could move to validator).
  - Exception handling (generic, could tighten).

- **`blueprints/upload.py` (550+ LOC)**: `upload_token` function (115 LOC) orchestrates:
  - EUDR entitlement check.
  - Quota consumption.
  - SAS token minting.
  - Ticket blob write.
  - Trial consumption.
  - Record persistence.
  All in a single request handler. Should delegate to domain classes:
  ```python
  # e.g. treesight/submission/submission_handler.py
  class SubmissionHandler:
      def mint_token(self, user_id, body, req) -> (sas_url, submission_id):
          self.check_eudr_entitlement(...)
          self.consume_quota(...)
          sas_url = self.mint_sas(...)
          self.persist_record(...)
          return sas_url, submission_id
  ```

- **`blueprints/eudr.py` (701 LOC)**: Usage aggregation (`_eudr_usage_payload`) + billing tier logic + org lookup. Heavy lifting could move to a domain layer.

---

## Level 4 — Code Review (Idiomaticity, Duplication, Complexity)

### Function-Level Analysis

#### Most Complex Functions

| Function | File | LOC | Cyclomatic | Issue |
|----------|------|-----|-----------|-------|
| `_phase_ingestion` | `blueprints/pipeline/orchestrator.py` | ~70 | High | Multiple nested yields, payload manipulations |
| `_phase_acquisition` | `blueprints/pipeline/orchestrator.py` | ~80 | High | Batch logic + polling + retry options |
| `upload_token` | `blueprints/upload.py` | 115 | High | Orchestrates 5+ operations sequentially |
| `_run_analysis_impl` | `blueprints/analysis.py` | ~50 | Medium | Auth + rate-limit + parsing + delegation |
| `_eudr_usage_payload` | `blueprints/eudr.py` | ~70 | Medium | Billing aggregation + tier logic |
| `_build_geojson` | `blueprints/export.py` | ~80 | Medium | Iterative frame building + metadata extraction |
| `_build_csv` | `blueprints/export.py` | ~120 | High | Nested loops, change-detection lookups |

**Assessment**: Phases are inherently complex (orchestration = sequential control flow). The issue is **not inherent complexity but lack of helper extraction**. Examples:

```python
# ❌ current: _phase_ingestion mixes concerns
def _phase_ingestion(context, inp, instance_id, ctx) -> _PhaseGen:
    features = (yield context.call_activity("parse_kml", inp))
    if isinstance(features, list):
        feature_list = features
        offloaded = False
    else:  # offloaded
        feature_list = (yield context.call_activity("load_offloaded_features", features))
        offloaded = True
    # ... claim-check logic ...
    aoi_refs = (yield context.call_activity("store_aoi_claims", {...}))
    # ... fan-out metadata writes ...
    return {...}

# ✅ better: extract helpers
def _phase_ingestion(context, inp, instance_id, ctx) -> _PhaseGen:
    features = yield from _load_features(context, inp)
    aoi_refs = yield from _prepare_and_store_aois(context, features, instance_id, inp)
    metadata = yield from _write_metadata_fan_out(context, aoi_refs, inp, ctx)
    coords = _extract_enrichment_coords(aoi_refs)
    return _ingestion_result(features, aoi_refs, metadata, coords)
```

#### Duplicate Code Patterns

**Duplication 1: Export logic**

```python
# blueprints/export.py — _build_geojson
for i, frame in enumerate(frame_plan):
    ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None
    props = {
        "frame_index": i,
        "label": frame.get("label", ""),
        ...
    }

# blueprints/export.py — _build_csv (same pattern)
for i, frame in enumerate(frame_plan):
    ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None
    # extract same fields from frame, ndvi, etc.
```

**Fix**: Extract a `FrameRow` model:
```python
class FrameRow(BaseModel):
    frame_index: int
    label: str
    year: int | None
    # ... all fields
    
    @classmethod
    def from_manifest_frame(cls, frame: dict, ndvi: dict | None, index: int):
        return cls(
            frame_index=index,
            label=frame.get("label", ""),
            ...
        )

# Use in both GeoJSON and CSV builders:
rows = [FrameRow.from_manifest_frame(f, ndvi_stats[i] if i < len(ndvi_stats) else None, i) 
        for i, f in enumerate(frame_plan)]
```

**Duplication 2: Org/owner lookup**

```python
# blueprints/eudr.py — _check_eudr_entitlement
org = get_user_org(user_id)
org_id = org.get("org_id") if isinstance(org, dict) else ""

# blueprints/org.py — route handler
org = get_user_org(user_id)
owner = org.get("owner_id", "")
```

**Fix**: Standardize `get_user_org` to always return a typed object or raise:
```python
from treesight.security.orgs import UserOrg

user_org = get_user_org(user_id)  # raises if not found
org_id = user_org.org_id
owner = user_org.owner_id
```

**Duplication 3: CORS + auth check in every route**

```python
# blueprints/upload.py
def upload_token(req, *, auth_claims, user_id):
    if req.method == "OPTIONS":
        return cors_preflight(req)
    try:
        check_auth(req)
    except ValueError:
        return error_response(401, ...)

# blueprints/analysis.py
def _run_analysis_impl(req, context, ...):
    if req.method == "OPTIONS":
        return cors_preflight(req)
    try:
        check_auth(req)
    except ValueError:
        return error_response(401, ...)

# (repeated 10+ times)
```

**Fix**: Use a decorator or middleware (if Azure Functions supports it):
```python
@require_auth(cors=True)
@rate_limit_if(limiter_instance)
def upload_token(req: func.HttpRequest) -> func.HttpResponse:
    # body omitted; auth + CORS already handled
    ...
```

(Azure Functions doesn't have middleware, but decorators can wrap the handler. Alternatively, extract a `@authenticated_http_route` helper that does the checks and yields to the actual logic.)

#### Idiomatic Patterns

**Good:**

```python
# treesight/storage/cosmos.py — lazy singleton with lock
_lock = threading.RLock()
_client: CosmosClient | None = None

def _get_client() -> CosmosClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:  # double-check lock pattern
                _client = CosmosClient(endpoint, credential=DefaultAzureCredential())
    return _client
```

✅ Thread-safe, deferred initialization, handles credential refresh.

**Good:**

```python
# treesight/models/aoi.py — Pydantic with defaults
class AOI(BaseModel):
    feature_name: str
    area_ha: float = 0.0
    metadata: dict[str, str] = Field(default_factory=dict)
    area_warning: str = ""
```

✅ Clear schema, mutable defaults (dict) use `default_factory`. Serialization/validation automatic.

**Questionable:**

```python
# blueprints/pipeline/orchestrator.py — cast everywhere
features = cast("Any", (yield context.call_activity("parse_kml", inp)))
aoi_tasks = [...]
aois = cast("list[dict[str, Any]]", (yield context.task_all(aoi_tasks)))
```

⚠️ `cast` is a type-hint-only directive; it does **nothing at runtime**. These should be documented with comments or return-type annotations on the Durable task. Excessive casting obscures actual runtime types.

```python
# Better:
def _activity_result_as[T](result: Any, expected_type: type[T]) -> T:
    """Validate and cast activity result to expected type (runtime check)."""
    if not isinstance(result, expected_type):
        raise TypeError(f"Expected {expected_type}, got {type(result)}")
    return result

features: list[dict] = _activity_result_as(
    (yield context.call_activity("parse_kml", inp)),
    list
)
```

**Questionable:**

```python
# blueprints/eudr.py — complex dict lookups without defaults
next_threshold = None
next_rate = None
for threshold, rate in ((100, 2.50), (500, 1.80)):
    if period_used < threshold:
        next_threshold = threshold
        next_rate = rate
        break
```

⚠️ Magic numbers (100, 500, 2.50, 1.80) hardcoded. Should be a config-driven tier list:

```python
from treesight.constants import EUDR_TIERS  # [(100, 2.50), (500, 1.80), ...]

next_tier = next(
    (tier for threshold, rate in EUDR_TIERS if period_used < threshold),
    None
)
next_threshold, next_rate = next_tier if next_tier else (None, None)
```

#### Shallow vs. Deep Functions

**Shallow (✅ good):**

```python
# treesight/storage/cosmos.py
def cosmos_available() -> bool:
    return bool(config.COSMOS_ENDPOINT)
```

Clear, single responsibility, testable.

**Deep (❌ problem):**

```python
# blueprints/upload.py::upload_token (115 LOC)
def upload_token(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    if not user_id:
        return error_response(401, "Missing user identity", req=req)
    
    # ... parse body ...
    is_eudr = body.get("eudr_mode") is True
    
    # ... EUDR entitlement gate ...
    eudr_org_id, entitlement, err = _check_eudr_entitlement(user_id, req)
    if err:
        return err
    
    # ... consume quota ...
    quota_consumed, billing_fields, quota_err = _consume_upload_quota(user_id, req)
    
    # ... prepare submission ...
    submission_id = str(uuid.uuid4())
    ext, content_type = _detect_file_extension(...)
    
    # ... write SAS ...
    sas_url, storage_err = _write_ticket_and_mint_sas(...)
    
    # ... consume trial ...
    eudr_err = _consume_eudr_trial_if_needed(...)
    
    # ... persist record ...
    run = RunRecord(...)
    _persist_submission_record(...)
    
    return func.HttpResponse(json.dumps({...}))
```

This is **not terrible** (it delegates heavy lifting) but it orchestrates many steps. The issue: if any middle step fails, the logic becomes harder to understand. Better to extract:

```python
class UploadTokenMinter:
    def __init__(self, user_id: str, body: dict, req: func.HttpRequest):
        self.user_id = user_id
        self.body = body
        self.req = req
    
    def mint(self) -> tuple[str, str] | func.HttpResponse:  # (sas_url, submission_id) or error
        self.validate_user()
        self.check_eudr_entitlement()
        self.consume_quota()
        self.mint_sas()
        self.persist_record()
        return self.sas_url, self.submission_id

# In blueprint:
def upload_token(req: func.HttpRequest, *, auth_claims: dict, user_id: str):
    body = req.get_json()
    minter = UploadTokenMinter(user_id, body, req)
    result = minter.mint()
    if isinstance(result, func.HttpResponse):
        return result  # error
    sas_url, submission_id = result
    return func.HttpResponse(json.dumps({...}), status_code=200)
```

---

## Architecture Findings

### 🔴 Critical Issues

| ID | Title | File | Severity | Impact | Fix Complexity |
|----|-------|------|----------|--------|----------------|
| **#779** | Orchestrator Function App registers all HTTP blueprints (compute-only). Should register only `health_bp`, `pipeline_bp`, `monitoring_bp` (conditional) | `function_registration.py` | 🔴 High | Bloated orchestrator image, unnecessary attack surface, confused ownership | Medium — requires blueprint reorganization |
| **#780** | `blueprints/export.py` is 1529 LOC — mixes blob I/O, data extraction, rendering, HTTP routing | `blueprints/export.py` | 🔴 High | Untestable, hard to debug export failures, violation of single responsibility | High — requires domain-layer extraction |

### 🟡 Important Issues

| ID | Title | File | Severity | Impact | Fix Complexity |
|----|-------|------|----------|--------|----------------|
| **#782** | Stale `X-MS-CLIENT-PRINCIPAL` CORS allowlist and test-mode escape hatch — no longer used in production | `blueprints/_helpers.py` | 🟡 Medium | Potential confusion about auth flow; obscured by legacy code path | Low — remove when `CANOPEX_TEST_MODE` retires |
| **#784** | `/api/proxy` in `blueprints/demo.py` lacks upstream-host allowlist — potential SSRF | `blueprints/demo.py` | 🟡 Medium | Lateral movement risk if orchestrator compromised | Medium — add allowlist validation |
| **#785** | `blueprints/analysis.py` (755 LOC) and `blueprints/eudr.py` (701 LOC) both mix HTTP routing + domain logic — plan split | `blueprints/analysis.py`, `blueprints/eudr.py` | 🟡 Medium | Testing complexity; reuse across SPA + orchestration difficult | High — requires domain-layer architecture |
| **#781** | CIAM app registration management — partially addressed by #776 (redirect URIs now Tofu); residual: scopes, permissions, secret rotation still manual | `infra/tofu/` | 🟡 Medium | Manual drift gap; configuration as documentation only | Medium — complete Tofu coverage (PR #776 partial) |
| **#783** | `website/js/app-msal.js` docstring references `app-auth.js` (no longer exists); likely moot post-#775 consolidation | `website/js/canopex-auth.js` | 🟡 Low | Stale documentation | Low — verify against current file, close if clean |

### 🟢 Non-Issues (Acceptable Design)

| Item | Why It's OK |
|------|-----------|
| **Phase orchestrator complexity** | Durable Functions inherently require sequential/parallel coordination. The phases are cleanly separated generators. Complexity is manageable with helper extraction (not a breaking issue). |
| **Claim-check pattern** | Necessary for large AOI payloads (keeps orchestrator history under 48 KiB). Blob offload is well-justified. |
| **Multi-region lack** | Acceptable for current scale; if volumes grow, design async replication at that time. |
| **No full CIAM automation** | PR #776 addressed the critical gap (redirect URIs). Full app reg under Tofu is nice-to-have, not critical. |
| **In-memory cache fallback** | Rate-limit + replay-protection caches have in-memory fallback when Cosmos is unavailable. Acceptable degradation. |
| **Duplicate auth checks** | Every route calls `check_auth`. Repetitive but clear and safe; decorator refactor is improvement but not essential. |

---

## Recommendations & Roadmap

### Priority 1: Clean Up Attack Surface & Sizing (1–2 weeks)

1. **#779** — Stop the compute image from registering browser-facing HTTP blueprints.
   - Extend the existing `PIPELINE_ROLE` env var (`full` vs `orchestrator`) so `function_registration.py` skips browser-facing blueprints when `PIPELINE_ROLE != "orchestrator"`. Avoid introducing a separate `DEPLOYMENT_ROLE` variable.
   - Reduce compute image HTTP surface and dependency footprint.

2. **#780** — Extract `treesight/exports/` domain layer.
   - Move GeoJSON, CSV, PDF logic to domain builders.
   - Blueprint routes become thin wrappers (20–30 LOC).

### Priority 2: Security Hardening & Test Coverage (2–3 weeks)

3. **#784** — Add upstream allowlist to `/api/proxy`.
   - Validate `upstream_url` parameter against fixed list of Planetary Computer + public data sources.
   - Log and reject any other URLs.

4. **#782** — Retire `X-MS-CLIENT-PRINCIPAL` CORS exception.
   - Remove from allowlist when `CANOPEX_TEST_MODE` env var is no longer used.
   - Audit codebase for lingering references.

### Priority 3: Refactoring for Reusability (3–4 weeks)

5. **#785** — Extract domain layer from `analysis.py` and `eudr.py`.
   - Create `treesight/analysis/`, `treesight/eudr/` packages with domain logic.
   - Blueprints delegate to domain orchestrators (mimics clean architecture).
   - Enables reuse across SPA endpoints + orchestration.

6. **#781 (residual)** — Expand Tofu CIAM coverage.
   - Add app scopes and permissions under Tofu (post-#776 redirect URI work).
   - Document as code-of-record for app configuration.

### Priority 4: Code Quality & Testing (Ongoing)

7. **Decorator refactoring** — Extract `@authenticated_http_route` and `@rate_limited` helpers (once Azure Functions decorator support is clearer).

8. **Typing** — Replace `cast(...)` with runtime validation helpers. Improve IDE support and debuggability.

9. **Constants** — Move all magic numbers to `treesight/constants.py` (EUDR tiers, Planetary Computer collection names, timeout values).

---

## Summary Table: Architectural Health

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **User Isolation (Multi-tenancy)** | ✅ Good | `get_user_org()` + quota gates work. Org ownership enforced. |
| **Data Flow Clarity** | ✅ Good | Ingestion → Acquisition → Fulfilment → Enrichment phases are well-named and separated. |
| **Error Handling** | ✅ Good | Structured error responses; activity retries with exponential backoff. |
| **Dependency Injection** | ⚠️ Fair | Singletons (Cosmos, Blob) are thread-safe but global. Consider DI container for testability. |
| **Code Duplication** | ⚠️ Fair | Moderate duplication in export logic, org lookups, auth checks. Extractable. |
| **Function Size** | ⚠️ Fair | `export.py` (1529 LOC), `eudr.py` (701), `analysis.py` (755) are too large. Refactoring recommended. |
| **Blueprint Organization** | ❌ Needs Work | Both FAs register all blueprints. Attack surface bloat. Should split by role. |
| **Testing Coverage** | ✅ Good | ~1200 tests across 52 files. Pipeline + auth + billing all covered. |
| **Observability** | ✅ Good | Application Insights + custom events + structured logging. Traces follow requests end-to-end. |

---

## Conclusion

The architecture is **sound at L1–L2** (system context and container level). The orchestration pattern (Durable Functions + claim-check) is appropriate and well-executed. The remaining friction is at L3–L4:

1. **Blueprint over-registration** (#779) creates unnecessary coupling and attack surface.
2. **Large blueprints** (#780, #785) mix concerns; extraction enables reuse and testing.
3. **Duplicate patterns** (export logic, auth checks, org lookup) can be unified with modest refactoring.
4. **Security gaps** (#784, #782) are fixable with targeted changes.

**Overall verdict**: Production-ready, well-tested, but ready for refactoring to improve maintainability, scalability, and testing. The listed issues are **not blockers** but **worthwhile improvements** for the next 1–2 quarters.
