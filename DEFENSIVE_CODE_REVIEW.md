# Defensive Code Review — Margaret Hamilton Standard

Date: 2026-02-18  
Scope: runtime Python code (`function_app.py`, `kml_satellite/**`) + quality signals from tests/lint/types.

## Executive Summary

- Runtime files reviewed: 22
- Runtime functions reviewed: 108
- Unit tests: `555 passed`
- Lint (`ruff`): clean
- Type checking (`pyright`): clean
- No infinite-loop risk found in runtime code paths.
- Main risks are placeholder implementation, broad exception handling in critical paths, and dynamic `dict[str, Any]` boundaries.

## Validation Signals Run

- `uv sync --all-extras`
- `uv run ruff check .` → all checks passed
- `uv run pyright` → 0 errors
- `uv run pytest tests/unit -q` → 555 passed

## File-by-File Review (Runtime)

## 1) function_app.py

Status: **Needs hardening**

### Functions reviewed

- `kml_blob_trigger` — **Issue**: catches broad `Exception` on orchestration start. Good logging, but exception taxonomy is too broad for strict defensive standards.
- `kml_processing_orchestrator` — acceptable thin wrapper.
- `orchestrator_status` — acceptable.
- Activity wrappers (`parse_kml_activity`, `prepare_aoi_activity`, `write_metadata_activity`, `acquire_imagery_activity`, `poll_order_activity`, `download_imagery_activity`, `post_process_imagery_activity`) — generally strong boundary checks.

### Findings

- TODO placeholder exists for compositing/delivery activities.

## 2) kml_satellite/core/config.py

Status: **Mostly solid, one high-value improvement**

### Functions reviewed

- `PipelineConfig.from_env` — good centralization and immutability (`frozen=True`).

### Findings

- No explicit validation of env-derived numeric ranges at config load time (e.g., `AOI_BUFFER_M`, cloud cover bounds). Invalid values can fail later rather than at startup.

## 3) kml_satellite/models/blob_event.py

Status: **Solid**

### Functions reviewed

- `to_dict`, `from_event_grid_event`, `_parse_blob_url`

### Findings

- Good defensive URL parsing with Azure + Azurite support.
- Good fallback behavior for malformed `contentLength`.

## 4) kml_satellite/models/feature.py

Status: **Good, can be stricter**

### Functions reviewed

- `to_dict`, `from_dict`, `vertex_count`, `has_holes`

### Findings

- `from_dict` coerces values heavily (`str(...)`, `int(...)`), which is resilient but can hide upstream schema bugs.

## 5) kml_satellite/models/aoi.py

Status: **Good, can be stricter**

### Functions reviewed

- `to_dict`, `from_dict`

### Findings

- Similar coercion tradeoff as `Feature.from_dict`.

## 6) kml_satellite/models/imagery.py

Status: **Strong model design**

### Functions/classes reviewed

- `OrderState`, `ImageryFilters`, `SearchResult`, `OrderId`, `OrderStatus`, `BlobReference`, `ProviderConfig`

### Findings

- Good immutability and explicit-unit design.
- Could add invariant validation (cloud cover, angles, resolution order).

## 7) kml_satellite/models/metadata.py

Status: **Strong**

### Functions reviewed

- `AOIMetadataRecord.from_aoi`, `to_json`, `to_dict`, `_extract_orchard_name`

### Findings

- Good type-safe schema and deterministic metadata structure.
- Timestamp default uses local timezone (`astimezone`) rather than explicit UTC; acceptable but may reduce cross-region determinism.

## 8) kml_satellite/providers/base.py

Status: **Strong**

### Functions reviewed

- `ImageryProvider` contract + exception hierarchy

### Findings

- Clean abstraction and retryability semantics.

## 9) kml_satellite/providers/factory.py

Status: **Strong**

### Functions reviewed

- `_register_builtin_adapters`, `_ensure_registry`, `register_provider`, `get_provider`, `list_providers`

### Findings

- Good lazy loading and registry logic.

## 10) kml_satellite/providers/skywatch.py

Status: **Critical gap (production-readiness)**

### Functions reviewed

- `search`, `order`, `poll`, `download`

### Findings

- All methods raise `NotImplementedError`.
- This directly violates your “no placeholders in working code” requirement for the production adapter path.

## 11) kml_satellite/providers/planetary_computer.py

Status: **Working, needs defensive tightening**

### Functions reviewed

- `search` — broad catch around STAC call.
- `order`, `poll` — acceptable for STAC semantics.
- `download` — broad catches around URL resolve/download.
- `_item_to_search_result` — broad catch; uses `Any`-typed STAC item.
- `_resolve_asset_url`, `_download_asset`, `_aoi_to_bbox`, `_build_date_range`, `_resolve_best_asset_url`, `_build_blob_path`

### Findings

- Broad exceptions reduce precision of failure handling.
- `Any` usage is acceptable at third-party boundary but can be narrowed via Protocol/TypedDict wrappers.
- In-memory `_orders` cache is unbounded (risk if adapter lifetime changes to long-lived process).

## 12) kml_satellite/activities/parse_kml.py

Status: **Strong defensive geometry implementation**

### Functions reviewed

- `parse_kml_file` — broad fallback catch for Fiona failure.
- `_validate_xml`, `_validate_coordinates`, `_validate_polygon_ring`
- `_parse_with_fiona`, `_try_fiona_polygon`, `_extract_crs_from_fiona`, `_fiona_polygon_to_feature`
- `_parse_with_lxml`, `_parse_polygon_lxml` (`Any` boundary), `_parse_coordinates_text`, `_extract_extended_data_lxml` (`Any` boundary)
- `_validate_shapely_geometry` — broad catch around polygon construction.
- `_coords_to_tuples`, `_extract_metadata_from_props`

### Findings

- Overall quality is high and defensive.
- Some broad catches and `Any` at parser-library boundaries; largely pragmatic but can be tightened.

## 13) kml_satellite/activities/prepare_aoi.py

Status: **Strong**

### Functions reviewed

- `prepare_aoi`, `compute_bbox`, `compute_buffered_bbox`, `compute_geodesic_area_ha`, `compute_centroid`, `_validate_coords`, `_get_utm_crs`

### Findings

- Strong defensive checks and metric-buffer correctness.
- `compute_centroid` doesn’t explicitly gate invalid polygon topology before Shapely centroid call (Shapely generally tolerates but explicit validity checks could align more strictly with policy).

## 14) kml_satellite/activities/acquire_imagery.py

Status: **Good with typing boundary tradeoffs**

### Functions reviewed

- `acquire_imagery`, `_build_provider_config`, `_build_filters`

### Findings

- Good fail-loud behavior and retry propagation.
- Uses dynamic dict boundaries heavily (`dict[str, Any]`) due Durable payloads; can be improved with input schema objects.

## 15) kml_satellite/activities/poll_order.py

Status: **Good**

### Functions reviewed

- `poll_order`

### Findings

- Strong validation and terminal-state signaling.

## 16) kml_satellite/activities/download_imagery.py

Status: **Good, but has TODO placeholders in validation path**

### Functions reviewed

- `download_imagery`, `_download_with_retry`, `_validate_download`, `_build_provider_config`, `_parse_timestamp`

### Findings

- TODO: rasterio-based content validation is not implemented yet.
- TODO: adapter-returned destination path wiring is still deferred.
- Current behavior is operational but not fully “no placeholders” compliant.

## 17) kml_satellite/activities/post_process_imagery.py

Status: **Robust fallback behavior, but broad catches are heavy**

### Functions reviewed

- `post_process_imagery`, `_process_raster`, `_get_raster_crs`, `_reproject_raster`, `_clip_raster`, `_build_geojson_polygon`, `_parse_timestamp`

### Findings

- Graceful degradation behavior is good.
- Multiple broad catches make root-cause categorization and retry policy less precise.
- Uses `Any` for rasterio module injection; practical for testability, but can be narrowed.

## 18) kml_satellite/activities/write_metadata.py

Status: **Good**

### Functions reviewed

- `write_metadata`, `_upload_metadata`

### Findings

- Broad catch in upload wrapper; can be narrowed to Azure SDK exceptions.

## 19) kml_satellite/orchestrators/kml_pipeline.py

Status: **Functionally strong orchestration, hardening needed**

### Functions reviewed

- `orchestrator_function` — 2 broad catches (download/post-process stages).
- `_poll_until_ready` — bounded loop with deadline (safe, no infinite loop risk); broad catch around poll activity.

### Findings

- Loop structure is safe (deadline + retries + timers).
- Broad exception handling works operationally but blurs transient/permanent classification.
- Uses mutable accumulators (`imagery_outcomes`, `download_results`, `post_process_results`); acceptable in orchestrator but less functional style.

## 20) kml_satellite/utils/blob_paths.py

Status: **Strong and idiomatic**

### Functions reviewed

- `sanitise_slug`, `build_kml_archive_path`, `build_metadata_path`, `build_imagery_path`, `build_clipped_imagery_path`

### Findings

- Deterministic and explicit path generation is good.

## Architectural Review (2026-02-19)

### 1) Orchestrator Scalability & Data Flow

**Risk: High (when scaling)**

- **Issue**: The orchestrator (`kml_pipeline.py`) keeps full `features` and `aois` lists in memory and passes them as activity inputs.
- **Impact**: For complex KMLs with thousands of polygons, the orchestration history payload may exceed the Azure Storage message size limit (64KB - 1MB depending on storage provider), causing `OrchestrationFailure`.
- **Recommendation**: Store large intermediate datasets (like the list of features or AOIs) in Blob Storage and pass only the blob reference (URI/path) to activities. Activities should read/write data from/to Blob Storage directly.

### 2) Configuration Management

**Risk: Medium (maintainability/consistency)**

- **Issue**: `PipelineConfig` in `core/config.py` is defined but **not effectively used** in the runtime path. Activities like `acquire_imagery` and the orchestrator rely on ad-hoc `os.getenv` calls or localized defaults (e.g., `_build_filters`), duplicating configuration logic.
- **Impact**: Changing a default value in `config.py` will have no effect on the running system, leading to confusion and potential configuration drift between environments.
- **Recommendation**: Instantiate `PipelineConfig` once (e.g., in `function_app.py` or a shared dependency provider upon startup) and pass relevant config objects explicitly to activities, or have activities use `PipelineConfig.from_env()` consistently.

### 3) Placeholder Code in Production Path

**Risk: High (compliance)**

- **Issue**: `SkyWatchAdapter` methods raise `NotImplementedError`.
- **Impact**: If `IMAGERY_PROVIDER` is set to `skywatch` (or passed in payload), the pipeline will crash at runtime. This violates the "no placeholders in production code" rule unless guarded by a feature flag that prevents its selection.
- **Issue**: `download_imagery` has TODOs for content validation (`rasterio`) and final path wiring. The code calculates a destination path but doesn't actually place the file there (provider adapter implementation details leak here).

### 4) Dependency Injection Scope

**Risk: Low (operational)**

- **Issue**: `get_provider` is called inside activities, creating new adapter instances for every single activity execution.
- **Impact**: While acceptable for stateless Azure Functions, this prevents connection pooling or shared state (like authentication tokens) optimization if the provider client supports it.
- **Recommendation**: Consider caching the provider instance or its underlying session (e.g., `requests.Session`) globally or on the module level if thread-safety permits, to reduce handshake overhead.

## Runtime Function-Level Issues Detected (Automated + Manual)

1. `function_app.py::kml_blob_trigger` — broad catch.
2. `kml_satellite/activities/parse_kml.py::parse_kml_file` — broad catch.
3. `kml_satellite/activities/parse_kml.py::_parse_polygon_lxml` — `Any` boundary.
4. `kml_satellite/activities/parse_kml.py::_extract_extended_data_lxml` — `Any` boundary.
5. `kml_satellite/activities/parse_kml.py::_validate_shapely_geometry` — broad catch.
6. `kml_satellite/activities/post_process_imagery.py::_process_raster` — broad catches (2).
7. `kml_satellite/activities/post_process_imagery.py::_get_raster_crs` — `Any` + broad catch.
8. `kml_satellite/activities/post_process_imagery.py::_reproject_raster` — `Any` + broad catch.
9. `kml_satellite/activities/post_process_imagery.py::_clip_raster` — `Any` + broad catch.
10. `kml_satellite/activities/write_metadata.py::_upload_metadata` — broad catch.
11. `kml_satellite/orchestrators/kml_pipeline.py::orchestrator_function` — broad catches (2).
12. `kml_satellite/orchestrators/kml_pipeline.py::_poll_until_ready` — broad catch.
13. `kml_satellite/providers/planetary_computer.py::search` — broad catch.
14. `kml_satellite/providers/planetary_computer.py::download` — broad catches (2).
15. `kml_satellite/providers/planetary_computer.py::_item_to_search_result` — `Any` + broad catch.
16. `kml_satellite/providers/planetary_computer.py::_resolve_best_asset_url` — `Any` boundary.
17. `kml_satellite/providers/skywatch.py::search` — `NotImplementedError` placeholder.
18. `kml_satellite/providers/skywatch.py::order` — `NotImplementedError` placeholder.
19. `kml_satellite/providers/skywatch.py::poll` — `NotImplementedError` placeholder.
20. `kml_satellite/providers/skywatch.py::download` — `NotImplementedError` placeholder.

## Idiomatic / Functional-Style Gaps

- Heavy `dict[str, Any]` payloads across activity boundaries reduce compile-time guarantees.
- Broad exception catches in orchestration/provider flows trade simplicity for reduced diagnostic precision.
- Some startup validation is deferred to runtime path usage (rather than fail-fast at config load).
- Placeholder implementation (`SkyWatchAdapter`) remains in production strategy path.

## Prioritized Remediation Plan (Updated 2026-02-19)

### P0 (must fix for "no placeholders" / correctness)

1. **Configuration**: Wire `PipelineConfig.from_env()` into actual usage across activities (e.g., as default args) or consistently rely on it. Currently, it is dead code.
2. **Provider Implementation**: Either implement `SkyWatchAdapter` contract methods or add explicit logic in `factory.py` / `acquire_imagery` to reject `IMAGERY_PROVIDER=skywatch` until implemented.
3. **Data Path**: Replace TODO placeholders in `download_imagery` with actual validation logic or remove the TODO if out of scope. Wire the calculated blob path to the adapter or move the blob post-download.

### P1 (defensive hardening & scalability)

1. **Orchestrator Payload**: Evaluate if passing full `features` and `aois` lists via Durable Functions history exceeds size limits for realistic KML inputs. Consider passing Blob URI references instead for large collections (Tracked in **Issue #62**).
2. **Exception Handling**: Replace broad `exception Exception` catches with specific exception families in:
   - orchestration activity calls,
   - provider STAC/download operations,
   - metadata upload path.
3. **Typing**: Introduce explicit input schemas (TypedDict/Pydantic) for activity payloads instead of free-form dicts (`start_orchestration` -> `features` -> `aois`).

### P2 (idiomatic quality improvements)

1. **Dependency Injection**: Cache `ImageryProvider` instances or sessions at module level if thread-safe to improve performance (connection pooling) (Tracked in **Issue #63**).
2. **Narrow Types**: Narrow `Any` at third-party boundaries using lightweight protocols/wrapper DTOs.
3. **Model Validation**: Add invariant validators to imagery models (`ImageryFilters`, `SearchResult`).
4. **Timestamps**: Standardize UTC timestamps for deterministic cross-region metadata output.

## Bottom Line

- The codebase is in a **good operational state** (tests/lint/types are green).
- It is **not yet fully compliant** with your strict "no placeholders / Hamilton defensive completeness" bar because of unfinished SkyWatch adapter, **unused configuration code**, and deferred TODOs in imagery download validation/wiring.
- **Architectural Scalability Risk**: The current orchestrator implementation may hit message size limits with large KML inputs.
- With the P0/P1 actions above, this can become production-grade and fully aligned with your stated principles.
