# Manual coffee and cattle/pasture scenarios

An **opt-in reference pack** for exploring real satellite evidence, tracked
by #1618 under #1379. These are source-derived landscape AOIs, not surveyed farms,
certified commodity plots, or a benchmark of Canopex's detection accuracy.

**Nothing here runs automatically.** No CI jobs, regression assertions, runner
defaults or production configuration are changed. The existing real runner's
nonrecursive `eudr_scenarios/*.kml` discovery excludes this subdirectory.
Use the individual KML paths below, or open them in Google Earth/QGIS.

## Cases

Map locators below are **latitude, longitude**, rounded from the source sample
centre. KML/manifest coordinates are **longitude, latitude**. The KML polygons,
not the locator points, define the AOIs.

| KML | Country / locator | Reference observation | AOI area |
| --- | --- | --- | --- |
| [coffee_recent_loss.kml](coffee_recent_loss.kml) | Ethiopia: 6.889887, 35.299779 | 76 pixels first mapped as deforested in 2021-2023 | 6.75 ha |
| [cattle_pasture_recent_loss.kml](cattle_pasture_recent_loss.kml) | Paraguay: -23.508415, -56.091385 | 29 pixels first mapped as deforested in 2021 | 2.38 ha |
| [coffee_nonforest_control.kml](coffee_nonforest_control.kml) | Ethiopia: 5.904316, 38.314160 | 911 pixels: no mapped first loss year, other land cover without afforestation | 81.02 ha |
| [cattle_pasture_nonforest_control.kml](cattle_pasture_nonforest_control.kml) | Paraguay: -23.241616, -59.968873 | 1,104 pixels: no mapped first loss year, other land cover without afforestation | 90.88 ha |
| [coffee_historical_loss.kml](coffee_historical_loss.kml) | Ethiopia: 6.191706, 38.227009 | 57 pixels first mapped as deforested in 2015 | 5.07 ha |
| [cattle_pasture_historical_loss.kml](cattle_pasture_historical_loss.kml) | Paraguay: -27.145784, -55.691186 | 30 pixels first mapped as deforested in 2004 | 2.39 ha |

The recent cases deliberately select loss pixels, sometimes in many small
disconnected patches. They are useful positive references and MultiPolygon
inputs, **not unbiased estimates of whole-farm loss percentage**. Thirty-metre
reference pixels, mixed satellite pixels, polygon edges, clouds and observation
dates can all affect the pipeline's signal. No fixed NDVI or determination
result is asserted.

The controls answer a narrower question than "no deforestation":
**does the pipeline avoid inventing forest conversion for reference nonforest?**
Class 91 does not identify coffee, pasture, or unchanged agricultural management.
Current commodity use inside these derived polygons has not been independently
verified. Do not call these deforestation-free farms, stable-production ground
truth, or EUDR-compliant suppliers.

Historical first loss before 2021 must not be relabelled post-cutoff merely
because current imagery is nonforest. A *first*-loss-year map does not exclude
subsequent regrowth/reclearing; the historical clips contain some regrowth
classes. These cases are not proof that no later conversion happened.

## Where the labels and boundaries come from

1. [PLUTo: Post-deforestation Land Use in the Tropics](https://doi.org/10.5281/zenodo.17831353)
   supplies the sample IDs, approximately 1 km landscape chip extents, and
   `coffee` / `pasture` labels. Five selected rows are from its training split;
   the recent coffee-loss row is from its test split. Each split is recorded
   in the manifest; this pack is not a held-out model evaluation.
2. [European Commission JRC Tropical Moist Forest](https://forobs.jrc.ec.europa.eu/TMF/data),
   **v1_1982_2025**, supplies current first-deforestation-year and transition
   subtype rasters. The masks here are derived from those rasters inside the
   selected chip extents, not from assumed farm outlines.
3. [manifest.json](manifest.json) records source URLs, hashes, original mask
   year distributions, window offsets, predicates, polygon/pixel counts and
   reference dates. [references/](references/) contains six small, aligned
   two-band GeoTIFF extracts: band 1 = first loss year; band 2 = transition
   subtype. The internal validity mask excludes invalid pixels. Zero in band 1
   is meaningful data, not a generic nodata value.

**Not independent corroboration:** PLUTo itself uses JRC TMF. Its description
advertises 2000-2020 loss, but some downloaded masks include 2021. Current TMF
also revises earlier dates and classifications. We retain the original mask
hash/counts and use the explicitly pinned current TMF reference for case labels,
without silently treating source agreement as independent validation.

Reproduction of each geometry:

- Read the identified PLUTo mask's geographic bounds.
- In the TMF grid, retain only whole pixels inside those bounds: ceil the
  starting row/column, floor the ending row/column. No resampling.
- Apply the recorded predicate to valid pixels. Recent: first year 2021-2023.
  Historical: 2015 for coffee, 2004 for pasture. Control: first year zero
  **and** subtype 91, retaining only the largest four-connected component.
- Polygonize at four-connectivity, retaining holes and disconnected components.
  Do not buffer, simplify, or substitute a bounding rectangle. KML coordinates
  are serialized to 12 decimal places; that precision does not imply survey
  accuracy. Areas use WGS84 geodesic polygon area.

The committed clips freeze the reference; the public download URLs may return
revised data later. Check their hashes before trying to reproduce this edition.

### Attribution and reuse

PLUTo dataset contributors, *Post-deforestation Land Use in the Tropics* (2025),
DOI above, **CC BY 4.0**. Modifications: selected sample rows/extent metadata,
not a redistribution of the imagery archive.

European Commission Joint Research Centre, *Tropical Moist Forest*,
v1_1982_2025; Vancutsem et al., *Science Advances* (2021),
[doi:10.1126/sciadv.abe1603](https://doi.org/10.1126/sciadv.abe1603).
Modifications: clipped rasters and derived pixel polygons. See the
[Commission reuse notice](https://commission.europa.eu/legal-notice_en)
(CC BY 4.0 for EU-owned content unless otherwise indicated).
No affiliation, endorsement, property ownership, cattle movement, or supplier
culpability is asserted.

## Run only the cases you choose

Complete export runs require the local ownership setup introduced by **#1617**
(fixing #1616): disposable Azurite, initialized Cosmos `orgs`/`users`/`runs`,
the local emulator endpoint/key/database configuration, Core Tools, and the
`dev` dependencies. The prerequisite merged in #1617 on 2026-10-28: use the
current runner with this local setup, not an auth bypass. Do not start
this runner on a port already occupied by the shared Functions host.

From the repository root, explicitly choose one or a pair:

```bash
uv run python scripts/real_acquisition_runner.py \
  tests/fixtures/eudr_scenarios/manual/coffee_recent_loss.kml \
  tests/fixtures/eudr_scenarios/manual/coffee_nonforest_control.kml

uv run python scripts/real_acquisition_runner.py \
  tests/fixtures/eudr_scenarios/manual/cattle_pasture_recent_loss.kml \
  tests/fixtures/eudr_scenarios/manual/cattle_pasture_nonforest_control.kml

uv run python scripts/real_acquisition_runner.py \
  tests/fixtures/eudr_scenarios/manual/coffee_historical_loss.kml \
  tests/fixtures/eudr_scenarios/manual/cattle_pasture_historical_loss.kml
```

These commands use live providers and may take minutes or fail upstream.
They write current-run exports and `result.json` beneath
`.real-acquisition-output/<fixture-stem>/<instance-id>/`.
Do not add them to `make check`, CI, or the synthetic regression corpus.

## Time coverage is a separate acceptance check

**The runner does not read this manifest or apply its suggested date windows.**
It has no date-range CLI, and its default scene selection does not guarantee
both sides of a clearing event. A successful run may show only present-day
cover. KML upload alone cannot guarantee a before/after deforestation signal.

| Case | Suggested before | Suggested after | Historical coverage constraint |
| --- | --- | --- | --- |
| Coffee recent | 2020 | 2024 | Check actual Sentinel-2 dates and usable pixels |
| Pasture recent | 2020 | 2022 | Check actual Sentinel-2 dates and usable pixels |
| Both nonforest controls | 2020 | 2025 | Compare like seasons; do not equate an NDVI fall with forest loss |
| Coffee historical | 2014 | 2016 | 2014 predates Sentinel-2; a Landsat/history-capable path is required |
| Pasture historical | 2003 | 2005 | Requires Landsat/other historical imagery, not default Sentinel-2 acquisition |

Use the manifest windows when selecting dates in a date-capable workflow or
reviewing reference imagery in GIS. Do not imply the commands above perform
that selection. Reference-layer dates are not measured scene timestamps.
If usable before/after observations are absent, record **not evaluated /
insufficient evidence**, never a negative detection or passed scientific test.
Cloud-free conditions cannot be guaranteed by choosing a location.

## Human review record

- Record commit, case/input hash, run ID, requested windows, **actual** scene
  IDs/dates and usable/cloud coverage; keep each run's exports separately.
- Open the KML and the two-band reference clip in GIS. Verify that the imagery
  comparison covers the selected polygon, not merely its bbox or centre.
- Separate mapped first forest loss from commodity attribution, current land
  cover, later regrowth, and legal/EUDR conclusions.
- Record unexpected detections and missed visible changes without changing the
  source label just to make the pipeline pass.
- A parsed PDF or HTTP 200 is mechanical success only. Record the scientific
  reviewer, evidence and disposition separately under #1379/#1223.

This pack has source-mask/geometry validation, not completed human imagery
review or live pipeline acceptance for these six new AOIs.

On 2026-10-28, all 12 bounded before/after catalogue queries returned HTTP 200
and at least one real scene under a scene-level cloud-cover filter below 20%.
Exact example scene IDs/dates are in the manifest. Those checks used Sentinel-2
where available and Landsat for pre-2015 windows. They establish catalogue
availability, not cloud-free pixels in the AOI or verified visible conversion;
Landsat 7 examples also require checking scan-line gaps.
