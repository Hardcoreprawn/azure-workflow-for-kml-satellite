# EUDR Compliance Workflow — Cattle Supply Chains in Pará

<!-- markdownlint-disable MD028 MD040 -->

**Date:** 14 April 2026
**Status:** Domain specification — informs Stage 2F/2G implementation.
**Scope:** End-to-end EUDR compliance workflow for cattle ranches in
São Félix do Xingu and similar Amazon frontier municipalities.

---

## Purpose

This document defines the data layers, operational workflow, and
architectural requirements for EUDR-ready geolocation evidence. It is
the technical specification that backs the persona analysis in
`PERSONA_DEEP_DIVE.md` §8 and the EUDR methodology published at
`/eudr-methodology.html`.

The core requirement: **prove that every hectare where the cattle lived
has had no deforestation after 31 December 2020.**

---

## Scope boundary — what Canopex does and does not do

| In scope (Canopex) | Out of scope (importer's ERP / traceability platform) |
|---------------------|------------------------------------------------------|
| Ingest and validate ranch boundary polygons | Parse GTA movement documents |
| Satellite-based deforestation detection | Reconstruct cattle birth→slaughter chain |
| Multi-year land-use history from imagery | Maintain supplier relationship database |
| Risk overlay (protected areas, embargoes) | Submit to EU Information System |
| Generate audit-grade evidence PDF/GeoJSON | Issue compliance certificates |
| Continuous monitoring alerts | Manage contractual supplier requirements |

Canopex provides the **geolocation evidence layer** that plugs into the
importer's broader compliance workflow. We do not handle supply-chain
document management or regulatory submission.

---

## 1. Data layers

These are the minimum layers required for EUDR compliance for cattle in
Pará. They fall into four groups: property boundaries, land-use history,
risk context, and traceability.

### 1.1 Property boundary and legal identity

Define *where* the ranch is and what land legally belongs to it.

| Layer | Source | Format | Canopex role |
|-------|--------|--------|-------------|
| CAR polygon | SICAR / state agencies | Shapefile, GeoJSON, KML | **Primary input** — user uploads or we query SICAR API |
| SIGEF/INCRA titles | INCRA geodatabase | Shapefile | Validation reference (future integration) |
| CCIR | Federal registry | Metadata (non-spatial) | Out of scope — importer's document |
| Parcel fragmentation | Derived from CAR | Multi-polygon | Must handle natively |

**Key detail:** CAR boundaries are self-declared and frequently
inaccurate. The app should flag self-intersections, topology errors,
and overlaps with neighbours or protected areas during ingest.

### 1.2 Land-use and deforestation history

Prove whether the land was deforested after the cutoff date.

| Layer | Source | Resolution | Temporal | Canopex integration |
|-------|--------|-----------|----------|-------------------|
| PRODES | INPE | 30 m | Annual (since 1988) | **Must integrate** — authoritative deforestation |
| DETER | INPE | 25 m | Near-real-time (daily) | **Must integrate** — monitoring alerts |
| MapBiomas land-use | MapBiomas Consortium | 30 m | Annual (since 1985) | **Should integrate** — pasture/forest/regen classes |
| MapBiomas Fire | MapBiomas Consortium | 30 m | Annual | Nice to have — fire scar evidence |
| Sentinel-2 imagery | ESA / Planetary Computer | 10 m | 5-day revisit | **Already integrated** — NDVI, change detection |
| Landsat | USGS / Planetary Computer | 30 m | 16-day revisit | Fallback for older time series |
| ESA WorldCover | ESA / Planetary Computer | 10 m | Annual | **Already integrated** — land classification |

**Integration priority:**

1. Sentinel-2 (already done)
2. ESA WorldCover (already done)
3. PRODES (critical — authoritative source, needed for compliance)
4. DETER (critical — real-time monitoring)
5. MapBiomas (high value — 35+ years of annual land-use classification)
6. MapBiomas Fire (nice to have)

### 1.3 Environmental and legal risk context

Determine whether the ranch overlaps protected or sensitive areas.

| Layer | Source | Canopex integration |
|-------|--------|-------------------|
| Indigenous territories | FUNAI | Must integrate — overlap = automatic non-compliance |
| Conservation units (federal, state, municipal) | ICMBio / MMA | Must integrate — via WDPA or direct |
| APP (Permanent Preservation Areas) | Derived from topography + hydrology | Future — requires DEM + river network |
| Legal Reserve (80% forest in Amazon biome) | Derived from CAR + forest cover | Future — requires CAR integration |
| IBAMA embargoed areas | IBAMA open data | Should integrate — sanctions database |
| WDPA protected areas | protectedplanet.net | **Already integrated** |

### 1.4 Cattle traceability and movement

These connect the animals to the land. **Out of Canopex's scope** — included
for architectural context so the evidence layer aligns with the full chain.

| Layer | Source | Notes |
|-------|--------|-------|
| GTA (Guia de Trânsito Animal) | State veterinary agencies | Origin → destination movement docs |
| Batch-level supplier declarations | Supplier | Which pasture/parcel animals were raised on |
| Indirect supplier chain | Traceability platform | Previous ranches the cattle passed through |
| Slaughterhouse intake records | Processor | Final link for EUDR reporting |

The importer or their traceability platform handles these. Each farm in
the GTA chain needs its CAR polygon checked — this is where the importer
sends polygons to Canopex for evidence.

---

## 2. End-to-end workflow

Designed for large ranch polygons (5,000–20,000 ha) typical of
São Félix do Xingu.

### Step 1: Ingest and validate the ranch boundary

**Input:** CAR polygon(s) from the supplier, uploaded as KML/GeoJSON.

**Processing:**

- Parse and validate geometry (existing `validate_kml_bytes` pipeline).
- Check for self-intersections, zero-area slivers, topology errors.
- Detect overlaps with protected areas (WDPA — already integrated).
- Identify multiple disjoint parcels within one submission.
- Reproject to consistent CRS (SIRGAS 2000 / EPSG:4674 for Brazil;
  WGS 84 / EPSG:4326 for storage and display).

**Output:** Validated multi-polygon with metadata (area, parcel count,
overlap flags).

**Canopex status:** Partially implemented. KML parsing, validation,
and WDPA check exist. Missing: self-intersection detection, SIGEF
cross-reference, CRS enforcement.

### Step 2: Generate multi-year land-use history

For each parcel:

- Acquire Sentinel-2 imagery across the EUDR-relevant time range
  (2021-01-01 to present) — **already implemented**.
- Overlay PRODES annual deforestation polygons — **not yet integrated**.
- Overlay MapBiomas annual land-use classification — **not yet integrated**.
- Compute NDVI time series and change detection — **already implemented**.
- Identify transitions:
  - Forest → pasture (deforestation)
  - Pasture → forest (regeneration)
  - Any clearing after the EUDR cutoff date

**Output:** Deforestation timeline for the entire ranch, with per-pixel
or per-zone classification.

### Step 3: Determine EUDR compliance status

For each polygon:

| Finding | Status | Action |
|---------|--------|--------|
| Deforestation detected after cutoff | **Non-compliant** | Flag, block, alert |
| Only pre-cutoff deforestation | **Conditionally compliant** | Requires documentation of legal status |
| No deforestation in time series | **Clean** | Issue evidence package |
| Data gap (cloud cover, no imagery) | **Inconclusive** | Flag for manual review |

The AI narrative should lead with a **clear verdict**, then provide
supporting detail. Compliance officers need yes/no, not an essay.

### Step 4: Trace cattle movements (out of scope)

This step is the importer's responsibility:

- Parse GTA documents to reconstruct the chain:
  birth farm → rearing farm → finishing farm → slaughterhouse.
- For each farm in the chain: submit its CAR polygon to Canopex
  (repeat steps 1–3).

**Canopex's role:** Accept batch submissions of multiple ranch polygons
from traceability platforms (API or bulk upload). Return evidence for
each.

### Step 5: Generate the EUDR geolocation evidence package

For each batch of cattle, Canopex produces:

- All polygons in GeoJSON (validated, with area and coordinates).
- Deforestation timeline summary (pre/post cutoff).
- Risk overlays (protected areas, embargoes, indigenous territories).
- Satellite imagery snapshots (before/after cutoff).
- NDVI trend data and change detection results.
- AI assessment narrative with clear verdict.
- Methodology description and data source citations.

**Canopex status:** Partially implemented. PDF export exists but needs
PRODES/DETER overlay, per-parcel breakdown, and GeoJSON export.

### Step 6: Continuous monitoring

Because São Félix do Xingu is a high-risk municipality:

- Run DETER alerts weekly against active supplier polygons.
- Run Sentinel-2 change detection on a configurable schedule.
- Flag new clearing inside supplier polygons.
- Trigger re-verification and alert the user.

**Canopex status:** Not yet implemented. Requires scheduled analysis
(roadmap item, post-2F).

---

## 3. Architectural implications

### Performance and scale

| Requirement | Implication |
|-------------|------------|
| Single polygon up to 50,000 ha | Raster operations must tile/chunk, not load entire AOI into memory |
| Multi-parcel submission (3–10 polygons per ranch) | Fan-out pipeline (already implemented) handles this |
| Multi-year time series (5+ years × 70+ revisits/year) | Must select representative frames, not process every scene |
| Concurrent batch submissions (50–500 ranches) | Queue-based processing with backpressure; compute-time limits per tier |

### Data integration priorities

| Priority | Layer | Effort | Impact |
|----------|-------|--------|--------|
| P0 | Sentinel-2 + WorldCover + WDPA | ✅ Done | Core evidence |
| P1 | PRODES annual deforestation | Medium | Authoritative compliance source |
| P1 | DETER near-real-time alerts | Medium | Monitoring + risk scoring |
| P2 | MapBiomas land-use time series | Medium | 35-year history, rich classification |
| P2 | IBAMA embargoed areas | Low | Sanctions cross-reference |
| P2 | FUNAI indigenous territories | Low | Automatic non-compliance flag |
| P3 | MapBiomas Fire | Low | Fire scar evidence |
| P3 | APP/Legal Reserve derivation | High | Requires DEM + hydrology |

### Pricing and limits

Current `aoi_limit` (parcel count per submission) is necessary but
insufficient. Additional limits to consider:

- **Total area per submission** — a 50,000 ha polygon costs 500× more
  compute than a 100 ha polygon.
- **Compute-time budget per tier** — cap processing time rather than
  (or in addition to) parcel count.
- **Historical depth** — free tier gets 1 year; paid tiers get 5+ years.
- **Monitoring frequency** — free = manual re-run; paid = scheduled
  weekly/monthly.

### API surface for traceability platforms

Traceability platforms (e.g., Visipec, JBS Green Platform) will want to
submit batch polygon checks via API rather than web UI. This requires:

- `POST /api/eudr/batch-check` — accept array of GeoJSON polygons.
- Async processing with webhook or polling for results.
- Structured JSON response per polygon (verdict, evidence, risk flags).
- API key authentication (not browser-based SWA auth).

This is a Stage 3+ feature.

---

## 4. PRODES and DETER integration notes

### PRODES (annual deforestation)

- Published by INPE (Brazilian National Institute for Space Research).
- Vector polygons of annual deforestation increments since 1988.
- Available as shapefiles from [TerraBrasilis](http://terrabrasilis.dpi.inpe.br/).
- Update frequency: annual (published ~Q2 for previous year).
- Integration approach: download annual shapefiles, intersect with
  submitted AOI polygon, report deforestation area by year.
- Alternative: query TerraBrasilis STAC/OGC API if available.

### DETER (near-real-time alerts)

- Published by INPE via TerraBrasilis.
- Daily deforestation and degradation alerts (25 m resolution).
- Available as shapefiles or via API.
- Integration approach: periodic (weekly) download of new alerts,
  spatial join against active monitored polygons, push notification
  to user if overlap detected.

### MapBiomas

- Published by MapBiomas Consortium (collaboration of NGOs, universities,
  tech companies).
- Annual land-use/land-cover classification for all of Brazil (30 m).
- Available as Cloud Optimized GeoTIFFs on Google Earth Engine and
  direct download.
- 35+ years of data (1985–present).
- Integration approach: for each AOI, extract annual land-use class
  rasters, compute transition matrix (forest→pasture, etc.), identify
  post-cutoff transitions.

---

## References

- INPE TerraBrasilis: <http://terrabrasilis.dpi.inpe.br/>
- MapBiomas: <https://mapbiomas.org/>
- SICAR (CAR registry): <https://www.car.gov.br/publico/imoveis/index>
- EU Deforestation Regulation (2023/1115): cutoff date 31 December 2020
- Canopex persona analysis: `docs/PERSONA_DEEP_DIVE.md` §8
- Canopex EUDR methodology: `website/eudr-methodology.html`
