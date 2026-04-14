# ADR 0003: Scaling Architecture — What to Adopt vs Defer

## Status

Accepted

## Context

External review of the current architecture identified areas that would
"creak" under EUDR-scale compliance workloads (hundreds of parcels,
multi-source evidence, audit-grade reproducibility). The review suggested
adding PostGIS, a rules engine, and a separate compliance service.

We evaluated each suggestion against current product stage (pre-revenue,
single regulatory framework, low parcel volume) and mapped the worthy
parts to existing roadmap items.

## Decisions

### Adopt now (via existing roadmap items)

1. **Versioned compliance verdicts.**
   Every compliance fact must record `rule_version` and `dataset_version`
   so verdicts are reproducible and auditable. Implement in #583 (data model
   cleanup) and #603 (deforestation-free determination).

2. **Pre-compute on upload, read on query.**
   When a polygon is first submitted, run the full history computation and
   store parcel-level facts. Subsequent dashboard/report views read stored
   results — no recomputation. Implement in #578 (per-AOI enrichment).

3. **Evidence as first-class artefacts.**
   Each run produces typed evidence blobs (GeoJSON, raster overlays, PDF)
   with pointers stored in the run manifest. Implement in #582 (EUDR
   per-parcel evidence export) and #587 (audit-grade PDF report).

4. **Dataset provenance per data source.**
   Each external dataset query records the source, version/date, and spatial
   extent used. Implement across 2G.1 data source issues (#604, #607, #608,
   #609).

### Defer (revisit at stated trigger)

1. **Geospatial warehouse (PostGIS).**
   Cosmos DB spatial queries (ST_WITHIN, ST_INTERSECTS) are sufficient for
   current query patterns. PostGIS adds operational burden (connection
   pooling with serverless, backups, schema migrations) without justification
   at current scale.
   **Trigger:** >100k stored parcels or complex spatial join queries that
   Cosmos cannot serve efficiently.

2. **Rules engine / rules-as-data.**
   One regulatory framework (EUDR), one cutoff date, a handful of rules.
   Python functions with versioned constants are simpler, testable, and
   auditable. A rules engine is warranted when non-engineers need to manage
   rule changes across multiple regulatory regimes.
   **Trigger:** Second regulatory framework or customer-configurable rule
   sets.

3. **Separate compliance service.**
   The Durable Functions orchestrator is the control plane. Compliance logic
   lives in `treesight/pipeline/eudr.py` and is called from existing
   activities. A separate service adds deployment and failure-mode complexity
   without benefit at current team size.
   **Trigger:** Team splits into separate backend squads, or compliance logic
   needs independent scaling/deployment.

4. **Formal data lake path conventions.**
   Current blob paths are already structured. Renaming to `raw/geo/`,
   `raw/client/` etc. is cosmetic. The real value is lifecycle policies
   (cold tier for old rasters, retention for evidence) — that's ops, not
   architecture.
   **Trigger:** Bundle with next infra/storage cleanup PR.

### Primary scaling risk identified

**Planetary Computer API rate limits and latency.** At 200 parcels × 5 data
sources × 5 years of history, the bottleneck is thousands of STAC queries
and raster downloads — not the database layer.

Mitigations already planned:

- Spatial clustering (#581) to batch nearby parcels into fewer queries
- Tile/imagery caching in blob (#586)
- Async fan-out with backpressure (Durable Functions, already in place)

## Consequences

- #583 scope includes adding `rule_version` and `dataset_version` fields
- No new infrastructure components until stated triggers are hit
- Architecture remains serverless-first with Cosmos + Blob as primary stores
- Scaling investment focuses on upstream API efficiency, not database changes
