# Enrichment AOI Model Contract

**Status:** Draft contract for #1447  
**Last updated:** 2026-08-24

## Purpose

This document defines the target enrichment handoff and manifest model for
runs with one or more AOIs. It exists because #1439 exposed that the current
single-AOI and multi-AOI paths can disagree about metadata, SAFE_MODE, blob
paths, and exporter inputs.

The product rule is simple: a one-parcel KML and a many-parcel KML should
produce the same kind of parcel evidence. The implementation can optimise
execution, but it must not expose different data contracts to exports,
review, or monitoring just because `aoi_count == 1`.

## Persona And JTBD

Primary persona: ESG/EUDR compliance operator.  
Secondary persona: agricultural advisor handling parcel batches.

Job to be done: upload one or many production plots and receive audit-ready,
per-plot evidence with stable metadata, reproducible exports, and clear
artifact provenance.

## Current Problem

Today the enrichment pipeline has two shapes:

- top-level/single/union enrichment, where parcel evidence is inferred from
  top-level manifest fields and exporter fallbacks;
- multi-AOI per-parcel enrichment, where evidence lives in
  `per_aoi_enrichment`.

That split creates several failure modes:

- single-AOI exports can lose `name`, `area_ha`, source geometry metadata, or
  other AOI facts unless a fallback reconstructs them;
- direct `run_enrichment(...)` and Durable activity orchestration can diverge;
- SAFE_MODE can be enforced in one entrypoint but bypassed in another;
- passing `aoi_index=0` for a single AOI can accidentally change established
  raster blob paths;
- top-level fields become both summary data and implicit parcel data, making
  ownership of each value unclear.

## Target Contract

### Canonical Manifest Shape

New v2 producers must include `schema_version: "enrichment-manifest/v2"`.
Readers may continue to accept missing `schema_version` as a legacy v1
manifest during the migration, but new writes must be explicit.

Every enriched run with at least one AOI must produce:

```json
{
  "schema_version": "enrichment-manifest/v2",
  "run": {
    "project_name": "example",
    "timestamp": "2026-08-24T19:00:00Z",
    "eudr_mode": true
  },
  "summary": {
    "aoi_count": 1,
    "multi_region": false,
    "frame_plan": []
  },
  "per_aoi_enrichment": [
    {
      "aoi_index": 0,
      "name": "Plot 1",
      "area_ha": 12.3,
      "coords": [[0.0, 0.0]],
      "bbox": [[0.0, 0.0]],
      "center": {"lat": 0.0, "lon": 0.0},
      "source_geometry_type": "polygon",
      "plot_area_ha": 12.3,
      "frame_plan": [],
      "weather_daily": [],
      "ndvi_stats": [],
      "ndvi_raster_paths": [],
      "change_detection": null,
      "eudr": null,
      "errors": []
    }
  ]
}
```

The exact nested enrichment payloads can stay open while they are still
evolving, but the container shape and AOI identity fields are not open-ended.

### Required AOI Fields

Each `per_aoi_enrichment[]` entry must contain:

| Field | Type | Notes |
|-------|------|-------|
| `aoi_index` | int | Position in the submitted AOI list. Stable for annotations and exports. |
| `name` | string | Source feature/AOI label. Empty only if the uploaded file had none. |
| `area_ha` | float | Computed AOI area used in exports and summaries. |
| `coords` | list | AOI polygon coordinates in lon/lat order. |
| `bbox` | list | AOI bbox used for imagery/enrichment. |
| `center` | object | `lat`/`lon` center point. |
| `source_geometry_type` | string | Supplier-declared geometry type when available. |
| `plot_area_ha` | float \| null | Supplier-declared plot area when available. |
| `frame_plan` | list | Frames considered for this AOI. |
| `weather_daily` | list | Weather evidence for this AOI. |
| `ndvi_stats` | list | NDVI evidence for this AOI. |
| `ndvi_raster_paths` | list | AOI-scoped or legacy-compatible raster paths. |
| `change_detection` | object \| null | Change evidence for this AOI. |
| `eudr` | object \| null | EUDR-specific evidence and determination inputs. |
| `errors` | list | Non-empty if this AOI failed while other AOIs continued. |

### Top-Level Fields

Top-level manifest fields must be summary or projection only:

- allowed: run metadata, aggregate timing/resource use, aggregate summaries,
  compatibility projections documented as such;
- not allowed: the only copy of parcel evidence needed by exports.

For v2 manifests, top-level `coords`, `bbox`, and `center` are legacy
compatibility projections for existing consumers. They may mirror the only AOI
for a single-AOI run or represent a run-level union/summary, but exports and
new product code must not treat them as the canonical parcel record.

Exports must prefer `per_aoi_enrichment`. Fallbacks from top-level evidence are
temporary compatibility only and should shrink as v2 producers land.

## Artifact Path Policy

AOI-scoped artifacts should have a deterministic owner.

Target policy:

- if an artifact belongs to one AOI, its owning `per_aoi_enrichment[]` entry
  records the path;
- if an artifact is a run-level summary or overview, it stays top-level;
- multi-AOI runs must scope same-named AOI artifacts with `aoi-{index}/` to
  avoid collisions;
- existing single-AOI unscoped raster paths are preserved until an explicit
  migration changes them.

This means implementation code may call single-AOI enrichment with
`aoi_index=None` for blob-path compatibility while still writing
`aoi_index=0` into the data model entry. Execution-path path scoping and data
model identity are separate concerns.

## SAFE_MODE Contract

SAFE_MODE must be enforced at the same semantic boundary for all entrypoints:

- Durable `_phase_enrichment`;
- registered activity `run_enrichment`;
- direct Python `treesight.pipeline.enrichment.run_enrichment(...)` calls used
  by tests and local runners;
- per-AOI helper paths such as `enrich_single_aoi`.

If SAFE_MODE skips external enrichments, it must skip them for one AOI and many
AOIs identically. A test must prove this across both orchestrator/activity and
direct runner paths.

## Pydantic Recommendation

Pydantic is useful here, but only at the contract boundary.

Use Pydantic models for:

- `EnrichmentManifestV2`;
- `RunSummary`;
- `PerAoiEnrichment`;
- small value models such as `CenterPoint`, `ArtifactPaths`, and `AoiEvidenceError`.

Do not use Pydantic to wrap every internal helper return or every NDVI/weather
row while those internals are still fluid. Keep hot-path computation as plain
dict/list/dataclass structures if that keeps code simple, then validate once
when building the manifest and once when loading it for exports.

Recommended implementation location:

```text
treesight/models/enrichment_manifest.py
```

The models should provide:

- `model_validate(...)` for runtime boundary checks;
- `model_dump(mode="json", exclude_none=True)` for blob serialization;
- JSON Schema generation for future `docs/schemas/enrichment-manifest-v2.schema.json`.

This gives us a documented data contract without forcing a broad pipeline
rewrite in the first slice.

## Implementation Slices

### Slice 1: Contract And Producers

- Add Pydantic contract models.
- Require `schema_version: "enrichment-manifest/v2"` on new manifests.
- Make direct `run_enrichment(...)` produce `per_aoi_enrichment` for a single
  AOI as length 1.
- Preserve legacy single-AOI raster path shape unless explicitly migrated.
- Add tests in `tests/test_enrichment_runner.py`.

### Slice 2: Durable Activity Parity

- Align `_phase_enrichment`, `run_enrichment`, `enrich_single_aoi`, and
  `enrich_finalize` around the same manifest builder.
- Prove SAFE_MODE parity across orchestrator/activity and direct runner paths.
- Add tests in `tests/test_orchestrator_phases_extra_coverage.py` and activity
  tests if needed.

### Slice 3: Export Consumers

- Make EUDR CSV, GeoJSON, and PDF exports consume `per_aoi_enrichment` first.
- Keep explicit compatibility fallback only for pre-v2 manifests.
- Add tests in `tests/test_export.py` and any EUDR-specific export suites.

### Slice 4: Schema And Cleanup

- Generate/check in `docs/schemas/enrichment-manifest-v2.schema.json`.
- Remove or isolate obsolete top-level fallback guesses.
- Update operations/API docs if external response payloads change.

## Validation Gates

First narrow check:

```bash
make test-fast TESTS="tests/test_enrichment_runner.py tests/test_export.py tests/test_orchestrator_phases_extra_coverage.py"
```

Handoff check:

```bash
make check
```

Required behavioral assertions:

- one-AOI and many-AOI runs both expose `per_aoi_enrichment`;
- single-AOI metadata is not reconstructed by export fallbacks;
- SAFE_MODE skips the same external work through every enrichment entrypoint;
- single-AOI raster path compatibility is either preserved by test or migrated
  by an explicit, documented migration test;
- exporters do not depend on top-level parcel metadata when v2 manifest data is
  present.

## Open Decisions

1. Do we preserve single-AOI unscoped blob paths indefinitely, or introduce an
   `aoi-0/` migration with redirect/compatibility support?
2. Should `per_aoi_metrics` remain separate from `per_aoi_enrichment`, or be
   nested into each AOI entry?
3. Which fields become strict Pydantic submodels in v2, and which remain open
   evidence bags until the next schema revision?
