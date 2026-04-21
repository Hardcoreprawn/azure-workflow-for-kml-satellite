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
| GET | /api/catalogue | SWA session | 401 | User analysis catalogue |
| POST | /api/analysis/submit | SWA session | 401 | KML upload + pipeline start |
| POST | /api/frame-analysis | anonymous | — | Single-frame analysis |
| POST | /api/timelapse-analysis | SWA session | 401 | Timelapse analysis |
| POST | /api/eudr-assessment | SWA session | 401 | EUDR compliance assessment |
| GET | /api/monitoring | SWA session | 401 | AOI monitoring |
| GET | /api/billing/status | SWA session | 401 | Billing status |
| POST | /api/billing/checkout | SWA session | 401 | Stripe checkout |
| POST | /api/billing/portal | anonymous | — | Stripe portal redirect |
| POST | /api/billing/webhook | anonymous | — | Stripe webhook |
| GET | /api/demo-artifacts | anonymous | 400 (no params) | Demo artifact listing |
| GET | /api/proxy | anonymous | — | Tile proxy |
| POST | /api/contact-form | anonymous | — | Contact form |
| GET | /api/orchestrator/{id} | anonymous | 200/404 | Durable diagnostics |
| GET | /api/analysis/history | SWA session | 401 | Analysis history (`scope=user` default, `scope=org` for portfolio summary) |
| POST | /api/convert-coordinates | SWA session | 401 | Coordinate conversion |
| GET | /api/export/{id}/{fmt} | SWA session | 401 | Export artifacts |

## Trigger and Orchestrator Entry Points

- Event Grid trigger: `blob_trigger` (blueprints/pipeline/blob_trigger.py)
- Main orchestrator: `treesight_orchestrator` (blueprints/pipeline/orchestrator.py)

## Activity Functions and Contracts

Durable activity functions are defined in blueprints/pipeline/activities.py.

| Activity | Input Contract | Output Contract |
| --- | --- | --- |
| parse_kml | ParseKmlInput | list[FeatureDict] |
| load_offloaded_features | OffloadRef | list[FeatureDict] |
| prepare_aoi | FeatureDict | AOIDict |
| store_aoi_claims | ClaimInput | list[ClaimRef] |
| load_aoi_claim | ClaimRef | AOIDict |
| acquire_imagery | AcquireImageryInput | AcquireImageryOutput |
| acquire_composite | CompositeInput | list[AcquireImageryOutput] |
| poll_order | PollOrderInput | PollOrderOutput |
| download_imagery | DownloadImageryInput | DownloadImageryOutput |
| post_process_imagery | PostProcessImageryInput | PostProcessImageryOutput |
| run_enrichment | EnrichmentInput | EnrichmentOutput |
| submit_batch_fulfilment | BatchInput | BatchOutput |
| poll_batch_fulfilment | BatchPollInput | BatchPollOutput |
| release_quota | QuotaInput | QuotaOutput |
| write_metadata | WriteMetadataInput | WriteMetadataOutput |

## ImageryProvider Contract

Base interface: treesight/providers/base.py

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

Canonical model: treesight/models/aoi.py

Formal schema file:

- docs/schemas/aoi-metadata-v2.schema.json

## Blob Path Conventions

Path builders: treesight/storage/client.py

- kml/YYYY/MM/{project}/{filename}.kml
- metadata/YYYY/MM/{project}/{feature}.json
- imagery/raw/YYYY/MM/{project}/{feature}.tif
- imagery/clipped/YYYY/MM/{project}/{feature}.tif

All path segments are lowercased, slug-sanitized, and deterministic for idempotent writes.
