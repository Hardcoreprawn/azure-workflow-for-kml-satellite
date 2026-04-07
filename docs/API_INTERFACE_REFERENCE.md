# API and Interface Reference

Issue: #18

## Public HTTP Endpoints

### Quick Verification Reference

Function App base URL (dev): `https://func-kmlsat-dev.jollysea-48e72cf8.uksouth.azurecontainerapps.io`

| Method | Path | Auth | Expected (unauthed) | Purpose |
| --- | --- | --- | --- | --- |
| GET | /api/health | anonymous | 200 JSON | Liveness probe |
| GET | /api/readiness | anonymous | 200 JSON | Dependency readiness probe |
| GET | /api/contract | anonymous | 200 JSON | OpenAPI/contract metadata |
| GET | /api/catalogue | bearer token | 401 | User analysis catalogue |
| POST | /api/analysis/submit | bearer token | 401 | KML upload + pipeline start |
| POST | /api/frame-analysis | anonymous | — | Single-frame analysis |
| POST | /api/timelapse-analysis | bearer token | 401 | Timelapse analysis |
| POST | /api/eudr-assessment | bearer token | 401 | EUDR compliance assessment |
| GET | /api/monitoring | bearer token | 401 | AOI monitoring |
| GET | /api/billing/status | bearer token | 401 | Billing status |
| POST | /api/billing/checkout | bearer token | 401 | Stripe checkout |
| POST | /api/billing/portal | anonymous | — | Stripe portal redirect |
| POST | /api/billing/webhook | anonymous | — | Stripe webhook |
| GET | /api/demo-artifacts | anonymous | 400 (no params) | Demo artifact listing |
| GET | /api/proxy | anonymous | — | Tile proxy |
| POST | /api/contact-form | anonymous | — | Contact form |
| GET | /api/orchestrator/{id} | anonymous | 200/404 | Durable diagnostics |
| GET | /api/analysis/history | bearer token | 401 | Analysis history |
| POST | /api/convert-coordinates | bearer token | 401 | Coordinate conversion |
| GET | /api/export/{id}/{fmt} | bearer token | 401 | Export artifacts |

## Trigger and Orchestrator Entry Points

- Event Grid trigger: kml_blob_trigger
- Main orchestrator: kml_processing_orchestrator
- Polling sub-orchestrator: poll_order_suborchestrator

## Activity Functions and Contracts

Durable activity payload contracts are defined in kml_satellite/models/payloads.py.

| Activity | Input Contract | Output Contract |
| --- | --- | --- |
| parse_kml | ParseKmlInput | list[FeatureDict] |
| prepare_aoi | FeatureDict | AOIDict |
| write_metadata | WriteMetadataInput | WriteMetadataOutput |
| acquire_imagery | AcquireImageryInput | AcquireImageryOutput |
| poll_order | PollOrderInput | PollOrderOutput |
| download_imagery | DownloadImageryInput | DownloadImageryOutput |
| post_process_imagery | PostProcessImageryInput | PostProcessImageryOutput |

## ImageryProvider Contract

Base interface: kml_satellite/providers/base.py

Required methods:

- search(aoi, filters) -> list[SearchResult]
- order(scene_id) -> OrderId
- poll(order_id) -> OrderStatus
- download(order_id) -> BlobReference

Failure model:

- ProviderError (base)
- ProviderAuthError
- ProviderSearchError
- ProviderOrderError
- ProviderDownloadError

## Metadata JSON Schema

Canonical model: kml_satellite/models/metadata.py

Formal schema file:

- docs/schemas/aoi-metadata-v2.schema.json

## Blob Path Conventions

Path builders: kml_satellite/utils/blob_paths.py

- kml/YYYY/MM/{project}/{filename}.kml
- metadata/YYYY/MM/{project}/{feature}.json
- imagery/raw/YYYY/MM/{project}/{feature}.tif
- imagery/clipped/YYYY/MM/{project}/{feature}.tif

All path segments are lowercased, slug-sanitized, and deterministic for idempotent writes.
