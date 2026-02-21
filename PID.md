# Project Initiation Document (PID)

## TreeSight — Multi-Tenant SaaS Platform for KML-Based Satellite Imagery Acquisition, Analysis, and Monitoring

| Field | Detail |
| --- | --- |
| **Document Version** | 2.0 |
| **Date** | 21 February 2026 |
| **Status** | Draft |
| **Classification** | Internal |

> **Version 2.0 Note:** This revision reframes the project from a single-user
> processing pipeline to a multi-tenant SaaS platform. The core imagery
> acquisition engine (v1.x) is retained and becomes the processing backbone.
> New sections cover multi-tenancy, API layer, temporal image cataloguing,
> analytical pipelines (vegetation indices, tree detection, change detection),
> annotation, and reporting.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Business Case & Justification](#2-business-case--justification)
3. [Project Objectives](#3-project-objectives)
4. [Scope](#4-scope)
5. [Functional Requirements](#5-functional-requirements)
    - [FR-1–6: Processing Engine (v1)](#fr-1-kml-ingestion-pipeline)
    - [FR-7: Multi-Tenancy & Data Isolation](#fr-7-multi-tenancy--data-isolation)
    - [FR-8: API & Authentication](#fr-8-api--authentication)
    - [FR-9: Temporal Image Catalogue](#fr-9-temporal-image-catalogue)
    - [FR-10: Vegetation Indices & Canopy Analysis](#fr-10-vegetation-indices--canopy-analysis)
    - [FR-11: Tree Detection & Counting](#fr-11-tree-detection--counting)
    - [FR-12: Temporal Analysis & Change Detection](#fr-12-temporal-analysis--change-detection)
    - [FR-13: Annotation & Labelling](#fr-13-annotation--labelling)
    - [FR-14: Reporting & Export](#fr-14-reporting--export)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Solution Architecture](#7-solution-architecture)
    - [7.4 Engineering Philosophy & Design Principles](#74-engineering-philosophy--design-principles)
    - [7.5 Compute Model Decision Record](#75-compute-model-decision-record)
    - [7.6 Imagery Provider Strategy](#76-imagery-provider-strategy)
    - [7.7 Multi-Tenant Data Architecture](#77-multi-tenant-data-architecture)
    - [7.8 Analytical Pipeline Architecture](#78-analytical-pipeline-architecture)
    - [7.9 Temporal Catalogue Data Model](#79-temporal-catalogue-data-model)
    - [7.10 Subscription Tiers](#710-subscription-tiers)
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

TreeSight is a **multi-tenant SaaS platform** hosted on Microsoft Azure that enables any user — farmers, foresters, conservation researchers, estate managers — to upload KML boundary files, automatically acquire satellite imagery for those areas, and unlock a growing suite of analytical capabilities: vegetation health indices, tree detection and counting, season-over-season change monitoring, and collaborative annotation.

The platform comprises three layers:

1. **Processing Engine** (v1 — implemented) — An automated, cloud-native pipeline that ingests KML files, extracts polygon geometry, acquires high-resolution satellite imagery via pluggable provider adapters, and stores analysis-ready GeoTIFF imagery with structured metadata in Azure Blob Storage.
2. **Multi-Tenant Service Layer** (v2 — this phase) — Tenant isolation with container-per-tenant storage, authenticated API, SAS-scoped uploads/downloads, usage metering, and subscription tiers.
3. **Analytical Platform** (v2+ — phased) — Temporal image cataloguing, vegetation indices (NDVI), ML-based tree detection and counting, temporal change detection, user annotation, and reporting.

The system is designed to serve diverse land-management use cases: precision agriculture (orchards, vineyards, plantations), forestry inventory, rainforest monitoring, conservation surveys, and urban canopy assessment. Data isolation ensures each tenant's boundaries, imagery, annotations, and analytical results are completely separated.

---

## 2. Business Case & Justification

| Driver | Description |
| --- | --- |
| **Operational Efficiency** | Eliminates manual steps of uploading KML files, querying imagery providers, downloading imagery, and organising outputs. |
| **Scalability** | Supports concurrent processing of many KML uploads with no per-file manual intervention. |
| **Reproducibility** | Every AOI is processed through an identical, auditable pipeline with full metadata lineage. |
| **Multi-User Value** | Any user can define their boundaries and monitor their land — orchards, woodlands, rainforest, gardens — without geospatial expertise. |
| **Temporal Intelligence** | Repeated imagery acquisition over the same AOIs builds a spatial time series, enabling season-to-season and year-to-year comparisons that reveal trends invisible in single snapshots. |
| **Analytical Upsell** | Free tier (imagery acquisition only) drives adoption; paid tiers unlock tree counting, change detection, health reports — classic SaaS value ladder. |
| **Data Flywheel** | User annotations ("this is a diseased tree", "this area was cleared") become training data for ML models, improving analytical accuracy for all tenants. |
| **Time-to-Insight** | Reduces the turnaround from field-boundary definition to imagery and analytics from days/weeks (manual) to minutes/hours (automated). |

---

## 3. Project Objectives

### 3.1 Processing Engine (v1 — implemented)

| # | Objective | Measurable Outcome | Status |
| --- | --- | --- | --- |
| O-1 | Automated KML detection and ingestion | Pipeline triggers within 60 seconds of a new KML upload | ✅ Done |
| O-2 | Polygon geometry extraction from KML | Correct extraction of single polygon, multipolygon, and multi-feature files with validation | ✅ Done |
| O-3 | AOI preparation and metadata generation | Buffered bounding box, centroid, area (ha), and CRS metadata produced for every polygon | ✅ Done |
| O-4 | High-resolution satellite imagery acquisition | Imagery at ≤ 50 cm/pixel retrieved and stored for each AOI (configurable resolution target) | ✅ Done |
| O-5 | Structured cloud storage | All outputs stored in Azure Blob with a well-defined folder hierarchy and companion metadata JSON | ✅ Done |
| O-6 | Provider-agnostic imagery architecture | Imagery retrieval layer abstracted behind an interface, allowing future provider substitution without pipeline changes | ✅ Done |
| O-7 | Robust error handling and logging | All processing steps logged; failures flagged; automatic retry mechanism in place | ✅ Done |

### 3.2 Multi-Tenant SaaS (v2)

| # | Objective | Measurable Outcome |
| --- | --- | --- |
| O-8 | Multi-tenant data isolation | Each tenant's KML, imagery, metadata, and analytics stored in dedicated containers; no cross-tenant data leakage |
| O-9 | Authenticated API layer | Users authenticate via Entra External ID; all operations authorised per-tenant |
| O-10 | Self-service onboarding | New tenants can sign up, upload KML, and receive imagery without manual provisioning |
| O-11 | Usage metering and subscription tiers | Per-tenant usage tracked (AOI count, imagery volume, API calls); free and paid tiers enforced |

### 3.3 Analytical Platform (v2+)

| # | Objective | Measurable Outcome |
| --- | --- | --- |
| O-12 | Temporal image catalogue | Every AOI accumulates a time-indexed series of imagery snapshots, queryable by date range |
| O-13 | Vegetation health indices | Automated NDVI / canopy cover computation for every acquired image with multispectral bands |
| O-14 | Tree detection and counting | ML-based individual tree detection with per-AOI tree counts accurate to ±10 % (F1 ≥ 0.85) |
| O-15 | Change detection and trend analysis | Season-over-season and year-over-year comparison reports showing canopy gain/loss, health trends, and anomalies |
| O-16 | User annotation | Users can annotate imagery (mark trees, disease zones, boundaries); annotations feed ML training |
| O-17 | Reporting and export | Per-AOI reports (health summary, tree inventory, change timeline) exportable as PDF, CSV, GeoJSON |

---

## 4. Scope

### 4.1 In Scope

#### Processing Engine (v1 — implemented)

- Monitoring a designated upload location (Azure Blob Storage container) for new `.kml` files
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

#### Multi-Tenant Service Layer (v2)

- Tenant provisioning with container-per-tenant storage isolation
- User authentication and authorisation via Entra External ID
- Authenticated REST API for upload, status, download, and management operations
- SAS-token-scoped blob access (upload and download) per tenant
- Usage metering and per-tenant quotas
- Subscription tier enforcement (free / pro / enterprise)
- Tenant administration (manage AOIs, view job history, configure providers)

#### Analytical Platform (v2+, phased delivery)

- **Temporal Image Catalogue** — each AOI accumulates a time-indexed series of imagery snapshots with queryable history
- **Vegetation Indices** — automated NDVI and canopy cover percentage computation for images with Red + NIR bands
- **Tree Detection & Counting** — ML-based individual tree detection, crown delineation, and per-AOI tree inventory
- **Health Classification** — per-tree or per-zone healthy / stressed / dead classification from multispectral imagery
- **Change Detection** — side-by-side and difference-map comparison between any two acquisition dates for the same AOI
- **Temporal Trend Analysis** — season-over-season and year-over-year health curves, canopy area trends, and anomaly detection (sudden loss events)
- **User Annotation** — point, polygon, and label annotations tied to specific imagery dates; annotations exportable and usable as ML training data
- **Reporting & Export** — per-AOI health reports, tree inventories, change timelines; export as PDF, CSV, GeoJSON
- **Web Frontend** — upload KMLs, view imagery, browse temporal catalogue, annotate, view reports

### 4.2 Out of Scope

| Item | Rationale |
| --- | --- |
| Satellite tasking (new capture requests) | Only archive/existing imagery retrieval is in scope |
| On-premises deployment | Azure-only deployment |
| Mobile native application | Web-responsive frontend covers mobile access; native app is a future consideration |
| Direct integration with farm management / ERP systems | API provides data; integrations are consumer responsibility |
| Real-time streaming imagery | Batch acquisition model; real-time is a different architecture |
| Multi-cloud deployment | Azure-only; cloud abstraction adds complexity without current benefit |

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

### FR-7: Multi-Tenancy & Data Isolation

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-7.1 | Provision a dedicated Blob Storage container pair (`{tenant}-input`, `{tenant}-output`) for each tenant on signup | Must |
| FR-7.2 | Thread `tenant_id` through all pipeline stages (blob event → orchestrator → activities → output paths) | Must |
| FR-7.3 | Ensure no pipeline code path can read or write outside the active tenant's containers | Must |
| FR-7.4 | Mint short-lived, container-scoped SAS tokens for tenant upload and download operations | Must |
| FR-7.5 | Support promotion of high-value tenants to dedicated storage accounts without pipeline code changes | Should |
| FR-7.6 | Enforce per-tenant quotas: max AOIs, max imagery volume (GB), max concurrent pipelines | Must |
| FR-7.7 | Record tenant creation, deletion, and quota changes in an audit log | Should |

### FR-8: API & Authentication

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-8.1 | Authenticate users via Entra External ID (email + social login) | Must |
| FR-8.2 | Expose REST API endpoints: upload KML, list jobs, get job status, download results, list AOIs | Must |
| FR-8.3 | Map authenticated user → tenant; authorise all operations against tenant context | Must |
| FR-8.4 | API returns scoped SAS upload URLs so clients PUT blobs directly to storage (no API proxy for large files) | Must |
| FR-8.5 | API returns scoped SAS download URLs for imagery and metadata retrieval | Must |
| FR-8.6 | Rate-limit API calls per tenant (configurable per tier) | Should |
| FR-8.7 | Expose OpenAPI / Swagger documentation for the API | Should |

### FR-9: Temporal Image Catalogue

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-9.1 | Maintain a catalogue record for every imagery acquisition: AOI ID, acquisition date, provider, resolution, cloud cover, blob paths, index values | Must |
| FR-9.2 | Support querying a tenant's catalogue by AOI, date range, provider, and resolution | Must |
| FR-9.3 | Enable scheduled re-acquisition: tenant configures an AOI for periodic imagery refresh (e.g., monthly, quarterly) | Should |
| FR-9.4 | Link each catalogue entry to derived products (NDVI raster, annotations, reports) | Must |
| FR-9.5 | Store catalogue in Cosmos DB (NoSQL) with partition key = `tenant_id` | Must |

### FR-10: Vegetation Indices & Canopy Analysis

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-10.1 | Compute NDVI (Normalized Difference Vegetation Index) for any image with Red and NIR bands | Must |
| FR-10.2 | Compute canopy cover percentage per AOI polygon (NDVI threshold-based) | Must |
| FR-10.3 | Generate NDVI heatmap raster (GeoTIFF) and store alongside source imagery | Must |
| FR-10.4 | Compute zonal statistics per AOI: mean NDVI, std dev, min, max, % above/below threshold | Should |
| FR-10.5 | Support additional indices (NDRE, EVI, SAVI) when band data is available | Could |

### FR-11: Tree Detection & Counting

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-11.1 | Detect individual trees from high-resolution imagery (≤ 50 cm) using an object detection / instance segmentation model | Must |
| FR-11.2 | Output per-AOI tree count and a GeoJSON layer of tree locations (point) and crown polygons | Must |
| FR-11.3 | Classify detected trees by health status (healthy / stressed / dead) using spectral signature | Should |
| FR-11.4 | Support user-provided training annotations to fine-tune models per tenant or crop type | Should |
| FR-11.5 | Report model confidence per detection; allow confidence threshold configuration | Must |
| FR-11.6 | Track tree counts over time per AOI to show planting, growth, and loss trends | Should |

### FR-12: Temporal Analysis & Change Detection

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-12.1 | Generate side-by-side comparison view of any two acquisition dates for the same AOI | Must |
| FR-12.2 | Compute NDVI difference map between two dates, highlighting areas of gain, loss, and no-change | Must |
| FR-12.3 | Detect anomalous canopy loss events (magnitude exceeding configurable threshold) and flag for user review | Should |
| FR-12.4 | Generate NDVI / canopy cover time-series charts per AOI spanning all available acquisition dates | Must |
| FR-12.5 | Support seasonal aggregation (spring, summer, autumn, winter) for trend normalisation | Should |
| FR-12.6 | Year-over-year comparison: same-season imagery from different years, highlighting multi-year trends | Should |

### FR-13: Annotation & Labelling

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-13.1 | Users can place point annotations (e.g., mark individual trees, damage locations) on imagery | Must |
| FR-13.2 | Users can draw polygon annotations (e.g., delineate disease zones, new plantings, cleared areas) | Must |
| FR-13.3 | Each annotation is tied to a specific AOI and acquisition date | Must |
| FR-13.4 | Annotations carry user-defined labels and free-text notes | Must |
| FR-13.5 | Annotations are stored per-tenant and are never visible to other tenants | Must |
| FR-13.6 | Annotations exportable as GeoJSON for use in external GIS tools | Should |
| FR-13.7 | Tenant can opt-in to contribute anonymised annotations to a shared training pool for ML model improvement | Could |

### FR-14: Reporting & Export

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-14.1 | Generate per-AOI health summary report (current NDVI, canopy cover, tree count, latest imagery thumbnail) | Must |
| FR-14.2 | Generate change report for any two dates (before/after thumbnails, NDVI difference, area statistics) | Must |
| FR-14.3 | Generate tree inventory report (total count, health breakdown, locations GeoJSON) | Must |
| FR-14.4 | Generate temporal trend report (time-series charts, seasonal summaries, year-over-year comparison) | Should |
| FR-14.5 | Export reports as PDF | Must |
| FR-14.6 | Export analytical data as CSV and GeoJSON | Must |
| FR-14.7 | API endpoint to programmatically retrieve reports and export data | Should |

---

## 6. Non-Functional Requirements

| ID | Category | Requirement |
| --- | --- | --- |
| NFR-1 | **Performance** | End-to-end processing (KML upload → imagery stored) must complete within 30 minutes for a single AOI, excluding imagery provider fulfilment time |
| NFR-2 | **Scalability** | Must process at least 20 concurrent KML uploads (each containing up to 10 polygons) without degradation; support 1000+ tenants on shared infrastructure |
| NFR-3 | **Availability** | Target 99.5 % uptime for the API layer and ingestion trigger (aligned with Azure Functions / Container Apps SLA) |
| NFR-4 | **Reliability** | No data loss — every uploaded KML must be processed or explicitly flagged as failed |
| NFR-5 | **Security** | All secrets stored in Azure Key Vault; Blob Storage accessed via Managed Identity; tenant data isolated at container level; SAS tokens scoped per-tenant; no credentials in code |
| NFR-6 | **Maintainability** | Modular codebase with clear separation: ingestion, AOI processing, imagery retrieval (adapter pattern), storage, orchestration, API, analytics |
| NFR-7 | **Observability** | Structured logging with correlation IDs; per-tenant dashboards for processing throughput and error rates |
| NFR-8 | **Cost Efficiency** | Flex Consumption Azure Function plan to minimise idle costs; free imagery (Planetary Computer) for dev/test and free tier tenants; Blob lifecycle policies for archival |
| NFR-9 | **Extensibility** | Architecture must support adding new imagery providers, new input formats (e.g., GeoJSON, Shapefile), new analytical modules, and new downstream consumers without significant refactoring |
| NFR-10 | **Tenant Isolation** | A bug, misconfiguration, or privilege escalation must never allow one tenant to access another tenant's data, imagery, annotations, or analytical results |
| NFR-11 | **API Latency** | API response time ≤ 200 ms p95 for metadata queries; upload/download SAS URL generation ≤ 100 ms |
| NFR-12 | **ML Inference** | Tree detection inference must complete within 60 seconds per image; batch processing of temporal catalogue must not block the imagery acquisition pipeline |

---

## 7. Solution Architecture

### 7.1 High-Level Architecture

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                         Web Frontend                                     │
│   Upload KML  ·  View imagery  ·  Annotate  ·  Reports  ·  Dashboard    │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │  HTTPS
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    API Layer (Container App / Functions HTTP)             │
│   Auth (Entra External ID)  ·  Tenant resolution  ·  SAS token minting  │
│   Upload/download URLs  ·  Job status  ·  Catalogue queries  ·  Reports  │
└─────┬─────────────┬──────────────┬───────────────┬───────────────────────┘
      │             │              │               │
      ▼             ▼              ▼               ▼
┌───────────┐ ┌───────────┐ ┌──────────────┐ ┌─────────────────────────┐
│ Entra     │ │ Cosmos DB │ │ Blob Storage │ │ Processing Engine       │
│ External  │ │           │ │ (per-tenant  │ │ (Durable Functions)     │
│ ID        │ │ Tenants   │ │  containers) │ │                         │
│           │ │ Catalogue │ │              │ │ Ingestion → Acquisition │
│ Users     │ │ Jobs      │ │ KML / TIFF / │ │ → Fulfillment           │
│ Tenants   │ │ Usage     │ │ Metadata /   │ │                         │
│           │ │ Annot'ns  │ │ NDVI / Rpts  │ │ Fan-out / Fan-in        │
└───────────┘ └───────────┘ └──────────────┘ │ Parallel batches        │
                                              └────────────┬────────────┘
                                                           │
                                              ┌────────────▼────────────┐
                                              │ Analytical Pipeline     │
                                              │                         │
                                              │ NDVI / Canopy Cover     │
                                              │ Tree Detection (ML)     │
                                              │ Change Detection        │
                                              │ Report Generation       │
                                              └─────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Azure Monitor / App Insights  │  Azure Key Vault  │  Stripe (billing)  │
│  (logging, metrics, alerts)    │  (API keys)       │  (subscriptions)   │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.1.1 Processing Engine Architecture (v1 — implemented)

```text
┌──────────────────────────────────────────────────────────────────────┐
│   Tenant blob upload (via SAS URL)  ──► {tenant}-input container     │
└──────────────────────┬───────────────────────────────────────────────┘
                       │  Blob Created Event
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Azure Event Grid                                  │
│   Filters: suffix = .kml, container pattern = *-input                │
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
│         │          │ Poll Status (parallel)    │                     │
│         │          │ Download Imagery (batched)│                     │
│         │          └──────────┬────────────────┘                     │
│         │                     │                                      │
│         │          ┌──────────▼────────────────┐                     │
│         └─────────►│ Activity:                 │                     │
│                    │ Clip / Reproject (batched)│                     │
│                    │ Store Imagery             │                     │
│                    │ Write Metadata JSON       │                     │
│                    │ Update Temporal Catalogue  │                     │
│                    └───────────────────────────┘                     │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│           Azure Blob Storage ({tenant}-output container)             │
│                                                                      │
│   /kml/               ← original KML files                           │
│   /imagery/raw/       ← full-extent GeoTIFF                          │
│   /imagery/clipped/   ← AOI-clipped GeoTIFF                          │
│   /imagery/ndvi/      ← NDVI heatmap raster                          │
│   /metadata/          ← per-AOI JSON records                         │
│   /reports/           ← generated PDF / CSV reports                   │
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

### 7.7 Multi-Tenant Data Architecture

#### Tenant Isolation Model: Container-per-Tenant

Each tenant receives a dedicated pair of Blob Storage containers on a shared storage account:

```text
Storage Account: sttreesight
│
├── Container: {tenant_id}-input     (Event Grid source — KML uploads)
├── Container: {tenant_id}-output    (processed outputs, imagery, reports)
│
├── Container: acme-farms-input
├── Container: acme-farms-output
│   ├── kml/...
│   ├── imagery/raw/...
│   ├── imagery/clipped/...
│   ├── imagery/ndvi/...
│   ├── metadata/...
│   ├── annotations/...
│   └── reports/...
│
├── Container: woodland-trust-input
├── Container: woodland-trust-output
│   └── ...
```

**Access control:**

- API layer mints SAS tokens scoped to the authenticated tenant's containers only
- Pipeline validates `tenant_id` against the triggering container at entry point
- No code path accepts a bare container name from user input — always derived from authenticated tenant context
- High-value tenants can be promoted to a dedicated storage account without changing pipeline code (container interface is the same)

#### Tenant State (Cosmos DB)

```text
Cosmos DB Account: cosmos-treesight
│
├── Database: treesight
│   ├── Container: tenants          (partition key: /tenant_id)
│   │   └── { tenant_id, name, email, tier, created_at, quota, ... }
│   │
│   ├── Container: catalogue        (partition key: /tenant_id)
│   │   └── { tenant_id, aoi_id, acquisition_date, provider, resolution,
│   │         cloud_cover, blob_paths, ndvi_stats, tree_count, ... }
│   │
│   ├── Container: jobs             (partition key: /tenant_id)
│   │   └── { tenant_id, job_id, status, kml_filename, started, completed, ... }
│   │
│   ├── Container: annotations      (partition key: /tenant_id)
│   │   └── { tenant_id, aoi_id, acquisition_date, annotation_type,
│   │         geometry, label, notes, created_by, created_at, ... }
│   │
│   └── Container: usage            (partition key: /tenant_id)
│       └── { tenant_id, month, aoi_count, imagery_gb, api_calls, ... }
```

### 7.8 Analytical Pipeline Architecture

The analytical pipeline runs **asynchronously after imagery acquisition**, triggered by new catalogue entries. It is decomposed into independent, composable stages so that each can be delivered incrementally and run on different compute tiers.

```text
                    Imagery Acquired
                    (catalogue entry written)
                           │
              ┌────────────┼────────────────┐
              │            │                │
              ▼            ▼                ▼
        ┌──────────┐ ┌──────────┐    ┌──────────────┐
        │ NDVI /   │ │ Tree     │    │ Change       │
        │ Canopy   │ │ Detection│    │ Detection    │
        │ Index    │ │ (ML)     │    │ (temporal)   │
        │          │ │          │    │              │
        │ Activity │ │ Container│    │ Activity /   │
        │ Function │ │ App Job  │    │ Container    │
        └────┬─────┘ └────┬─────┘    └──────┬───────┘
             │            │                 │
             ▼            ▼                 ▼
        ┌─────────────────────────────────────────┐
        │  Update Catalogue  ·  Store Outputs     │
        │  NDVI raster, tree GeoJSON, diff maps   │
        │  → {tenant}-output container            │
        └─────────────────────┬───────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Report          │
                    │ Generation      │
                    │ (on-demand or   │
                    │  post-analysis) │
                    └─────────────────┘
```

**Compute placement:**

| Stage | Compute | Rationale |
| --- | --- | --- |
| NDVI / Canopy | Azure Functions activity | Lightweight raster arithmetic (numpy); completes in seconds |
| Tree Detection | Container Apps Job | GPU inference (PyTorch/ONNX); needs more memory and optional GPU; isolated from pipeline |
| Change Detection | Azure Functions activity or Container Apps Job | Depends on complexity; NDVI differencing is lightweight; multi-temporal alignment may need more resources |
| Report Generation | Azure Functions activity | Template rendering + chart generation; lightweight |

This follows the **Option C hybrid pattern** from Section 7.5's decision record — Functions for orchestration and lightweight compute, Container Apps Jobs for ML inference. The migration path we identified is now being used.

### 7.9 Temporal Catalogue Data Model

The temporal catalogue is the core data structure that unlocks all analytical value. Every imagery acquisition creates a catalogue entry; every analytical product links back to one.

```text
AOI (polygon)
  │
  ├── Acquisition 2026-01-15 (Sentinel-2, 10m)
  │     ├── Raw GeoTIFF
  │     ├── Clipped GeoTIFF
  │     ├── NDVI raster
  │     ├── NDVI stats: { mean: 0.72, canopy_cover: 85% }
  │     └── Annotations: [ { point: ..., label: "dead tree" }, ... ]
  │
  ├── Acquisition 2026-04-20 (Maxar, 0.3m)
  │     ├── Raw / Clipped GeoTIFF
  │     ├── NDVI raster
  │     ├── NDVI stats: { mean: 0.68, canopy_cover: 82% }
  │     ├── Tree detection: { count: 1,247, healthy: 1,180, stressed: 52, dead: 15 }
  │     └── Change vs 2026-01-15: { ndvi_delta: -0.04, canopy_loss_ha: 0.3 }
  │
  ├── Acquisition 2026-07-10 (Sentinel-2, 10m)
  │     ├── ...
  │     └── Change vs 2026-04-20: { ndvi_delta: +0.05, canopy_gain_ha: 0.1 }
  │
  └── Temporal Summary
        ├── NDVI trend chart (time series)
        ├── Canopy cover trend (%)
        ├── Tree count history: [_, 1247, _]  (only for hi-res acquisitions)
        └── Anomaly flags: [ "2026-04-20: canopy_loss > threshold" ]
```

### 7.10 Subscription Tiers

| Feature | **Free** | **Pro** | **Enterprise** |
| --- | --- | --- | --- |
| AOIs | 3 | 50 | Unlimited |
| Imagery provider | Sentinel-2 (free, 10 m) | Sentinel-2 + commercial (≤ 50 cm) | All providers + priority |
| Acquisitions / month | 5 | 100 | Unlimited |
| NDVI / canopy cover | ✅ | ✅ | ✅ |
| Tree detection | — | ✅ | ✅ |
| Change detection | Last 2 dates | Full history | Full history |
| Annotations | 50 / AOI | Unlimited | Unlimited |
| Reports (PDF) | — | ✅ | ✅ + white-label |
| API access | — | ✅ | ✅ + webhooks |
| Support | Community | Email | Dedicated |
| Storage | 1 GB | 50 GB | 500 GB + custom |

---

## 8. Technology Stack

| Layer | Technology | Justification |
| --- | --- | --- |
| **Runtime** | Python 3.12 | Rich geospatial library ecosystem; stable GDAL/rasterio/shapely wheels; full Azure Functions support |
| **Serverless Compute** | Azure Functions v4 (Flex Consumption, custom Docker) | Event-driven, scales to zero, native Blob/Event Grid bindings; custom container for GDAL dependencies |
| **Orchestration** | Azure Durable Functions (Python v2 model) | Built-in fan-out/fan-in, async polling with timers (zero cost while waiting), retries, state management |
| **API Layer** | Azure Container Apps (or Azure Functions HTTP) | Always-on API for tenant auth, SAS minting, catalogue queries; independent scaling from pipeline |
| **Authentication** | Entra External ID (Azure AD B2C successor) | Consumer-facing signup/login; email + social providers; standards-based (OIDC/OAuth2) |
| **Event Routing** | Azure Event Grid | Reliable, filterable event delivery for blob-created events |
| **Blob Storage** | Azure Blob Storage (General Purpose v2, Hot tier) | Scalable object storage; per-container RBAC; lifecycle management for tiering |
| **Document Database** | Azure Cosmos DB (NoSQL) | Tenant state, temporal catalogue, annotations, usage; partition key = tenant_id for isolation and scale |
| **Secrets** | Azure Key Vault | Centralised, auditable secret management; Managed Identity access |
| **Monitoring** | Azure Monitor + Application Insights | Structured logging, live metrics, alerting |
| **Configuration** | Azure App Configuration (optional) | Centralised, feature-flag-capable configuration |
| **Identity** | Azure Managed Identity (System-Assigned) | Passwordless access to Blob Storage, Key Vault, Cosmos DB, App Configuration |
| **ML Inference** | Azure Container Apps Jobs (GPU optional) | Tree detection model serving; isolated from pipeline; scales independently |
| **ML Framework** | PyTorch + ONNX Runtime | Tree detection (instance segmentation); ONNX for optimised inference |
| **Billing** | Stripe | Subscription management, usage-based billing; proven SaaS billing platform |
| **Frontend** | React / Next.js (or similar) | Map-based UI for upload, imagery viewing, annotation, reports |
| **Map Rendering** | MapLibre GL JS (or Leaflet) | Open-source map rendering for imagery overlay, annotation drawing, AOI display |
| **IaC** | Bicep | Repeatable, version-controlled infrastructure deployment; type-safe, less verbose than raw ARM |
| **CI/CD** | GitHub Actions | Automated build, test, deploy; native integration with project repository |
| **KML Parsing** | `fiona` (primary, OGR driver), `lxml` (fallback) | Fiona returns Shapely-compatible geometries directly; lxml handles edge cases (nested Folders, SchemaData) where OGR's KML driver has gaps |
| **Geometry** | `shapely`, `pyproj` | Geometry operations (buffer, centroid, area, validation, CRS transforms) |
| **Raster** | `rasterio`, `GDAL`, `numpy` | GeoTIFF read/write, clipping, reprojection, NDVI computation |
| **STAC Client** | `pystac-client` | Programmatic search of STAC catalogues (Microsoft Planetary Computer) |
| **Imagery Provider** | Microsoft Planetary Computer (dev/test/free tier), SkyWatch EarthCache (production/paid tiers) | Free STAC API for development and free-tier tenants; aggregated commercial imagery for paid tiers |
| **Linting & Formatting** | `ruff` | Replaces flake8 + black + isort; 100x faster; single tool |
| **Type Checking** | `pyright` (via Pylance) | Static type analysis; catches bugs before runtime |
| **Testing** | `pytest` | Standard Python test framework; parametrised tests, fixtures, plugins |

---

## 9. Data Flow

### 9.1 End-to-End Sequence (Processing Engine)

```text
User uploads .kml
        │
        ▼
[1] Blob Storage ({tenant_id}-input container) receives file
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
[6] Catalogue activity
        │   ├── Upsert acquisition record in Cosmos DB
        │   ├── Link AOI → snapshot (date, scene_id, blob paths)
        │   └── Increment tenant usage counters
        │
        ▼
[7] Orchestrator writes summary; archives KML → /kml/
        │
        ▼
[8] Logs written to Application Insights
```

### 9.2 Analytical Pipeline Sequence

The analytical pipeline runs after imagery acquisition, triggered either automatically (for subscribed AOIs) or on demand via the API.

```text
New acquisition catalogued
        │
        ▼
[A1] Vegetation Index activity
        │   ├── Load clipped GeoTIFF bands (Red, NIR, [Red Edge])
        │   ├── Compute NDVI raster  (NIR − Red) / (NIR + Red)
        │   ├── Compute canopy cover % (NDVI > threshold)
        │   ├── Store NDVI GeoTIFF → /ndvi/{date}/
        │   └── Store zonal statistics → Cosmos catalogue
        │
        ▼
[A2] Tree Detection activity  (Pro/Enterprise tiers)
        │   ├── Load clipped imagery (RGB or multispectral)
        │   ├── Run inference (ONNX model on Container Apps)
        │   ├── Output: bounding boxes + confidence scores
        │   ├── Count trees per polygon
        │   ├── Store detections GeoJSON → /detections/{date}/
        │   └── Store tree count → Cosmos catalogue
        │
        ▼
[A3] Change Detection activity  (requires ≥ 2 acquisitions)
        │   ├── Load NDVI rasters for date_T and date_T−1
        │   ├── Compute difference map (ΔNDVI)
        │   ├── Classify: gain / stable / loss / severe-loss
        │   ├── Compute tree count delta (if detections exist)
        │   ├── Flag anomalies (loss > configurable threshold)
        │   └── Store change report → /reports/{date_range}/
        │
        ▼
[A4] Results available via API / frontend
```

### 9.3 Metadata JSON Schema (per AOI)

```json
{
  "$schema": "aoi-metadata-v2",
  "processing_id": "uuid",
  "tenant_id": "tenant-abc123",
  "kml_filename": "orchard_alpha.kml",
  "feature_name": "Block A",
  "project_name": "Alpha Orchard",
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
    "provider": "planetary_computer",
    "scene_id": "S2A_20260110_...",
    "acquisition_date": "2026-01-10T10:23:00Z",
    "spatial_resolution_m": 10.0,
    "crs": "EPSG:32637",
    "cloud_cover_pct": 5.2,
    "format": "GeoTIFF",
    "raw_blob_path": "/imagery/raw/2026/01/alpha-orchard/block-a.tif",
    "clipped_blob_path": "/imagery/clipped/2026/01/alpha-orchard/block-a.tif"
  },
  "analysis": {
    "ndvi_blob_path": "/ndvi/2026/01/alpha-orchard/block-a.tif",
    "ndvi_mean": 0.72,
    "ndvi_min": 0.18,
    "ndvi_max": 0.89,
    "canopy_cover_pct": 68.4,
    "tree_count": 342,
    "detections_blob_path": "/detections/2026/01/alpha-orchard/block-a.geojson"
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
Storage Account: sttreesight
│
├── Container: {tenant_id}-input          (Event Grid source — per tenant)
│   └── {filename}.kml
│
└── Container: {tenant_id}-output         (processed outputs — per tenant)
    ├── kml/
    │   └── {YYYY}/{MM}/{project-name}/{filename}.kml
    │
    ├── imagery/
    │   ├── raw/
    │   │   └── {YYYY}/{MM}/{project-name}/{feature-name}.tif
    │   ├── clipped/
    │   │   └── {YYYY}/{MM}/{project-name}/{feature-name}.tif
    │   └── ndvi/
    │       └── {YYYY}/{MM}/{project-name}/{feature-name}_ndvi.tif
    │
    ├── metadata/
    │   └── {YYYY}/{MM}/{project-name}/{feature-name}.json
    │
    ├── detections/
    │   └── {YYYY}/{MM}/{project-name}/{feature-name}_trees.geojson
    │
    ├── annotations/
    │   └── {aoi_id}/{acquisition_date}.geojson
    │
    └── reports/
        └── {YYYY}/{MM}/{project-name}/{report-type}_{date}.pdf
```

> **Note:** `{project-name}` replaces the v1 `{orchard-name}` to reflect the broadened use case (woodland, rainforest, plantation, etc.).

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

The following items are **explicitly excluded** from this version and may be revisited in future:

1. **Satellite Tasking** — Requesting new satellite captures (only archive retrieval is in scope)
2. **Mobile Native Application** — Web-responsive frontend covers mobile access; dedicated native app is a future consideration
3. **Direct Farm Management / ERP Integration** — API provides data; specific integrations are consumer-driven
4. **Real-Time Streaming Imagery** — Batch acquisition model; real-time is a different architecture
5. **Multi-Cloud Deployment** — Azure-only; cloud abstraction adds complexity without current benefit
6. **Drone Imagery Ingestion** — Different data pipeline; potential future input source
7. **3D Canopy Modelling** — LiDAR/stereo-derived canopy height models are a separate workstream

---

## 18. Project Phases & Milestones

### Phase 1: Foundation & KML Ingestion — ✅ Complete

| Milestone | Deliverable | Status |
| --- | --- | --- |
| M-1.1 | Azure infrastructure provisioned (IaC templates) | ✅ |
| M-1.2 | Blob trigger + Event Grid subscription operational | ✅ |
| M-1.3 | KML parsing function: single polygon, multipolygon, multi-feature | ✅ |
| M-1.4 | AOI processing: bounding box, buffer, area, centroid | ✅ |
| M-1.5 | Metadata JSON generation and storage | ✅ |

### Phase 2: Imagery Retrieval — ✅ Complete

| Milestone | Deliverable | Status |
| --- | --- | --- |
| M-2.1 | Provider adapter interface (strategy pattern) | ✅ |
| M-2.2 | Planetary Computer + SkyWatch adapters | ✅ |
| M-2.3 | Async polling with Durable Functions timers | ✅ |
| M-2.4 | GeoTIFF download and storage | ✅ |
| M-2.5 | Clipping and reprojection pipeline | ✅ |

### Phase 3: Pipeline Hardening — ✅ Complete

| Milestone | Deliverable | Status |
| --- | --- | --- |
| M-3.1 | Defensive error handling and input validation | ✅ |
| M-3.2 | Parallel fan-out/fan-in (download, post-process, polling) | ✅ |
| M-3.3 | Orchestrator decomposition into bounded phases | ✅ |
| M-3.4 | 700+ unit tests, CI/CD, CodeQL security scanning | ✅ |

### Phase 4: Multi-Tenant Service Layer

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-4.1 | Tenant-aware blob event model and path builders | — |
| M-4.2 | Container-per-tenant provisioning (automated on signup) | — |
| M-4.3 | Entra External ID integration (signup, login, token validation) | — |
| M-4.4 | REST API: upload (SAS minting), status, download, list AOIs | — |
| M-4.5 | Cosmos DB: tenant, job, and usage stores | — |
| M-4.6 | Per-tenant quota enforcement and usage metering | — |
| M-4.7 | Subscription tier logic (free / pro / enterprise) | — |
| M-4.8 | Stripe billing integration | — |

### Phase 5: Temporal Catalogue & Vegetation Indices

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-5.1 | Temporal catalogue in Cosmos DB (acquisition history per AOI) | — |
| M-5.2 | Catalogue API: query by AOI, date range, provider | — |
| M-5.3 | NDVI computation activity (Red + NIR bands) | — |
| M-5.4 | Canopy cover percentage and zonal statistics | — |
| M-5.5 | NDVI heatmap raster storage and catalogue linkage | — |
| M-5.6 | Scheduled re-acquisition (configurable per AOI) | — |

### Phase 6: Tree Detection & Counting

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-6.1 | Tree detection model selection and benchmarking (DeepForest or custom) | — |
| M-6.2 | Container Apps Job for ML inference | — |
| M-6.3 | Tree detection output: per-AOI count + crown GeoJSON | — |
| M-6.4 | Health classification (healthy / stressed / dead) from spectral data | — |
| M-6.5 | Tree count temporal tracking (planting, growth, loss trends) | — |
| M-6.6 | User-provided annotation fine-tuning pipeline | — |

### Phase 7: Change Detection & Temporal Analysis

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-7.1 | NDVI difference map generation between any two dates | — |
| M-7.2 | Side-by-side imagery comparison view | — |
| M-7.3 | Temporal trend charts (NDVI / canopy cover over time) | — |
| M-7.4 | Anomaly detection (sudden canopy loss events) | — |
| M-7.5 | Season-over-season and year-over-year comparison engine | — |

### Phase 8: Annotation, Reporting & Frontend

| Milestone | Deliverable | Target |
| --- | --- | --- |
| M-8.1 | Web frontend: KML upload, imagery viewer, map-based AOI display | — |
| M-8.2 | Annotation tools: point/polygon markers, labels, notes on imagery | — |
| M-8.3 | Annotation storage (Cosmos DB, per-tenant, per-AOI, per-date) | — |
| M-8.4 | Per-AOI health summary report (NDVI, canopy, tree count) | — |
| M-8.5 | Change detection report (before/after, diff map, statistics) | — |
| M-8.6 | Tree inventory report (count, health breakdown, GeoJSON) | — |
| M-8.7 | PDF and CSV/GeoJSON export | — |
| M-8.8 | Annotation export and optional shared training pool opt-in | — |

---

## 19. Estimated Effort & Resource Plan

### 19.1 Team Roles

| Role | Responsibility | Estimated Allocation |
| --- | --- | --- |
| **Cloud/Backend Developer** | Azure Functions, Durable Functions, API layer, multi-tenancy, Cosmos DB, KML parsing, imagery integration | 1 FTE |
| **Frontend Developer** | Web UI, map rendering, annotation tools, reporting views | 0.5–1 FTE (Phase 8) |
| **ML / Geospatial Engineer** | Tree detection model, NDVI computation, change detection, raster operations, CRS handling | 0.5 FTE (Phases 5–7) |
| **DevOps Engineer** | IaC, CI/CD, monitoring, security configuration, Container Apps | 0.25 FTE |
| **Product / Domain Expert** | Use-case validation, annotation schema, report design, UAT | 0.1 FTE |

### 19.2 Estimated Azure Costs (Monthly, Production Steady-State)

| Service | Estimate | Notes |
| --- | --- | --- |
| Azure Functions (Flex Consumption) | $15–50 | Pipeline processing; variable by volume |
| Azure Container Apps (API layer) | $30–80 | 1–2 replicas, always-on; scales with API traffic |
| Azure Container Apps Jobs (ML inference) | $10–50 | Per-job billing; only runs when tree detection is triggered |
| Azure Blob Storage (Hot, per-tenant) | $10–100 | Scales with tenant count and imagery volume |
| Azure Cosmos DB (serverless) | $10–40 | Catalogue, tenants, annotations, usage; scaling with request units |
| Entra External ID | $0–50 | Free up to 50k MAU; then per-auth |
| Azure Event Grid | < $1 | Low event volume |
| Azure Key Vault | < $1 | Low transaction volume |
| Application Insights | $5–15 | Dependent on log volume |
| **Subtotal (Azure infra)** | **~$80–390/month** | Scales with tenant count; excludes imagery API costs |
| Imagery — Free tier (Planetary Computer) | **$0** | Sentinel-2 (10 m) and NAIP (~60 cm, US-only) |
| Imagery — Paid tiers (SkyWatch EarthCache) | **Variable** | Pass-through cost; per-km² pricing from provider |
| Stripe fees | 2.9 % + $0.30/txn | Standard SaaS billing |

> **Note:** Infrastructure costs scale roughly linearly with tenant count. At ~100 active tenants with moderate usage, expect $200–400/month Azure infra. Revenue from Pro/Enterprise subscriptions should exceed this well before that point.

---

## 20. Acceptance Criteria

### 20.1 Processing Engine (Phases 1–3 — complete)

| # | Criterion | Verification Method | Status |
| --- | --- | --- | --- |
| AC-1 | A `.kml` file uploaded to the monitored container triggers processing within 60 seconds | Manual upload + log inspection | ✅ |
| AC-2 | Single polygon, multipolygon, and multi-feature KML files are all parsed correctly | Test with ≥ 5 sample KML files of varying complexity | ✅ |
| AC-3 | Bounding box, buffered bounding box, area (ha), and centroid are computed accurately (±1 % vs. reference) | Compare output metadata with independently computed values | ✅ |
| AC-4 | Satellite imagery at the configured resolution target is retrieved and stored as GeoTIFF | Visual inspection of output imagery + metadata JSON review | ✅ |
| AC-5 | Imagery is clipped to AOI polygon (when clipping is enabled) | Visual inspection / GIS tool overlay | ✅ |
| AC-6 | Metadata JSON is produced for every processed AOI and conforms to the defined schema | Automated schema validation | ✅ |
| AC-7 | Output files are stored in the correct Blob path hierarchy | Blob listing inspection | ✅ |
| AC-8 | All processing steps are logged with correlation IDs in Application Insights | Log query in Application Insights | ✅ |
| AC-9 | Failed processing is logged, flagged, and does not crash the pipeline | Inject malformed KML + unavailable AOI; verify graceful handling | ✅ |
| AC-10 | ≥ 20 concurrent KML uploads are processed without errors or conflicts | Concurrent upload test | ✅ |
| AC-11 | All secrets are retrieved from Key Vault; no credentials in code | Code review + Key Vault audit log | ✅ |
| AC-12 | Infrastructure is deployed via Bicep templates and is reproducible | Tear down and redeploy from templates | ✅ |

### 20.2 Multi-Tenant Service Layer (Phase 4)

| # | Criterion | Verification Method |
| --- | --- | --- |
| AC-13 | New user can sign up, upload KML, and receive imagery with no manual provisioning | End-to-end signup flow test |
| AC-14 | Tenant A cannot access Tenant B's containers, imagery, metadata, or API resources | Penetration test with cross-tenant SAS tokens and API calls |
| AC-15 | API returns valid SAS upload/download URLs scoped to the authenticated tenant only | Automated API test suite |
| AC-16 | Usage metering accurately records AOI count, imagery volume, and API calls per tenant per month | Compare metering records with actual blob operations |
| AC-17 | Free-tier tenants are blocked from exceeding quota (AOIs, acquisitions, storage) | Quota enforcement test |

### 20.3 Analytical Platform (Phases 5–8)

| # | Criterion | Verification Method |
| --- | --- | --- |
| AC-18 | NDVI computed correctly for Sentinel-2 imagery (validated against reference tooling) | Compare with QGIS / rasterio manual computation (±0.01) |
| AC-19 | Tree detection model achieves F1 ≥ 0.85 on test imagery | Benchmarked against labelled validation dataset |
| AC-20 | Temporal catalogue accurately reflects all acquisitions per AOI with correct linkage to derived products | Query catalogue after multi-acquisition test |
| AC-21 | Change detection report correctly identifies canopy loss/gain between two dates | Visual inspection + zonal statistics validation |
| AC-22 | Annotations are persisted, tenant-isolated, and exportable as GeoJSON | Create annotations as Tenant A, verify invisible to Tenant B, export and validate |

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
