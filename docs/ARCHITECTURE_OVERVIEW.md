# Architecture Overview

Issue: #18

## Deployed Components

The production pipeline is deployed as Azure Functions on Container Apps with event-driven orchestration.

- Event Grid topic: evgt-<baseName>
- Event Grid subscription: evgs-kml-upload
- Function App: func-<baseName>
- Resource group: rg-<baseName>
- Input container: kml-input
- Output container: kml-output
- Durable task hub: KmlSatelliteHub

For dev this commonly resolves to:

- Function App: func-kmlsat-dev
- Resource group: rg-kmlsat-dev

## Data Flow

1. User uploads KML into input blob container.
2. Event Grid emits a BlobCreated event.
3. kml_blob_trigger validates event payload and starts kml_processing_orchestrator.
4. Orchestrator runs phase pipeline:
   - parse_kml
   - prepare_aoi + write_metadata
   - acquire_imagery + poll_order_suborchestrator + download_imagery + post_process_imagery
5. Metadata and imagery artifacts are written to output blob paths.
6. Operational diagnostics are available at /api/orchestrator/{instance_id}.

## Provider Adapter Boundary

The orchestrator calls provider adapters only through the ImageryProvider contract in kml_satellite/providers/base.py.

Required adapter methods:

- search(aoi, filters) -> list[SearchResult]
- order(scene_id) -> OrderId
- poll(order_id) -> OrderStatus
- download(order_id) -> BlobReference

This allows provider-specific logic to evolve without changing orchestration flow.

## Configuration Reference (Environment)

Core runtime settings:

- DEFAULT_INPUT_CONTAINER or KML_INPUT_CONTAINER
- DEFAULT_OUTPUT_CONTAINER or KML_OUTPUT_CONTAINER
- IMAGERY_PROVIDER
- IMAGERY_RESOLUTION_TARGET_M
- IMAGERY_MAX_CLOUD_COVER_PCT
- AOI_BUFFER_M
- AOI_MAX_AREA_HA
- KEYVAULT_URL
- AzureWebJobsStorage
- APPLICATIONINSIGHTS_CONNECTION_STRING

Validation and defaults are implemented in kml_satellite/core/config.py.

## Observability Surface

HTTP diagnostics:

- GET /api/health
- GET /api/readiness
- GET /api/orchestrator/{instance_id}

Structured logs include correlation and entity fields such as:

- instance, correlation_id
- blob, feature
- order_id, provider

## Deployment Model

Infrastructure is managed with OpenTofu under infra/tofu.

Deployment sequencing must ensure host readiness before Event Grid subscription enablement, to avoid webhook validation race conditions.
