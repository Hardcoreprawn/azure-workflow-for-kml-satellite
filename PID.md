# Project Initiation Document (PID)

## Azure Workflow for KML Ingestion and High-Resolution Satellite Imagery Acquisition

| Field | Detail |
| --- | --- |
| **Document Version** | 1.1 |
| **Date** | 15 February 2026 |
| **Status** | Draft |
| **Classification** | Internal |

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Business Case & Justification](#2-business-case--justification)
3. [Project Objectives](#3-project-objectives)
4. [Scope](#4-scope)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Solution Architecture](#7-solution-architecture)
    - [7.4 Engineering Philosophy & Design Principles](#74-engineering-philosophy--design-principles)
    - [7.5 Compute Model Decision Record](#75-compute-model-decision-record)
    - [7.6 Imagery Provider Strategy](#76-imagery-provider-strategy)
8. [Technology Stack](#8-technology-stack)
9. [Data Flow](#9-data-flow)
10. [Storage Strategy](#10-storage-strategy)
11. [Security & Credential Management](#11-security--credential-management)
12. [Logging, Monitoring & Error Handling](#12-logging-monitoring--error-handling)
13. [Assumptions](#13-assumptions)
14. [Constraints](#14-constraints)
15. [Dependencies](#15-dependencies)
16. [Risks & Mitigations](#16-risks--mitigations)
17. [Out of Scope](#17-out-of-scope)
18. [Project Phases & Milestones](#18-project-phases--milestones)
19. [Estimated Effort & Resource Plan](#19-estimated-effort--resource-plan)
20. [Acceptance Criteria](#20-acceptance-criteria)
21. [Approval & Sign-Off](#21-approval--sign-off)

---

## 1. Project Overview

This project delivers an **automated, cloud-native workflow** hosted on Microsoft Azure that ingests KML files containing agricultural field and orchard boundaries, extracts polygon geometry and metadata, acquires very-high-resolution satellite imagery covering those areas of interest (AOIs), and persists the imagery alongside structured metadata in Azure Blob Storage for downstream analytical consumption.

The system is designed to support precision-agriculture use cases where up-to-date, sub-meter satellite imagery of specific orchards or fields is required on a recurring basis.

---

## 2. Business Case & Justification

| Driver | Description |
| --- | --- |
| **Operational Efficiency** | Eliminates manual steps of uploading KML files, querying imagery providers, downloading imagery, and organising outputs. |
| **Scalability** | Supports concurrent processing of many KML uploads with no per-file manual intervention. |
| **Reproducibility** | Every AOI is processed through an identical, auditable pipeline with full metadata lineage. |
| **Extensibility** | Lays the foundation for future phases (e.g., tree detection, NDVI analysis, change detection) by delivering analysis-ready imagery in a structured store. |
| **Time-to-Insight** | Reduces the turnaround from field-boundary definition to imagery availability from days (manual) to minutes/hours (automated). |

---

## 3. Project Objectives

| # | Objective | Measurable Outcome |
| --- | --- | --- |
| O-1 | Automated KML detection and ingestion | Pipeline triggers within 60 seconds of a new KML upload |
| O-2 | Polygon geometry extraction from KML | Correct extraction of single polygon, multipolygon, and multi-feature files with validation |
| O-3 | AOI preparation and metadata generation | Buffered bounding box, centroid, area (ha), and CRS metadata produced for every polygon |
| O-4 | High-resolution satellite imagery acquisition | Imagery at ≤ 50 cm/pixel retrieved and stored for each AOI (configurable resolution target) |
| O-5 | Structured cloud storage | All outputs stored in Azure Blob with a well-defined folder hierarchy and companion metadata JSON |
| O-6 | Provider-agnostic imagery architecture | Imagery retrieval layer abstracted behind an interface, allowing future provider substitution without pipeline changes |
| O-7 | Robust error handling and logging | All processing steps logged; failures flagged; automatic retry mechanism in place |

---

## 4. Scope

### 4.1 In Scope

- Monitoring a designated upload location (Azure Blob Storage container, with optional OneDrive/SharePoint bridge) for new `.kml` files
- Parsing and validation of KML geometry (WGS 84 assumed; CRS validated)
- Extraction of polygon coordinates, bounding box, centroid, and area
- Generation of buffered AOI queries compatible with satellite imagery provider APIs
- Retrieval of very-high-resolution satellite imagery (≤ 50 cm/pixel preferred) via a provider API
- Support for archive imagery requests, tile/mosaic downloads, and scene downloads
- Clipping imagery to AOI polygon (preferred)
- Reprojection of imagery if required
- Storage of raw and processed imagery in Azure Blob Storage (GeoTIFF)
- Production and storage of metadata JSON for each processed AOI
- Orchestration via Azure serverless / event-driven services
- Concurrent multi-file processing
- Comprehensive logging and error handling with retry

### 4.2 Out of Scope

| Item | Rationale |
| --- | --- |
| Tree detection, counting, or computer vision | Planned for a future phase |
| NDVI, vegetation index, or spectral analysis | Planned for a future phase |
| User interface / web portal | Not required in this phase; files are uploaded directly to the monitored location |
| Satellite tasking (new capture requests) | Only archive/existing imagery retrieval is in scope |
| Billing or usage dashboards | Operational concern to be addressed separately |
| On-premises deployment | Azure-only deployment |

---

## 5. Functional Requirements

### FR-1: KML Ingestion Pipeline

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-1.1 | Monitor a designated Azure Blob Storage container for new `.kml` file uploads | Must |
| FR-1.2 | Optionally bridge OneDrive / SharePoint uploads into the monitored container | Should |
| FR-1.3 | Trigger processing automatically within 60 seconds of upload | Must |
| FR-1.4 | Support single polygon, multipolygon, and multiple features per KML file | Must |
| FR-1.5 | Extract geometry coordinates (lat/lon vertices) from each feature | Must |
| FR-1.6 | Compute bounding box for each polygon | Must |
| FR-1.7 | Compute polygon area in hectares | Must |
| FR-1.8 | Compute polygon centroid | Must |
| FR-1.9 | Assume WGS 84 (EPSG:4326) CRS; validate and reject or reproject if different | Must |
| FR-1.10 | Parse and preserve associated metadata (orchard name, tree variety, location label) if present in KML | Should |

### FR-2: Area of Interest (AOI) Processing

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-2.1 | Generate a buffered bounding box around each polygon with a configurable margin (default 100 m, range 50–200 m) | Must |
| FR-2.2 | Format AOI query payload compatible with the configured imagery provider API | Must |
| FR-2.3 | Log all AOI metadata (coordinates, area, buffer applied, timestamp) | Must |

### FR-3: High-Resolution Satellite Imagery Retrieval

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-3.1 | Implement a provider-agnostic abstraction layer (strategy/adapter pattern) for imagery retrieval | Must |
| FR-3.2 | Implement at least two provider adapters: Microsoft Planetary Computer (STAC, dev/test) and SkyWatch EarthCache (production) | Must |
| FR-3.3 | Target spatial resolution ≤ 50 cm/pixel; make resolution target system-configurable | Must |
| FR-3.4 | Support archive imagery search and download | Must |
| FR-3.5 | Support tile mosaic download mode | Should |
| FR-3.6 | Support full-scene download covering AOI | Should |
| FR-3.7 | Handle API authentication (OAuth2, API keys) via Azure Key Vault | Must |
| FR-3.8 | Submit imagery search/order queries to provider API | Must |
| FR-3.9 | Poll asynchronous job status until completion (with timeout) | Must |
| FR-3.10 | Download imagery upon job completion | Must |
| FR-3.11 | Reproject imagery to a target CRS if the delivered CRS differs from the project standard | Should |
| FR-3.12 | Clip imagery to the AOI polygon boundary | Should |
| FR-3.13 | Apply configurable filters: maximum cloud cover %, date range, off-nadir angle | Should |

### FR-4: Imagery & Metadata Storage

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-4.1 | Store original KML files under `/kml/` path prefix | Must |
| FR-4.2 | Store raw (unclipped) imagery under `/imagery/raw/` path prefix | Must |
| FR-4.3 | Store clipped imagery under `/imagery/clipped/` path prefix | Should |
| FR-4.4 | Store metadata JSON records under `/metadata/` path prefix | Must |
| FR-4.5 | Output imagery in GeoTIFF format | Must |
| FR-4.6 | Produce a metadata JSON per AOI containing: acquisition date, provider name, spatial resolution, CRS, cloud cover %, AOI area (ha), bounding box coordinates, processing timestamp | Must |
| FR-4.7 | Organise storage hierarchy by date and/or orchard name for easy downstream access | Should |

### FR-5: Processing Orchestration

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-5.1 | Use event-driven triggering (Azure Event Grid or Blob Storage trigger) | Must |
| FR-5.2 | Implement processing logic in Azure Functions (Python preferred) | Must |
| FR-5.3 | Use Durable Functions for long-running imagery acquisition workflows | Must |
| FR-5.4 | Support multiple concurrent KML uploads without conflict | Must |
| FR-5.5 | Use Azure Key Vault for all secrets and API credentials | Must |
| FR-5.6 | Use environment-based configuration (Azure App Configuration or Function App settings) | Should |

### FR-6: Logging & Error Handling

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-6.1 | Log every processing step with timestamp, correlation ID, and status | Must |
| FR-6.2 | Log failed imagery queries with provider error details | Must |
| FR-6.3 | Flag AOIs where imagery is unavailable (e.g., cloud cover too high, no archive coverage) | Must |
| FR-6.4 | Implement automatic retry with exponential backoff (configurable max retries, default 3) | Must |
| FR-6.5 | Dead-letter failed items after max retries for manual review | Should |
| FR-6.6 | Surface logs via Azure Monitor / Application Insights | Should |

---

## 6. Non-Functional Requirements

| ID | Category | Requirement |
| --- | --- | --- |
| NFR-1 | **Performance** | End-to-end processing (KML upload → imagery stored) must complete within 30 minutes for a single AOI, excluding imagery provider fulfilment time |
| NFR-2 | **Scalability** | Must process at least 20 concurrent KML uploads (each containing up to 10 polygons) without degradation |
| NFR-3 | **Availability** | Target 99.5 % uptime for the ingestion trigger and orchestration layer (aligned with Azure Functions SLA) |
| NFR-4 | **Reliability** | No data loss — every uploaded KML must be processed or explicitly flagged as failed |
| NFR-5 | **Security** | All secrets stored in Azure Key Vault; Blob Storage accessed via Managed Identity; no credentials in code or config files |
| NFR-6 | **Maintainability** | Modular codebase with clear separation: ingestion, AOI processing, imagery retrieval (adapter pattern), storage, orchestration |
| NFR-7 | **Observability** | Structured logging with correlation IDs; dashboards for processing throughput and error rates |
| NFR-8 | **Cost Efficiency** | Flex Consumption Azure Function plan to minimise idle costs (~$0 at zero scale); free imagery (Planetary Computer) for dev/test; Blob lifecycle policies for archival of old imagery |
| NFR-9 | **Extensibility** | Architecture must support adding new imagery providers, new input formats (e.g., GeoJSON, Shapefile), and new downstream consumers without significant refactoring |

---

## 7. Solution Architecture

### 7.1 High-Level Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Upload Sources                               │
│   OneDrive / SharePoint ──► Power Automate ──► Azure Blob (input)    │
│                              or direct upload ──► Azure Blob (input) │
└──────────────────────┬───────────────────────────────────────────────┘
                       │  Blob Created Event
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Azure Event Grid                                  │
│   Filters: suffix = .kml, container = kml-input                      │
└──────────────────────┬───────────────────────────────────────────────┘
                       │  Trigger
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│              Azure Durable Functions (Python)                        │
│                                                                      │
│  ┌─────────────┐   ┌───────────────┐   ┌──────────────────────────┐  │
│  │ Orchestrator │──►│ Activity:     │──►│ Activity:               │  │
│  │              │   │ Parse KML     │   │ Prepare AOI             │  │
│  │              │   │ Extract Geom  │   │ Buffer BBox             │  │
│  │              │   │ Validate CRS  │   │ Compute Area/Centroid   │  │
│  └──────┬───── │   └───────────────┘   └──────────┬───────────────┘  │
│         │      │                                   │                 │
│         │      │   ┌───────────────────────────┐   │                 │
│         │      └──►│ Activity:                 │◄──┘                 │
│         │          │ Query Imagery Provider    │                     │
│         │          │ (Provider Adapter Layer)  │                     │
│         │          │ Poll Status               │                     │
│         │          │ Download Imagery          │                     │
│         │          └──────────┬────────────────┘                     │
│         │                     │                                      │
│         │          ┌──────────▼────────────────┐                     │
│         └─────────►│ Activity:                 │                     │
│                    │ Clip / Reproject          │                     │
│                    │ Store Imagery             │                     │
│                    │ Write Metadata JSON       │                     │
│                    └───────────────────────────┘                     │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Azure Blob Storage (output)                       │
│                                                                      │
│   /kml/               ← original KML files                           │
│   /imagery/raw/       ← full-extent GeoTIFF                          │
│   /imagery/clipped/   ← AOI-clipped GeoTIFF                          │
│   /metadata/          ← per-AOI JSON records                         │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Azure Monitor / Application Insights  │  Azure Key Vault            │
│  (logging, metrics, alerts)            │  (API keys, secrets)        │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.2 Orchestration Pattern

The workflow uses the **Durable Functions Fan-Out / Fan-In** pattern:

1. **Trigger Function** — Event Grid subscription fires on blob creation in `kml-input` container.
2. **Orchestrator Function** — Reads KML blob, invokes activity functions, manages state.
3. **Activity: Parse KML** — Extracts features and geometry.
4. **Fan-Out per Polygon** — For multi-feature KMLs, the orchestrator fans out to process each polygon concurrently.
5. **Activity: Prepare AOI** — Buffers bounding box, computes area/centroid, formats provider query.
6. **Activity: Acquire Imagery** — Calls provider adapter, polls, downloads.
7. **Activity: Post-Process** — Clips, reprojects, stores imagery and metadata.
8. **Fan-In** — Orchestrator collects results, writes summary log.

### 7.3 Provider Adapter Layer

```text
                    ┌──────────────────────────┐
                    │  ImageryProvider          │  (Abstract Base Class)
                    │  ──────────────────────── │
                    │  + search(aoi) -> list    │
                    │  + order(scene_id) -> id  │
                    │  + poll(order_id) -> bool │
                    │  + download(order) -> path│
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼───────────────────┐
              │                                      │
    ┌─────────▼──────────────┐          ┌────────────▼──────────┐
    │ PlanetaryComputerAdapter│          │ SkyWatchAdapter       │
    │ (STAC API — free)      │          │ (EarthCache — paid)   │
    │ Dev/Test environment   │          │ Production            │
    └────────────────────────┘          └───────────────────────┘
```

The active provider is selected via configuration (environment variable / App Configuration), enabling zero-code-change provider switching. Development and testing use the **Microsoft Planetary Computer** adapter (free STAC API, Sentinel-2 at 10 m / NAIP at ~60 cm), while production uses the **SkyWatch EarthCache** adapter (aggregated commercial imagery at ≤ 50 cm).

### 7.4 Engineering Philosophy & Design Principles

> *"There was no second chance. We all knew that."*
> — **Margaret Hamilton**, Director of Apollo Flight Computer Programming, MIT Instrumentation Laboratory

This system processes geospatial data that feeds directly into agricultural decision-making. A silently corrupt polygon, a swallowed exception, or an unvalidated assumption about input format can cascade into wasted imagery spend, incorrect field boundaries, or missed orchards — with no human in the loop to catch it. The engineering approach for this project therefore draws directly from the principles Margaret Hamilton established during the Apollo programme: **build software that is correct by construction, not by coincidence**.

#### 7.4.1 Zero-Assumption Input Handling

Every byte that enters the system — KML content, API responses, configuration values, blob metadata — is treated as **untrusted until validated**. The code must never assume:

- That a KML file is well-formed XML
- That coordinates are in the expected CRS or within valid ranges
- That a polygon has the minimum required vertices, is closed, or is non-self-intersecting
- That an imagery provider API returns the documented schema
- That a downloaded file is a valid GeoTIFF (or even non-empty)
- That environment variables or Key Vault secrets exist and are non-blank

**Implementation mandate:** Every function that accepts external data must begin with explicit validation. Invalid input must produce a clear, actionable error — never a `NoneType has no attribute` three stack frames later.

#### 7.4.2 Fail Loudly, Fail Safely

Hamilton's Apollo software was engineered to **detect its own errors and recover without human intervention**. When Apollo 11's computer was overloaded during descent, it did not crash — it shed lower-priority work and kept flying. This system follows the same principle:

- **No bare `except:` clauses.** Every exception handler must name the specific exception type and log the full context (correlation ID, input parameters, stack trace).
- **No silent failures.** If a polygon cannot be processed, the system must write a failure record to metadata, move the file to a failed queue, and emit a structured log entry — not simply skip it.
- **Graceful degradation.** If clipping fails, store the unclipped image and flag it. If one polygon in a multi-feature KML fails, process the remaining polygons and report partial success. Never let one bad feature take down the entire batch.
- **Dead-letter everything.** After max retries, unprocessable items are persisted to a dead-letter path with full diagnostic context so a human can investigate without guesswork.

#### 7.4.3 Defensive Geometry Processing

Geospatial data is notoriously messy. The system must handle real-world KML files, not textbook examples:

- **Validate before compute.** Every polygon is checked with `shapely.is_valid` before any operation. Invalid geometries are repaired with `make_valid()` where possible, rejected with a diagnostic message where not.
- **Guard against degenerate cases.** Zero-area polygons, duplicate vertices, unclosed rings, polygons with fewer than 3 distinct points — all must be detected and handled explicitly.
- **Coordinate sanity checks.** Latitude must be in [-90, 90], longitude in [-180, 180]. Coordinates outside these bounds indicate a CRS problem, not a valid location.
- **Area reasonableness checks.** A 500,000-hectare "orchard" is almost certainly a data error. Configurable upper bounds with automatic flagging.
- **Buffer arithmetic.** Buffering in degrees is meaningless for metric distances. All buffer operations must project to a local metric CRS, apply the buffer, then project back.

#### 7.4.4 Idempotent and Deterministic Processing

The same KML file uploaded twice must produce the same outputs, and must not corrupt or duplicate existing records:

- **Processing IDs.** Every orchestration run is keyed by a unique ID derived from the input blob path and upload timestamp.
- **Idempotent writes.** Blob storage writes use deterministic paths. Re-running a failed pipeline produces the same output paths, overwriting partial results rather than creating duplicates.
- **No hidden state.** Functions are stateless. All state lives in the Durable Functions orchestration store or in Blob Storage. There is nothing to "get out of sync."

#### 7.4.5 Explicit Over Implicit

- **No magic strings.** Blob paths, container names, provider identifiers, and configuration keys are defined as constants or enums — never as inline string literals scattered across the codebase.
- **No implicit type conversions.** Coordinate arrays, areas, and resolutions carry explicit units. A function that expects hectares must not silently receive square metres.
- **No default-to-happy-path.** If a configuration value is missing, the system raises an error at startup — not minutes later when the value is first accessed mid-processing.
- **Type hints everywhere.** Every function signature carries full type annotations. `Any` is not an acceptable return type.

#### 7.4.6 Observability as a First-Class Concern

If you cannot see what the system is doing, you cannot trust what it has done:

- **Structured logging from day one.** Not an afterthought. Every log entry includes: correlation ID, processing stage, input identifiers, elapsed time, and outcome.
- **Metrics that matter.** Processing duration per stage, imagery file sizes, API response times, retry counts, success/failure ratios — all emitted as custom Application Insights metrics.
- **Audit trail.** The metadata JSON for each AOI is a complete, self-contained record of what happened: what was requested, what was received, how it was processed, and how long it took. This is the system's flight recorder.

#### 7.4.7 Test Pyramid and Verification Strategy

Hamilton's team at MIT built verification into every layer. This project follows the same discipline:

| Layer | What is tested | Approach |
| --- | --- | --- |
| **Unit** | KML parsing, geometry validation, buffer logic, metadata schema, path generation | `pytest` with parametrised test cases covering valid, invalid, and edge-case inputs |
| **Integration** | Blob trigger → Function invocation, Key Vault secret retrieval, provider adapter HTTP interactions | Azure Functions local runtime + `responses`/`httpx_mock` for provider API stubbing |
| **Contract** | Provider adapter interface compliance | Abstract base class enforcement + adapter-specific test suites |
| **End-to-End** | Full pipeline: upload KML → imagery stored + metadata written | Automated test using real Azure resources in a staging environment |
| **Chaos / Fault** | Transient API failures, timeout scenarios, malformed responses | Injected faults via test doubles; verify retry and dead-letter behaviour |

No code is merged without passing the relevant test tier. Test coverage is a project metric, not a suggestion.

#### 7.4.8 Summary: The Hamilton Standard

| Principle | In Practice |
| --- | --- |
| **Assume nothing** | Validate all inputs at system boundaries; reject or repair before processing |
| **Fail visibly** | Every failure produces a log entry, a metadata record, and (if terminal) a dead-letter artefact |
| **Recover automatically** | Retry transient errors with backoff; degrade gracefully on partial failures |
| **Be deterministic** | Same input always produces same output; idempotent writes; no hidden state |
| **Be explicit** | Type hints, named constants, explicit units, no silent defaults |
| **Be observable** | Structured logs, custom metrics, audit-trail metadata on every processed AOI |
| **Verify relentlessly** | Unit, integration, contract, E2E, and fault-injection tests — all automated |

This is not aspirational. These principles are **mandatory engineering standards** for this project. Every pull request, every code review, and every design decision is evaluated against them. We are building software that must work correctly without a human watching — exactly the kind of software Margaret Hamilton's team built to land on the Moon.

### 7.5 Compute Model Decision Record

Three compute approaches were evaluated for this workload. The decision is recorded here for traceability.

#### Options Evaluated

| Option | Compute Layer | Orchestration | GDAL Strategy |
| --- | --- | --- | --- |
| **A: Pure Serverless** | Azure Functions Flex Consumption (custom Docker) | Durable Functions (fan-out/fan-in, timers, retry) | Pre-installed in custom container image |
| **B: Pure Containers** | Azure Container Apps Jobs (KEDA-scaled) | Queue-based state machine (manual fan-out via messages) | Standard Docker image — full control |
| **C: Hybrid** | Functions for orchestration + Container Apps Jobs for GDAL compute | Durable Functions (lightweight) + ACA Jobs (heavy compute) | Isolated in container layer only |

#### Workload Analysis

The decision hinges on understanding where time and resources are actually spent:

| Task | Nature | Typical Duration | Memory |
| --- | --- | --- | --- |
| KML parsing | CPU-light (XML parsing) | Milliseconds | < 50 MB |
| Geometry validation + AOI prep | CPU-light (Shapely) | Milliseconds | < 100 MB |
| Imagery API search + order | I/O-bound (HTTP) | Seconds | < 50 MB |
| Imagery API polling (waiting) | **Idle waiting** | Minutes to hours | **$0 with Durable timers** |
| GeoTIFF download | I/O-bound (HTTP) | Seconds–minutes | 10–200 MB (stream to blob) |
| GDAL clipping/reprojection | CPU-burst (C extension) | 2–10 seconds | 200 MB–1 GB |

Key insight: **95%+ of wall-clock time is spent waiting on imagery provider APIs.** Durable Functions timers cost nothing during this wait. The actual compute-heavy work (GDAL clipping) is short-burst and well within the 4 GB / 10-minute activity limits.

#### Typical Raster Sizes for Agricultural AOIs

| AOI Size | Image Dimensions (50 cm/px) | GeoTIFF (4-band, compressed) |
| --- | --- | --- |
| 5 ha (small orchard) | ~450 × 450 px | 2–5 MB |
| 50 ha (large orchard) | ~1,400 × 1,400 px | 10–25 MB |
| 500 ha (plantation) | ~4,500 × 4,500 px | 80–150 MB |
| 10,000 ha (PID upper bound) | ~14,000 × 14,000 px | 500 MB–1.2 GB |

The vast majority of real orchard/field polygons produce GeoTIFFs in the **10–150 MB range** — comfortably within Azure Functions resource limits.

#### Decision: Option A — Pure Serverless (Azure Functions Flex Consumption)

**Rationale:**

1. **Durable Functions solves the two hardest architectural problems for free** — fan-out/fan-in and async polling with zero-cost timers. Building equivalent orchestration on Container Apps requires ~200–400 lines of custom plumbing.
2. **No raster will realistically stress the 4 GB memory limit.** Common case is 10–50 MB; extreme edge case (10,000 ha) peaks at ~1 GB.
3. **GDAL operations complete in seconds**, well within the 10-minute activity timeout.
4. **Cheapest at low-to-moderate volume.** Pay per execution. During imagery API wait times (the majority of wall-clock time), cost is $0.
5. **Least infrastructure to manage.** One Function App, one storage account for orchestration state. No container orchestration, ingress controllers, or service mesh.

**Migration path:** If future requirements exceed Functions limits (very large rasters >2 GB, CV/ML workloads), the GDAL-heavy activity functions can be extracted to Container Apps Jobs without rewriting the Durable Functions orchestration layer — effectively upgrading from Option A to Option C.

#### Python 3.12 Decision

Python 3.12 was selected over 3.13/3.14 for the following reasons:

| Factor | Python 3.12 | Python 3.14 (free-threaded) |
| --- | --- | --- |
| Azure Functions Flex Consumption | Full GA support | Unverified — likely preview |
| GDAL/rasterio/shapely wheels | All stable | Uncertain (C extensions need no-GIL compilation) |
| Durable Functions SDK | Tested | Untested |
| Concurrency benefit for this project | Baseline (all parallelism is I/O-bound or multi-process) | **None** — GIL is already released during I/O and C extension calls |

Free threading (PEP 703) removes the GIL for CPU-bound thread parallelism within a single process. This project's concurrency is either I/O-bound (async HTTP, Durable timers) or multi-process (Durable Functions activity fan-out), neither of which benefits from GIL removal.

### 7.6 Imagery Provider Strategy

#### Two-Adapter Approach

The project implements two provider adapters behind the `ImageryProvider` abstract base class:

| Adapter | Provider | Resolution | Cost | Use Case |
| --- | --- | --- | --- | --- |
| `PlanetaryComputerAdapter` | Microsoft Planetary Computer | 10 m (Sentinel-2), ~60 cm (NAIP, US-only) | **Free** (public STAC API, no auth required) | Development, testing, CI/CD pipelines |
| `SkyWatchAdapter` | SkyWatch EarthCache | ≤ 50 cm (aggregated: Maxar, Planet, Airbus) | Per-km², per-order | Production |

#### Why Planetary Computer for Dev/Test?

1. **Zero imagery cost** during Phases 1–3 of development.
2. **Standard STAC protocol** — well-documented, stable, industry-standard.
3. **Hosted on Azure** — data egress from Planetary Computer to Azure Blob Storage is fast and free (same network).
4. **Real satellite data** (Sentinel-2, Landsat, NAIP) — lower resolution than production, but the pipeline code is identical: a GeoTIFF is a GeoTIFF.
5. **Proves the adapter pattern** by having two real implementations from day one.

#### Why SkyWatch for Production?

1. **Aggregator** — one API covers multiple underlying providers (Maxar, Planet, Airbus), reducing integration effort.
2. **Simple REST workflow** — search → order → poll → download.
3. **Meets the ≤ 50 cm resolution target** via aggregated commercial imagery.
4. **Not a permanent lock-in** — the adapter pattern means adding a direct Maxar or Planet adapter is a config change + new adapter class.

---

## 8. Technology Stack

| Layer | Technology | Justification |
| --- | --- | --- |
| **Runtime** | Python 3.12 | Rich geospatial library ecosystem; stable GDAL/rasterio/shapely wheels; full Azure Functions support |
| **Serverless Compute** | Azure Functions v4 (Flex Consumption, custom Docker) | Event-driven, scales to zero, native Blob/Event Grid bindings; custom container for GDAL dependencies |
| **Orchestration** | Azure Durable Functions (Python v2 model) | Built-in fan-out/fan-in, async polling with timers (zero cost while waiting), retries, state management |
| **Event Routing** | Azure Event Grid | Reliable, filterable event delivery for blob-created events |
| **Storage** | Azure Blob Storage (General Purpose v2, Hot tier) | Scalable object storage; lifecycle management for tiering |
| **Secrets** | Azure Key Vault | Centralised, auditable secret management; Managed Identity access |
| **Monitoring** | Azure Monitor + Application Insights | Structured logging, live metrics, alerting |
| **Configuration** | Azure App Configuration (optional) | Centralised, feature-flag-capable configuration |
| **Identity** | Azure Managed Identity (System-Assigned) | Passwordless access to Blob Storage, Key Vault, App Configuration |
| **IaC** | Bicep | Repeatable, version-controlled infrastructure deployment; type-safe, less verbose than raw ARM |
| **CI/CD** | GitHub Actions | Automated build, test, deploy; native integration with project repository |
| **KML Parsing** | `fiona` (primary, OGR driver), `lxml` (fallback) | Fiona returns Shapely-compatible geometries directly; lxml handles edge cases (nested Folders, SchemaData) where OGR's KML driver has gaps |
| **Geometry** | `shapely`, `pyproj` | Geometry operations (buffer, centroid, area, validation, CRS transforms) |
| **Raster** | `rasterio`, `GDAL` | GeoTIFF read/write, clipping, reprojection |
| **STAC Client** | `pystac-client` | Programmatic search of STAC catalogues (Microsoft Planetary Computer) |
| **Imagery Provider** | Microsoft Planetary Computer (dev/test), SkyWatch EarthCache (production) | Free STAC API for development; aggregated commercial imagery for production |
| **Linting & Formatting** | `ruff` | Replaces flake8 + black + isort; 100x faster; single tool |
| **Type Checking** | `pyright` (via Pylance) | Static type analysis; catches bugs before runtime |
| **Testing** | `pytest` | Standard Python test framework; parametrised tests, fixtures, plugins |

---

## 9. Data Flow

### 9.1 End-to-End Sequence

```text
User uploads .kml
        │
        ▼
[1] Blob Storage (kml-input container) receives file
        │
        ▼
[2] Event Grid emits BlobCreated event
        │
        ▼
[3] Trigger Function spins up Orchestrator instance
        │
        ▼
[4] Orchestrator calls Parse KML activity
        │   ├── Reads blob content
        │   ├── Validates XML schema
        │   ├── Extracts features (1..N polygons)
        │   ├── Validates CRS (WGS 84)
        │   └── Returns list of Feature objects
        │
        ▼
[5] Orchestrator fans-out: for each Feature
        │
        ├──► [5a] Prepare AOI activity
        │         ├── Compute bounding box
        │         ├── Apply buffer (configurable)
        │         ├── Compute area (ha), centroid
        │         └── Return AOI query object
        │
        ├──► [5b] Acquire Imagery activity
        │         ├── Select provider adapter (from config)
        │         ├── Search archive (AOI, resolution, cloud cover)
        │         ├── Select best scene
        │         ├── Submit order / download request
        │         ├── Poll until ready (Durable timer)
        │         ├── Download imagery
        │         └── Return local blob reference
        │
        └──► [5c] Post-Process activity
                  ├── Reproject if needed
                  ├── Clip to polygon (if enabled)
                  ├── Store raw GeoTIFF → /imagery/raw/
                  ├── Store clipped GeoTIFF → /imagery/clipped/
                  ├── Build metadata JSON
                  └── Store metadata → /metadata/
        │
        ▼
[6] Orchestrator writes summary; archives KML → /kml/
        │
        ▼
[7] Logs written to Application Insights
```

### 9.2 Metadata JSON Schema (per AOI)

```json
{
  "$schema": "aoi-metadata-v1",
  "processing_id": "uuid",
  "kml_filename": "orchard_alpha.kml",
  "feature_name": "Block A",
  "orchard_name": "Alpha Orchard",
  "tree_variety": "Fuji Apple",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[lon, lat], ...]],
    "centroid": [lon, lat],
    "bounding_box": [min_lon, min_lat, max_lon, max_lat],
    "buffered_bounding_box": [min_lon, min_lat, max_lon, max_lat],
    "area_hectares": 12.45,
    "crs": "EPSG:4326"
  },
  "imagery": {
    "provider": "maxar",
    "scene_id": "WV03_20260110_...",
    "acquisition_date": "2026-01-10T10:23:00Z",
    "spatial_resolution_m": 0.31,
    "crs": "EPSG:32637",
    "cloud_cover_pct": 5.2,
    "off_nadir_angle_deg": 12.3,
    "format": "GeoTIFF",
    "raw_blob_path": "/imagery/raw/2026/01/alpha-orchard/block-a.tif",
    "clipped_blob_path": "/imagery/clipped/2026/01/alpha-orchard/block-a.tif"
  },
  "processing": {
    "buffer_m": 100,
    "clipped": true,
    "reprojected": false,
    "timestamp": "2026-02-15T14:30:00Z",
    "duration_s": 142,
    "status": "success",
    "errors": []
  }
}
```

---

## 10. Storage Strategy

### 10.1 Container & Path Layout

```text
Storage Account: stkmlsatellite
│
├── Container: kml-input          (Event Grid source)
│   └── {filename}.kml
│
└── Container: kml-output         (processed outputs)
    ├── kml/
    │   └── {YYYY}/{MM}/{orchard-name}/{filename}.kml
    │
    ├── imagery/
    │   ├── raw/
    │   │   └── {YYYY}/{MM}/{orchard-name}/{feature-name}.tif
    │   └── clipped/
    │       └── {YYYY}/{MM}/{orchard-name}/{feature-name}.tif
    │
    └── metadata/
        └── {YYYY}/{MM}/{orchard-name}/{feature-name}.json
```

### 10.2 Lifecycle Policies

| Rule | Condition | Action |
| --- | --- | --- |
| Archive old raw imagery | Blob age > 180 days | Move to Cool tier |
| Archive old raw imagery | Blob age > 365 days | Move to Archive tier |
| Delete processing logs | Blob age > 730 days | Delete |
| Retain metadata | Indefinite | No action (metadata is small) |

---

## 11. Security & Credential Management

| Concern | Control |
| --- | --- |
| **Imagery API Keys** | Stored in Azure Key Vault; accessed via Managed Identity at runtime |
| **Blob Storage Access** | System-Assigned Managed Identity with Storage Blob Data Contributor role; no connection strings in code |
| **Network** | Private endpoints for Blob Storage and Key Vault (recommended for production) |
| **Data Encryption** | Azure Storage Service Encryption (SSE) at rest; TLS 1.2+ in transit |
| **RBAC** | Least-privilege Azure RBAC for all service principals and developers |
| **Secret Rotation** | Key Vault secret versioning; application reads latest version on each invocation |
| **Code Secrets** | Pre-commit hooks / CI scanning to prevent accidental credential commits |

---

## 12. Logging, Monitoring & Error Handling

### 12.1 Logging Strategy

| Level | Content | Destination |
| --- | --- | --- |
| **INFO** | Processing step start/complete, AOI metadata, imagery query parameters | Application Insights (traces) |
| **WARNING** | High cloud cover, no archive match, slow provider response | Application Insights (traces) |
| **ERROR** | Parse failures, API errors, download failures, timeout | Application Insights (exceptions) |
| **METRIC** | Processing duration, imagery file size, AOI area, success/failure count | Application Insights (custom metrics) |

All log entries carry a **correlation ID** (the Durable Functions instance ID) for end-to-end traceability.

### 12.2 Error Handling

| Scenario | Handling |
| --- | --- |
| Malformed KML | Log error, move file to `/kml/failed/`, skip processing |
| CRS unsupported | Attempt reprojection; if impossible, flag and skip |
| Imagery provider API error (transient) | Retry with exponential backoff (base 5 s, max 3 retries) |
| Imagery provider API error (permanent — 4xx) | Log, flag AOI as `imagery_unavailable`, continue with remaining AOIs |
| No archive imagery available | Flag AOI as `no_coverage`, write metadata JSON with status |
| Download timeout | Retry up to 3 times; on final failure, dead-letter the AOI for manual review |
| Concurrent upload conflict | Durable Functions instance isolation — each KML gets its own orchestration instance |

### 12.3 Alerts

| Alert | Condition | Channel |
| --- | --- | --- |
| Pipeline failure rate | > 20 % failures in 1-hour window | Email / Teams webhook |
| Processing stall | No successful completion in 6 hours (when uploads exist) | Email / Teams webhook |
| Key Vault access denied | Any 403 from Key Vault | Email (immediate) |

---

## 13. Assumptions

| # | Assumption |
| --- | --- |
| A-1 | Uploaded KML files conform to the OGC KML 2.2 or 2.3 specification. |
| A-2 | All geometries are in WGS 84 (EPSG:4326) unless explicitly specified otherwise. |
| A-3 | An imagery provider API with adequate archive coverage for the regions of interest is available and licenced. |
| A-4 | The project team has an active Azure subscription with permissions to create Function Apps, Storage Accounts, Key Vaults, and Event Grid subscriptions. |
| A-5 | Imagery provider delivers data in a georeferenced raster format (e.g., GeoTIFF). |
| A-6 | Individual polygon AOIs will not exceed 10,000 hectares. |
| A-7 | Internet egress from Azure Functions to external imagery provider APIs is permitted by network policy. |

---

## 14. Constraints

| # | Constraint |
| --- | --- |
| C-1 | **Platform**: All services must run on Microsoft Azure. |
| C-2 | **Language**: Python 3.12 is the implementation language (see Section 7.5 for version decision rationale). |
| C-3 | **Budget**: Azure consumption must stay within an approved monthly spend (to be defined). |
| C-4 | **Imagery Cost**: Satellite imagery API costs are subject to provider pricing; budget approval required before production activation. |
| C-5 | **No CV/ML**: This phase must not include any computer vision, machine learning, or tree-detection components. |
| C-6 | **Data Residency**: If applicable, imagery and metadata must be stored in a specific Azure region (to be confirmed). |

---

## 15. Dependencies

| # | Dependency | Type | Owner |
| --- | --- | --- | --- |
| D-1 | Azure subscription with adequate quotas | Infrastructure | Project Sponsor / IT |
| D-2 | SkyWatch EarthCache API account and credentials (production) | External Service | Project Manager |
| D-3 | Sample KML files for testing (various geometries) — **✅ 17 test files created** | Test Data | Domain Expert |
| D-4 | Network connectivity from Azure to imagery provider endpoints | Infrastructure | IT / Network Team |
| D-5 | Approval for SkyWatch imagery usage costs (production only; dev/test uses free Planetary Computer) | Commercial | Project Sponsor |
| D-6 | GitHub repository for CI/CD — **✅ created** (`Hardcoreprawn/azure-workflow-for-kml-satellite`) | Tooling | DevOps Team |

---

## 16. Risks & Mitigations

| # | Risk | Probability | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| R-1 | Imagery provider API changes or is discontinued | Low | High | Provider-agnostic adapter layer; implement ≥ 1 backup adapter |
| R-2 | Insufficient archive coverage for target AOIs | Medium | High | Allow manual override to request tasking (future phase); surface no-coverage flag clearly |
| R-3 | Large KML files cause Function timeout | Low | Medium | Use Durable Functions with checkpointed activities; increase timeout limits |
| R-4 | High cloud cover renders imagery unusable | Medium | Medium | Configurable cloud cover threshold; retry with different date range; flag for user review |
| R-5 | Azure service outage (regional) | Low | High | Deploy to paired region with geo-redundant storage (GRS) for critical data |
| R-6 | Imagery costs exceed budget | Medium | High | Implement per-AOI cost estimation before ordering; configurable spend cap; alert on threshold |
| R-7 | KML files with degenerate geometry (self-intersections, zero-area polygons) | Medium | Low | Validate geometry with Shapely `is_valid`; attempt `make_valid()`; reject if unfixable |
| R-8 | Concurrent processing causes storage naming conflicts | Low | Medium | Include unique processing ID and timestamp in all output paths |

---

## 17. Out of Scope

The following items are **explicitly excluded** from this phase and are candidates for future project phases:

1. **Tree Detection & Counting** — Computer vision / ML-based analysis of imagery
2. **Vegetation Indices** — NDVI, NDRE, EVI calculations
3. **Change Detection** — Temporal comparison of imagery
4. **User Portal / Dashboard** — Web-based UI for upload, status tracking, results viewing
5. **Satellite Tasking** — Requesting new satellite captures (only archive retrieval in scope)
6. **Multi-spectral Band Analysis** — Processing beyond RGB + NIR
7. **Report Generation** — PDF or formatted reports from processed data
8. **Mobile Application** — Field data collection or result viewing on mobile devices
9. **Integration with Farm Management Systems** — ERP or agronomic software integration

---

## 18. Project Phases & Milestones

### Phase 1: Foundation & KML Ingestion (Weeks 1–3)

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-1.1 | Azure infrastructure provisioned (IaC templates) | Week 1 |
| M-1.2 | Blob trigger + Event Grid subscription operational | Week 1 |
| M-1.3 | KML parsing function: single polygon | Week 2 |
| M-1.4 | KML parsing function: multipolygon + multi-feature | Week 2 |
| M-1.5 | AOI processing: bounding box, buffer, area, centroid | Week 3 |
| M-1.6 | Metadata JSON generation and storage | Week 3 |

### Phase 2: Imagery Retrieval (Weeks 4–6)

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-2.1 | Provider adapter interface defined and documented | Week 4 |
| M-2.2 | First provider adapter implemented (search + order + download) | Week 5 |
| M-2.3 | Async polling with Durable Functions timer | Week 5 |
| M-2.4 | GeoTIFF download and storage in Blob | Week 6 |
| M-2.5 | Clipping and reprojection pipeline | Week 6 |

### Phase 3: Integration, Hardening & Testing (Weeks 7–9)

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-3.1 | End-to-end pipeline integration test (upload → imagery stored) | Week 7 |
| M-3.2 | Concurrent upload stress test (≥ 20 files) | Week 7 |
| M-3.3 | Error handling and retry logic verified | Week 8 |
| M-3.4 | Logging and alerting configured and validated | Week 8 |
| M-3.5 | Security review (Key Vault, Managed Identity, RBAC) | Week 8 |
| M-3.6 | Documentation: architecture, runbook, API reference | Week 9 |
| M-3.7 | UAT sign-off | Week 9 |

### Phase 4: Deployment & Handover (Week 10)

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-4.1 | CI/CD pipeline configured and tested | Week 10 |
| M-4.2 | Production deployment | Week 10 |
| M-4.3 | Operational handover and knowledge transfer | Week 10 |

---

## 19. Estimated Effort & Resource Plan

### 19.1 Team Roles

| Role | Responsibility | Estimated Allocation |
| --- | --- | --- |
| **Cloud/Backend Developer** | Azure Functions, Durable Functions, KML parsing, imagery integration | 1 FTE, 10 weeks |
| **Geospatial Engineer** | Geometry processing, raster operations, CRS handling | 0.5 FTE, 6 weeks |
| **DevOps Engineer** | IaC, CI/CD, monitoring, security configuration | 0.25 FTE, 4 weeks |
| **Project Manager** | Coordination, vendor liaison, acceptance | 0.25 FTE, 10 weeks |
| **Domain Expert (Agriculture)** | KML sample provision, validation, UAT | 0.1 FTE, 3 weeks |

### 19.2 Estimated Azure Costs (Monthly, Production Steady-State)

| Service | Estimate | Notes |
| --- | --- | --- |
| Azure Functions (Flex Consumption) | $15–50 | Highly variable by volume; includes ~$30/mo for 1–2 always-ready instances if cold starts are problematic |
| Azure Blob Storage (Hot, 500 GB) | $10–20 | Imagery is the primary cost driver |
| Azure Event Grid | < $1 | Low event volume |
| Azure Key Vault | < $1 | Low transaction volume |
| Application Insights | $5–15 | Dependent on log volume |
| **Subtotal (Azure infra)** | **~$35–90/month** | Excludes imagery API costs |
| Imagery — Dev/Test (Planetary Computer) | **$0** | Free STAC API; Sentinel-2 (10 m) and NAIP (~60 cm, US-only) |
| Imagery — Production (SkyWatch EarthCache) | **Variable** | Depends on per-km² pricing, AOI size, and order frequency |

> **Note:** Imagery API costs are provider-dependent and may significantly exceed infrastructure costs. A cost estimation step should be built into the pipeline before production ordering.

---

## 20. Acceptance Criteria

The project will be considered complete when the following criteria are met:

| # | Criterion | Verification Method |
| --- | --- | --- |
| AC-1 | A `.kml` file uploaded to the monitored container triggers processing within 60 seconds | Manual upload + log inspection |
| AC-2 | Single polygon, multipolygon, and multi-feature KML files are all parsed correctly | Test with ≥ 5 sample KML files of varying complexity |
| AC-3 | Bounding box, buffered bounding box, area (ha), and centroid are computed accurately (±1 % vs. reference) | Compare output metadata with independently computed values |
| AC-4 | Satellite imagery at the configured resolution target is retrieved and stored as GeoTIFF | Visual inspection of output imagery + metadata JSON review |
| AC-5 | Imagery is clipped to AOI polygon (when clipping is enabled) | Visual inspection / GIS tool overlay |
| AC-6 | Metadata JSON is produced for every processed AOI and conforms to the defined schema | Automated schema validation |
| AC-7 | Output files are stored in the correct Blob path hierarchy | Blob listing inspection |
| AC-8 | All processing steps are logged with correlation IDs in Application Insights | Log query in Application Insights |
| AC-9 | Failed processing (e.g., malformed KML, no imagery) is logged, flagged, and does not crash the pipeline | Inject malformed KML + unavailable AOI; verify graceful handling |
| AC-10 | ≥ 20 concurrent KML uploads are processed without errors or conflicts | Concurrent upload test |
| AC-11 | All secrets are retrieved from Key Vault; no credentials in code or environment variables | Code review + Key Vault audit log |
| AC-12 | Infrastructure is deployed via Bicep templates and is reproducible | Tear down and redeploy from templates |

---

## 21. Approval & Sign-Off

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| **Project Sponsor** | | | |
| **Technical Lead** | | | |
| **Project Manager** | | | |
| **Domain Expert** | | | |

---

### End of Document
