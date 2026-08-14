# Code Review — 3 April 2026

Full function-by-function review of the Python codebase. **No fixes applied** —
this document catalogues findings for triage.

**Scope:** `treesight/`, `blueprints/`, `scripts/`, `tests/`
**Test suite:** 864 passed, 28 skipped at time of review

---

## Quick Stats

| Category | High | Medium | Low | Total |
|----------|------|--------|-----|-------|
| Dead code | 2 | 2 | 2 | 6 |
| Duplication | 2 | 14 | 7 | 23 |
| Waste | — | 2 | 6 | 8 |
| Code smell | 2 | 6 | 14 | 22 |
| Magic number | — | 4 | 9 | 13 |
| Error handling | — | 4 | 5 | 9 |
| Type inconsistency | — | 4 | 3 | 7 |
| Import issue | — | — | 5 | 5 |
| **Total** | **6** | **36** | **51** | **93** |

---

## HIGH Severity

### H1 — Test stubs in production code

- **Files:** `treesight/pipeline/fulfilment.py` (L33–65),
  `treesight/providers/planetary_computer.py` (L367–450)
- **Category:** smell
- **Detail:** `_make_stub_geotiff()`, `_get_stub_geotiff()`, and
  `_stub_geotiff_cache` live in `fulfilment.py`. `_stub_search()`,
  `_stub_download()`, `_stub_composite_search()` (~90 lines) live inside the
  production `PlanetaryComputerProvider` class. This is test infrastructure
  deployed to production. Should be a separate `StubProvider` or test fixture.

### H2 — Likely dead endpoint: `demo_submit()`

- **File:** `blueprints/demo.py` (L42–100)
- **Category:** dead-code
- **Detail:** `POST /api/demo-submit` uploads KML and writes a record but does
  **not** start the durable orchestrator. It was superseded by
  `blueprints/pipeline/submission.py::demo_process()` (`POST /api/demo-process`)
  which does start the orchestrator. The old endpoint submits data that goes
  nowhere. Launch-readiness tests still reference it by source inspection, which
  would need updating.

### H3 — `graph()` helper duplicated 4× across CIAM scripts

- **Files:** `scripts/_create_user_flow.py`, `scripts/_setup_ciam.py`,
  `scripts/_setup_sso_providers.py`, `scripts/_register_ciam_app.py`
- **Category:** duplication
- **Detail:** Four independent implementations of a Microsoft Graph API helper
  with divergent behaviour (some add `beta` param, some have timeouts, some
  catch `URLError`). Should be a shared `scripts/_graph.py`.

### H4 — Hardcoded CIAM identifiers duplicated across scripts

- **Files:** `scripts/_create_user_flow.py` (L13–14, L135–143),
  `scripts/_setup_ciam.py` (L10–11, L58), `scripts/_setup_sso_providers.py`,
  `scripts/_register_ciam_app.py`
- **Category:** duplication + magic-number
- **Detail:** `APP_ID "6e2abd0a-..."`, tenant ID `"92001438-..."`, tenant name
  `"treesightauth"` appear as string literals in multiple scripts. A change to
  one requires manual update of all others.

### H5 — Cosmos/blob fallback pattern repeated 5×

- **Files:** `treesight/security/billing.py`, `treesight/security/quota.py`
- **Category:** duplication
- **Detail:** `get_subscription`, `save_subscription`,
  `get_subscription_emulation`, `save_subscription_emulation`,
  `clear_subscription_emulation`, `_get_quota_record`, `_save_quota_record` all
  repeat the same ~8-line try-Cosmos-fallback-to-blob pattern. A shared
  `_cosmos_or_blob_read/write` helper would eliminate duplication.

### H6 — AI analysis endpoint boilerplate repeated 3×

- **File:** `blueprints/analysis.py`
- **Category:** duplication
- **Detail:** `frame_analysis()`, `timelapse_analysis()`, `eudr_assessment()`
  each repeat ~30 lines of identical boilerplate: OPTIONS → auth → rate-limit →
  body-size → JSON parse → context → prompt → `generate_analysis()` → fallback →
  response. Extract to a shared `_run_analysis()` helper.

---

## MEDIUM Severity

### M1 — `_cosmos_available()` defined in 4 places

- **Files:** `treesight/security/billing.py`, `treesight/security/quota.py`,
  `blueprints/billing.py`, `blueprints/pipeline/_helpers.py`
- **Category:** duplication
- **Detail:** Body is `return bool(config.COSMOS_ENDPOINT)` in all four. Should
  be one canonical location (e.g. `treesight/storage/cosmos.py`).

### M2 — `_safe_origin()` vs `_cors_origin()`

- **Files:** `blueprints/billing.py` (L58), `blueprints/_helpers.py`
- **Category:** duplication
- **Detail:** Two CORS-origin-resolution functions with subtly different fallback
  behaviour. `_safe_origin()` falls back to hardcoded
  `"https://canopex.hrdcrprwn.com"` (magic number); `_cors_origin()` returns
  `""` on mismatch.

### M3 — `_transform_bbox` duplicated

- **Files:** `treesight/pipeline/fulfilment.py` (L337),
  `treesight/pipeline/enrichment/ndvi.py` (L320)
- **Category:** duplication
- **Detail:** Nearly identical CRS-transform logic. `_transform_bbox` takes
  `(bbox, src_crs, dst_crs)`, `_transform_bbox_4326` takes
  `(bbox, src_crs)` and hardcodes `EPSG:4326` as target. Factor into a shared
  geo utility.

### M4 — `EARTH_RADIUS_M` duplicated

- **Files:** `treesight/constants.py`, `treesight/pipeline/eudr.py` (L55)
- **Category:** duplication
- **Detail:** `_EARTH_RADIUS_M = 6_371_000.0` redeclared locally in `eudr.py`
  instead of importing `EARTH_RADIUS_M` from constants.

### M5 — `_polygon_to_feature` / `_multi_polygon_part_to_feature` near-identical

- **File:** `treesight/parsers/fiona_parser.py`
- **Category:** duplication
- **Detail:** Same body, only difference is how `coords` are sourced. Factor
  into a single helper taking coords as input.

### M6 — Double geodesic computation in `geo.py`

- **File:** `treesight/geo.py`
- **Category:** waste
- **Detail:** `_geodesic_area_ha()` and `_geodesic_perimeter_km()` each
  independently call `Geod(ellps="WGS84").polygon_area_perimeter()`. When
  `prepare_aoi()` calls both, the expensive geodesic computation runs twice.
  Merge into a single call returning both values.

### M7 — `_dedup_orders_by_scene()` never called in production

- **File:** `blueprints/pipeline/_helpers.py` (L246)
- **Category:** dead-code
- **Detail:** Tested (3 test cases in `test_pipeline.py`) but never called in
  any blueprint or orchestrator code. Scene deduplication is not wired into the
  pipeline.

### M8 — Inconsistent return schemas (acquisition/fulfilment)

- **Files:** `treesight/pipeline/acquisition.py`, `treesight/pipeline/fulfilment.py`
- **Category:** type-inconsistency
- **Detail:** `acquire_imagery()`, `acquire_composite()`, `download_imagery()`,
  `post_process_imagery()` all return `Model.model_dump()` on failure but a
  hand-built dict with different keys on success. Callers must handle two
  schemas.

### M9 — `DownloadResult.state` / `PostProcessResult.state` defaults to `""`

- **File:** `treesight/models/outcomes.py`
- **Category:** type-inconsistency
- **Detail:** Success path never sets `state` (defaults to `""`), failure sets
  `state="failed"`. Should be explicit (e.g. `"completed"` for success).

### M10 — `submit_batch_job` shell command construction

- **File:** `treesight/pipeline/batch.py`
- **Category:** smell
- **Detail:** Command line built via f-string interpolation with `claim_key`,
  `asset_url`, etc. If values contain spaces or shell metacharacters, the
  command breaks. Should use proper argument escaping or structured parameter
  passing.

### M11 — `_extract_red_channel_from_png` manual PNG decompression

- **File:** `treesight/pipeline/enrichment/ndvi.py`
- **Category:** smell
- **Detail:** ~80 lines of manual PNG decompression/defiltering. Only handles
  filter types 0–4 for 8-bit RGBA/RGB. Any PNG variant (interlaced, 16-bit,
  palette) silently returns an empty list.

### M12 — `run_enrichment()` god function

- **File:** `treesight/pipeline/enrichment/runner.py`
- **Category:** smell
- **Detail:** ~170 lines, 7 phases, 12+ parameters. Orchestrates weather,
  flood, fire, EUDR, mosaics, NDVI, change detection, AOI metrics, and manifest
  storage all in one function body.

### M13 — `ensure_container()` called on every upload

- **File:** `treesight/storage/client.py`
- **Category:** waste
- **Detail:** Every `upload_bytes()` / `upload_json()` triggers an HTTP HEAD to
  check container existence. For a pipeline processing hundreds of uploads to
  the same container, this is redundant. Cache known containers in a set.

### M14 — `billing_interest()` duplicates `contact_form()`

- **File:** `blueprints/billing.py` (L504–540)
- **Category:** duplication
- **Detail:** Same rate-limit → email/org validation → blob upload to
  `contact-submissions/` → `send_contact_notification()`. The main difference
  is auth and an extra field.

### M15 — `_user_id_from_customer()` O(n) blob scan

- **File:** `blueprints/billing.py`
- **Category:** smell
- **Detail:** Iterates over **every** subscription blob to find a matching
  `stripe_customer_id`. No caching. O(n) network I/O per blob for a growing
  user base.

### M16 — `_handle_event()` no error handling around `save_subscription()`

- **File:** `blueprints/billing.py`
- **Category:** error-handling
- **Detail:** Stripe webhook handler. If Cosmos/blob write fails, webhook
  returns 200 and Stripe won't retry. The event is silently lost.

### M17 — Manifest fetch logic duplicated

- **Files:** `blueprints/export.py` (`_fetch_manifest()`),
  `blueprints/pipeline/enrichment.py` (`timelapse_data()`)
- **Category:** duplication
- **Detail:** Same steps: get orchestrator status → extract output → find
  manifest key → download from blob. Two independent implementations.

### M18 — `SEASONAL_YEARS` hardcoded upper bound

- **File:** `treesight/pipeline/enrichment/frames.py` (L21)
- **Category:** magic-number
- **Detail:** `list(range(2018, 2027))` — will produce stale frame plans after
  2026 with no 2027+ data. Should compute from `date.today().year`.

### M19 — `consume_quota()` race condition

- **File:** `treesight/security/quota.py`
- **Category:** smell
- **Detail:** Not atomic — read → increment → write. Two concurrent requests
  can both read `used=4`, both write `used=5`. Needs optimistic concurrency
  (etag) or a Cosmos stored procedure.

### M20 — Flood error dict inflates event count

- **File:** `treesight/pipeline/enrichment/flood.py`
- **Category:** type-inconsistency
- **Detail:** On error, `fetch_ea_floods()` returns
  `[{"source": "ea_error", ...}]` — a list with one error dict. Callers count
  `len(events)` for the event count, so errors add 1 to the reported count.

### M21 — `_fetch_submission_records()` O(n) blob downloads

- **File:** `blueprints/pipeline/history.py`
- **Category:** smell
- **Detail:** Blob-storage fallback downloads **every** blob under the user's
  prefix, parses each as JSON, filters, sorts, and slices. Sequential network
  I/O per record.

### M22 — `_build_analysis_history_response()` sequential awaits

- **File:** `blueprints/pipeline/history.py`
- **Category:** waste
- **Detail:** Awaits durable client status for every record in a sequential
  `for` loop. Should use `asyncio.gather()` for parallelism.

### M23 — Contact form endpoint missing CORS headers

- **File:** `blueprints/contact.py`
- **Category:** smell
- **Detail:** `contact_form()` returns `status_code=204` for OPTIONS without
  CORS headers. Success/error responses also lack CORS headers. Cross-origin
  calls will fail.

### M24 — `_error_response()` duplicate in pipeline helpers

- **Files:** `blueprints/_helpers.py` (`error_response()`),
  `blueprints/pipeline/_helpers.py` (`_error_response()`)
- **Category:** duplication
- **Detail:** Two error-response builders with slightly different CORS handling.
  Some callers use one, some the other, some build inline.

### M25 — Analysis endpoint catch-all loses tracebacks

- **File:** `blueprints/analysis.py`
- **Category:** error-handling
- **Detail:** `frame_analysis()`, `timelapse_analysis()`, `eudr_assessment()`
  all have bare `except Exception` returning 500 with no logging. Production
  failures are invisible.

### M26 — `init_storage_docker.py` duplicates `_azurite.py` constants

- **File:** `scripts/init_storage_docker.py`
- **Category:** duplication
- **Detail:** Connection string, container list, host/port defaults are all
  redeclared instead of importing from `_azurite.py`. (May be intentional if
  the Docker script runs outside Python path, but undocumented.)

### M27 — EUDR cutoff fallback date wrong in PDF export

- **File:** `blueprints/export.py` (L399)
- **Category:** magic-number
- **Detail:** `cutoff = manifest.get("eudr_date_start", "2021-01-01")` — the
  EUDR cutoff is 31 December 2020, not 1 January 2021. The fallback is one day
  off. Should use `EUDR_CUTOFF_DATE` from constants.

### M28 — Test helper `_make_req()` duplicated 4×

- **Files:** `tests/test_analysis_submission_endpoints.py`,
  `tests/test_billing_endpoints.py`, `tests/test_health_endpoints.py`,
  `tests/test_submission_cors.py`
- **Category:** duplication
- **Detail:** Four independent request factory helpers with different signatures.
  Should be a shared `conftest.py` fixture.

### M29 — GeoTIFF builder duplicated in tests

- **Files:** `tests/test_fulfilment.py` (`_make_geotiff_bytes()`),
  `tests/test_change_detection.py` (`_make_ndvi_tiff()`)
- **Category:** duplication
- **Detail:** Both generate synthetic GeoTIFFs with rasterio using the same
  pattern. Extract to a shared `tests/_tiff_helpers.py`.

### M30 — Mock storage pattern repeated across test files

- **Files:** `tests/test_billing.py`, `tests/test_billing_endpoints.py`,
  `tests/test_feature_gate.py`, `tests/test_quota.py`, `tests/test_ingestion.py`
- **Category:** duplication
- **Detail:** Each file re-implements mock `BlobStorageClient` behaviour
  independently. A shared conftest fixture would reduce boilerplate.

---

## LOW Severity

### L1 — `__version__` hardcoded in `treesight/__init__.py`

Consider `importlib.metadata.version("treesight")` to stay in sync with
`pyproject.toml`.

### L2 — `_env_int` indirection in `config.py`

Builds a dict just to pass to `config_get_int`. Direct `int(os.getenv(...))` is
simpler.

### L3 — `int(float(val))` in `config_get_int` silently truncates

`"3.7"` becomes `3`. Could mask configuration errors.

### L4 — `send_contact_notification` subject line uses raw user input

Email header injection risk (newline characters). Body is HTML-escaped but
subject is not.

### L5 — `_centroid` simple mean may fall outside concave polygons

Documented limitation — acceptable for approximation.

### L6 — `httpx.Client` created without `with` block in multiple places

- `treesight/pipeline/enrichment/mosaic.py` (`register_mosaic`)
- `treesight/pipeline/enrichment/ndvi.py` (`fetch_ndvi_stat`)
- `treesight/pipeline/enrichment/runner.py` (`run_enrichment`)

Connection pools are never explicitly closed. Resource leak.

### L7 — `_call_ollama` sets timeout twice

`httpx.Client(timeout=30)` then `.post(timeout=150)`. Client-level timeout is
wasted.

### L8 — AI keys read at module import time

`treesight/ai/client.py`, `treesight/pipeline/enrichment/fire.py` — API keys
read from env at import time, never refreshed. Key rotation requires process
restart.

### L9 — `WorkflowState` has both `COMPLETED` and `SUCCESS`

Callers must check both; `is_success` handles it, but the dual naming is
confusing.

### L10 — `_parse_json_response` silently returns `None` on malformed LLM output

No logging when regex-extracted JSON fails to parse.

### L11 — `_xml_escape` in `eudr.py` reimplements `html.escape()`

`html.escape(text, quote=True)` from stdlib does the same thing.

### L12 — `_NAME_KEYS` case inconsistency in `fiona_parser.py`

Set includes both `"Description"` and `"description"`, but `_extract_name_description`
uses `.get("Name")` / `.get("name")` — different capitalisation strategy.

### L13 — `_season_window` hardcodes Feb end to 28

Misses Feb 29 in leap years.

### L14 — `RATE_LIMIT_DEMO_MAX = 3` parallels `DEMO_TIER_RUN_LIMIT = 3`

Same value for different concepts — document or unify.

### L15 — Tier limits split across `treesight/constants.py` and `treesight/security/billing.py`

Some tier limits in constants, some in billing module. All should live in one
place.

### L16 — `auth_enabled._warned` monkey-patches function object

Use a module-level `_warned` sentinel instead.

### L17 — JWKS cache invalidation thundering herd

`validate_token` clears entire JWKS cache on `kid` not found. Under load with
bad tokens, causes repeated JWKS fetches.

### L18 — `TableReplayStore._table` property recreates client on every access

Should cache the table client after first creation.

### L19 — `_bbox_height_km` / `_bbox_width_km` use magic `111.32`

Should reference `METRES_PER_DEGREE_LATITUDE / 1000` from constants.

### L20 — `parse_kml_from_blob` silent fallback from Fiona to lxml

No logging when Fiona parser fails. Makes debugging parser issues difficult.

### L21 — `NAIP_SUMMERS` requires manual update

Hardcoded set of known NAIP acquisition years. New summers need manual addition.

### L22 — `register_mosaic` returns `None` on error

Callers append `None` to lists and scatter `None` checks throughout.

### L23 — `import os` inside `check_wdpa_overlap` (eudr.py)

Inconsistent with module-level import convention used elsewhere.

### L24 — `json` imported inside method bodies in `storage/client.py`

`download_json` and `upload_json` both do `import json` inline. Should be
top-level.

### L25 — `reset_client` in `cosmos.py` calls `__exit__` directly

`CosmosClient` should be closed properly (`.close()` or discard reference).

### L26 — Dead OPTIONS check inside `@require_auth` decorated endpoints

`billing_checkout()`, `billing_portal()`, `billing_status()`,
`billing_emulation()` check `req.method == "OPTIONS"` inside the function body,
but `@require_auth` already handles OPTIONS and returns before the function
runs.

### L27 — `_collect_enrichment_coords()` only uses first AOI's bbox fallback

If no `exterior_coords` exist, takes the first AOI's bbox and `break`s. All
other AOIs silently ignored.

### L28 — `timelapse_data()` missing OPTIONS handling

Unlike all other GET endpoints, no preflight handling. CORS preflight will fail.

### L29 — `_build_csv()` O(n×m) weather aggregation

For each frame, iterates all daily weather entries. Pre-grouping would be more
efficient.

### L30 — Hardcoded `"planetary_computer"` as default provider

Appears in at least 4 locations. Should be a `DEFAULT_PROVIDER` constant.

### L31 — `_submit_demo_request()` and `_submit_analysis_request()` 60% overlap

Could share a common `_submit_kml()` helper.

### L32 — `write_metadata()` silently suppresses all exceptions on KML download

`contextlib.suppress(Exception)` means storage misconfigurations are invisible.

### L33 — Batch polling 60-second timer is a magic number

`orchestrator.py` hardcodes the polling interval. Should be configurable.

### L34 — `convert_coordinates()` acknowledged too complex (`# noqa: C901`)

~60 lines of validation + conversion. Should be split.

### L35 — `_calculate_trends()` reinvents `statistics.stdev()`

Manual variance/std-dev computation instead of using stdlib.

### L36 — Inconsistent CORS `req=req` usage in `error_response()` calls

Some endpoints pass it (errors include CORS headers), some don't (errors are
opaque to browsers).

### L37 — Hardcoded URLs in `scripts/_setup_stripe.py`

Privacy policy, terms of service, portal return URLs. Should be CLI args.

### L38 — Hardcoded redirect URIs in `scripts/_register_ciam_app.py`

Localhost, Azure SWA hostname, custom domain. Should be parameterised.

### L39 — OAuth permission GUIDs uncommented in `scripts/_register_ciam_app.py`

`resourceAccess` GUIDs with no comments explaining what each permission is.

### L40 — `tests/test_dev_server.py` only tests class structure

No tests for the proxy logic, CORS, path normalisation, or traversal prevention
— which is security-sensitive code.

### L41 — Allowed origin strings repeated as literals across test files

`"https://canopex.hrdcrprwn.com"` appears in at least 3 test files. Should
reference a shared constant.

---

## Summary of Top Refactoring Opportunities

Roughly ordered by impact-to-effort ratio:

1. **Extract `_cosmos_available()`** to one location — trivial, eliminates 3
   duplicates (M1)
2. **Unify CORS origin resolution** — `_safe_origin()` and `_cors_origin()` →
   one function (M2)
3. **Extract shared `_transform_bbox()`** to `treesight/geo.py` (M3)
4. **Move test stubs out of production code** — `StubProvider` + test fixtures
   (H1)
5. **Remove or gate `demo_submit()`** — confirm dead, remove (H2)
6. **Extract `scripts/_graph.py`** — eliminate 4 copies (H3)
7. **Extract Cosmos/blob fallback helper** — eliminate 5 repetitions (H5)
8. **Fix `SEASONAL_YEARS`** — compute from current year (M18)
9. **Fix EUDR cutoff fallback** — `"2021-01-01"` → `EUDR_CUTOFF_DATE` (M27)
10. **Merge geodesic area + perimeter** into one call (M6)
11. **Cache `ensure_container()` results** (M13)
12. **Add logging to analysis catch-all** (M25)
13. **Fix `consume_quota()` race condition** with etag (M19)
14. **Close `httpx.Client` instances properly** (L6)

---

*Review performed by automated analysis. Each finding should be validated
before acting on it.*
