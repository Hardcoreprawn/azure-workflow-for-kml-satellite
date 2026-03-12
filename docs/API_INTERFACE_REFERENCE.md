# API and Interface Reference

Issue: #18

## Public HTTP Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /api/health | Liveness probe |
| GET | /api/readiness | Dependency readiness probe |
| GET | /api/orchestrator/{instance_id} | Durable diagnostics payload |
| POST | /api/marketing-interest | Contact form ingestion endpoint |

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
