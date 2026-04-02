# ADR 0002: Bulk AOI Imaging Strategy (Issue #318)

## Status

Accepted

## Context

With fan-out/fan-in and claim check now in place (#316, PR #360), the system can handle 200+ AOIs without hitting the 48 KiB orchestrator history limit. The next question is how to handle imagery output when processing bulk workloads (50–200+ polygons from a single KMZ upload).

Two approaches were evaluated:

1. **Multiple individual images** — one cropped GeoTIFF per AOI per scene
2. **Single consolidated mosaic** — stitch all AOIs into one composite raster

### Current State

- Each AOI generates ~7 imagery orders in composite mode (1 NAIP detail + 6 Sentinel-2 temporal) → 200 AOIs = ~1,400 orders
- COG windowed reads keep per-download memory low (KB–few MB)
- All image processing is in-memory via `rasterio.MemoryFile`
- Post-processing runs batched (10 concurrent) with clip → square-frame → reproject
- Enrichment (NDVI, weather, change detection) currently runs on the union bounding box, not per-AOI
- Images stored as GeoTIFFs under `imagery/{raw,detail,framed,clipped}/{project}/{ts}/{aoi_name}/`

## Options Evaluated

### Option 1: Individual Images Per AOI (Recommended)

Keep the current per-AOI imagery pattern. Each fan-out activity produces its own clipped GeoTIFFs. Add an aggregation summary (CSV/JSON) at the end, but do not combine rasters.

**Pros:**

- Already implemented — no new image processing code needed
- Natural fit for fan-out architecture: each activity is self-contained
- Memory-bounded: each activity processes one small COG window
- Per-AOI images are directly useful for EUDR compliance (one polygon = one deforestation-free proof)
- Frontend can lazy-load thumbnails (no multi-GB transfer)
- Failure isolation: one AOI failure doesn't block others

**Cons:**

- Many small files in blob storage (mitigated by hierarchical naming)
- Frontend needs pagination/gallery UX for 200+ results
- No single "overview" visualisation out of the box

### Option 2: Single Consolidated Mosaic

After fan-in, stitch all per-AOI imagery into a single bounding-box raster.

**Pros:**

- Single file to transfer and display
- Clean "overview" visualisation

**Cons:**

- Extremely expensive for geographically dispersed AOIs (empty space dominates the raster)
- Memory spike during stitching scales with union bounding box area, not AOI count — 200 global polygons could require a multi-GB raster
- Requires a heavyweight "aggregate" activity after fan-in, re-introducing a single-point bottleneck
- No clear value for EUDR (regulators need per-polygon evidence, not one blended image)
- Stitching different CRS projections and resolutions is error-prone
- If stitching fails, all AOI results are lost

## Decision

**Option 1: Individual images per AOI.**

The per-AOI pattern is already working, fits the fan-out architecture, and serves the primary EUDR use case directly. A mosaic overview can be added as a future progressive enhancement (e.g., a lightweight SVG/canvas map on the frontend with per-AOI thumbnail markers) without changing the backend imagery pipeline.

### Complementary Improvements to Ship with Bulk AOI (#311)

1. **Aggregated summary artifact** — After fan-in, produce a `summary.csv` with per-AOI metrics (NDVI mean/min/max, change detection score, acquisition dates, image count). This satisfies the "aggregated view" requirement from #311 without stitching rasters.

2. **Tile deduplication** — AOIs sharing the same Sentinel-2 tile should reuse a single download. Group acquisition by tile ID before fan-out to reduce the ~1,400 orders problem.

3. **Per-AOI enrichment** — Current enrichment runs on the union bbox. Split into per-AOI NDVI/change computations inside the fan-out activities so results are directly attributable.

4. **Frontend gallery/table** — Paginated results view with per-AOI thumbnails, sortable by metric. Deferred to the frontend build (#86) but API contract should support it now.

## Consequences

### Positive

- No new image stitching code — reduced complexity and risk
- Memory stays bounded per activity
- EUDR compliance output is per-polygon by default
- Tile deduplication reduces API calls and download time for clustered AOIs
- Aggregated CSV provides the "bulk overview" users need

### Trade-offs

- No single visual overview image from the backend (frontend can compose one from per-AOI tiles)
- More small blob files to manage (mitigated by TTL policy on imagery containers)
