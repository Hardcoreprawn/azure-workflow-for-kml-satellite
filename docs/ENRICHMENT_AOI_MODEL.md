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

Other fields include frame plans, weather, NDVI statistics/raster references,
change detection, EUDR evidence and errors. Exact optionality and types belong
in the schema/model, not a duplicated Markdown field specification. Current
weather values can be dictionaries or lists; NDVI entries/paths can be null.
Some nested blocks allow additional fields and are not fully constrained schemas.

Run-level summary/projection fields are not substitutes for parcel evidence.
Consumers must preserve parcel identity and use returned manifest paths rather
than guessing evidence from aggregate values or filenames.

## Availability and Artifact Identity

SAFE_MODE and synthetic test mode can omit expensive/external observations.
Missing weather, null NDVI, empty source results or skipped phases mean unavailable
evidence, not reassuring observations or a legal determination. Validate direct
and Durable split paths against [enrichment tests](../tests/test_enrichment_runner.py).

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
