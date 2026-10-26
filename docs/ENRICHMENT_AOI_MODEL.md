# Enrichment AOI Contract

Current v2 producer contract, reconciled 2026-09-16. The former #1447 proposal
was implemented through #1449 (including #1448/#1450). Historical design text
is available in Git history; this file is not a second migration plan.

## Authority

- [Pydantic model](../treesight/models/enrichment_manifest.py): Python boundary.
- [JSON schema](schemas/enrichment-manifest-v2.schema.json): persisted envelope.
- [Record tests](../tests/test_records.py): schema parity and validation.
- [Runner](../treesight/pipeline/enrichment/runner.py): producer behavior.

New manifests carry `schema_version: "enrichment-manifest/v2"`, `run`, `summary`
and `per_aoi_enrichment`. The model defaults the per-AOI list to empty; evidence
completeness and expected AOI counts require behavioral validation beyond schema
parsing. Old record types or retained projections do not define new writes.

## Parcel Evidence

Each per-AOI entry identifies `aoi_index`, `name`, `area_ha`, `geometry`, `bbox`
and named `center.lat`/`center.lon`. Geometry arrays use longitude/latitude order.
Source geometry type and declared plot area can be retained for downstream review.
One-parcel and multi-parcel runs use the same per-AOI contract.

### Polygon model

The immutable [geometry model](../treesight/models/geometry.py) is deliberately
small: a `PolygonPart` has one `outer` ring and an `inners` tuple (empty by
default). `PolygonGeometry.parts` is a non-empty tuple of these polygons.
There is no recursive nesting or inferred ring ownership.

- Coordinates are finite WGS84 longitude/latitude pairs. Rings must be closed,
  non-degenerate and form valid polygon topology.
- Inner rings exclude area from their own outer ring. They cannot lie outside
  it, overlap one another or nest inside one another.
- Separate parts cannot overlap filled area. An island inside a hole is another
  part; it can have its own inner rings.
- Ring direction does not determine membership. GeoJSON conversion preserves
  each outer ring followed by its inner rings.
- Unknown model fields fail validation rather than silently dropping geometry.
  The model does not repair, flatten or union invalid input.
- Antimeridian-crossing rings and geometry whose total longitude span exceeds
  180 degrees are rejected. Wrapped extents are unsupported; splitting into parts
  within the same AOI is not a workaround.

For analysis, the footprint is the union of each part's **outer minus inners**.
Bounding boxes are search/display extents, not substitutes for that footprint.
Area must subtract holes; NDVI statistics and analytical rasters must exclude
holes and space between parts. Serialization must preserve all these boundaries.

NDVI is unavailable if the raster window does not cover the complete plot
(`plot_not_fully_covered`), if required cloud masks or grid metadata are missing,
or if no valid in-plot pixels remain. Reflectance bands must share a grid;
categorical SCL/QA masks are reprojected using their actual CRS/transforms.
Landsat requires STAC reflectance scale/offset metadata and applies it before
band math; missing calibration metadata yields unavailable evidence.
There is no independent four-pixel cutoff in either the Python or Rust change
path. Reported valid-pixel counts are sample sizes, not a claim of scientific
accuracy or legal sufficiency; scientific acceptance remains separate work.

Other fields include frame plans, weather, NDVI statistics/raster references,
change detection, EUDR evidence and errors. Exact optionality and types belong
in the schema/model, not a duplicated Markdown field specification. Current
weather values can be dictionaries or lists; NDVI entries/paths can be null.
Some nested blocks allow additional fields and are not fully constrained schemas.

Each frame's provenance separates `display_source` from `analysis_source`.
It records both display and analysis resolution as well.
NDVI prefers the frame's multispectral collection and tries the other supported
COG sensor if the preferred computation fails or returns no usable observation,
including an explicit unavailable result. Both attempts receive the same canonical
polygon geometry, including every part and hole. NAIP is display-only; its NDVI
uses Sentinel-2 first and Landsat as fallback. Unmasked tile statistics are never
used as analytical fallback. If neither sensor succeeds, the frame stays explicitly
unavailable, retains the first returned failure reason when present, and has no
successful analysis source or resolution in provenance. The scheduled
frame plan has no same-year Landsat/Sentinel pair, so a sensor transition alone
must not be interpreted as a vegetation-change signal. Change detection skips
cross-source pairs and repeated observations for the same source/window; the
single summary trend uses the latest source series rather than mixing sensors.

Run-level summary/projection fields are not substitutes for parcel evidence.
Consumers must preserve parcel identity and use returned manifest paths rather
than guessing evidence from aggregate values or filenames.
Ordinary GeoJSON exports emit labelled features from each per-AOI entry's own
geometry and observations, including boundaries for parcels with no imagery.
Browser preflight counts one polygon-bearing Placemark as one AOI, sums its
parts and subtracts its holes for the approximate area estimate.
Selecting a parcel loads that parcel's imagery and comparison frames; resetting
selection returns to the overview without inventing union-level observations.

## Availability and Artifact Identity

SAFE_MODE and synthetic test mode can omit expensive/external observations.
Missing weather, null NDVI, empty source results or skipped phases mean unavailable
evidence, not reassuring observations or a legal determination. Validate direct
and Durable split paths against [enrichment tests](../tests/test_enrichment_runner.py).
UI summaries, NDVI timelines and AI prompts only count observations with finite
numeric NDVI means in [-1, 1] that are not explicitly unavailable. Failure
reasons remain visible separately. No usable observations means unavailable,
not a stable trajectory or post-cutoff evidence.
The same observation rule applies to monitoring baselines, per-AOI metrics and
CSV/GeoJSON/PDF summaries. AI requests and comparison controls use the selected
parcel (or the only parcel) rather than absent run-level imagery projections.

Single-AOI identity `aoi_index=0` does not itself require a path migration.
Multi-AOI raster outputs use AOI-scoped namespaces to prevent concurrent collisions;
historical single-AOI paths can remain unscoped. The
[API reference](API_INTERFACE_REFERENCE.md#blob-path-conventions) owns general
storage conventions. A referenced path alone does not prove a readable raster.

## Change Discipline

Update model, schema, producers, consumers and regression tests together. Do not
silently introduce dual formats or infer missing parcel identities. A compatibility
path requires a documented consumer and migration decision. Scientific validity,
complete source coverage and legal compliance are separate from schema validity.
