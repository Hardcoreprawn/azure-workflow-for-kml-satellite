# pystac_client and pystac API Contract

**Purpose**: Document the exact API surface we depend on from `pystac_client` and `pystac` libraries.

**Why this exists**: If these third-party libraries change their API in breaking ways, this document identifies what will break in our code.

**Based on**: Actual usage in [kml_satellite/providers/planetary_computer.py](../kml_satellite/providers/planetary_computer.py)

---

## pystac.Item Structure

We access these attributes from `pystac.Item` objects returned by search results:

### Direct Attributes

```python
item.id: str
```

Scene identifier (e.g., `"S2B_T10TEM_20260115T183909_L2A"`)

**Used in**: `_item_to_search_result()` line 329

---

```python
item.properties: dict[str, Any] | None
```

STAC metadata dictionary. **May be None** - we defensively handle this:

```python
properties = item.properties or {}
```

**Used in**: `_item_to_search_result()` line 328

---

```python
item.bbox: list[float] | None
```

Bounding box `[min_lon, min_lat, max_lon, max_lat]`. **May be None** - we defensively handle this:

```python
bbox_raw = item.bbox or [0.0, 0.0, 0.0, 0.0]
```

**Used in**: `_item_to_search_result()` line 348

---

```python
item.assets: dict[str, pystac.Asset]
```

Dictionary of downloadable assets with keys like `"visual"`, `"B04"`, `"rendered_preview"`.

**Used in**: `_resolve_best_asset_url()` line 460

---

```python
item.collection_id: str | None
```

Collection identifier. **May be None** for standalone items. We use `getattr()` with fallback:

```python
collection = getattr(item, "collection_id", "")
```

**Used in**: `_item_to_search_result()` line 368

---

### Properties Dictionary Keys

All accessed via `.get()` with fallbacks to handle missing keys:

| Key | Type | Description | Used in Line |
| ----- | ------ | ------------- | -------------- |
| `"datetime"` | `str` | ISO 8601 timestamp (e.g., `"2026-01-15T18:39:09Z"`) | 332 |
| `"eo:cloud_cover"` | `float` | Cloud cover percentage (0.0 to 100.0) | 339 |
| `"gsd"` | `float` | Ground sample distance in metres (e.g., 10.0) | 342 |
| `"proj:epsg"` | `int` | EPSG CRS code (e.g., 32610 for UTM Zone 10N) | 345 |
| `"platform"` | `str` | Satellite platform (e.g., `"sentinel-2b"`) | 366 |
| `"constellation"` | `str` | Constellation name (e.g., `"sentinel-2"`) | 367 |

**Example defensive pattern** (PID 7.4.3):

```python
properties = item.properties or {}
cloud_cover = float(properties.get("eo:cloud_cover", 0.0))
```

---

### Asset Structure

We prefer assets in this priority order:

1. `assets["visual"]` - RGB visual composite (preferred)
2. `assets["B04"]` - Red band (fallback #1)
3. `assets["rendered_preview"]` - Pre-rendered preview (fallback #2)

Each asset has:

```python
asset.href: str
```

Download URL for the asset (e.g., `"https://planetarycomputer.microsoft.com/..."`)

**Used in**: `_resolve_best_asset_url()` lines 461-467

---

## pystac_client.Client API

### Opening a Catalog

```python
pystac_client.Client.open(url: str) -> pystac_client.Client
```

**Used in**: `search()` line 176  
**URL**: `"https://planetarycomputer.microsoft.com/api/stac/v1"`

---

### Searching the Catalog

```python
client.search(**kwargs) -> pystac_client.ItemSearch
```

**Parameters we use**:

- `bbox: tuple[float, float, float, float]` - Bounding box
- `collections: list[str]` - Collection identifiers (e.g., `["sentinel-2-l2a"]`)
- `datetime: str` - Date range (e.g., `"2025-01-01/2025-12-31"`)
- `max_items: int` - Maximum results to return
- `ids: list[str]` - Specific scene IDs to retrieve

**Used in**:

- `search()` line 188 (bbox search)
- `_resolve_asset_url()` line 389 (search by ID)

**CRITICAL**: Planetary Computer API requires `collections` parameter **even when searching by scene ID** (Issue #126)

---

### Getting Search Results

```python
search.items() -> Iterator[pystac.Item]
```

Returns an iterator of `pystac.Item` objects matching the search criteria.

**Used in**: `search()` line 194

---

## Error Handling

pystac_client does **NOT** handle network errors. We must catch:

- `pystac_client.exceptions.APIError` - API returns 400/500 errors
- `httpx.HTTPStatusError` - HTTP protocol errors
- `httpx.RequestError` - Network connection failures
- `TimeoutError` - Request timeout
- `ConnectionError` - Network unavailable

**Used in**: `search()` line 195-238 (try/except blocks)

---

## References

- **Production Code**: [kml_satellite/providers/planetary_computer.py](../kml_satellite/providers/planetary_computer.py)
- **Mock Tests**: [tests/unit/test_planetary_computer.py](../tests/unit/test_planetary_computer.py)
  - `_make_stac_item()` helper creates mock STAC items for testing
  - `_mock_stac_search()` patches `pystac_client.Client.open()`
- **PID References**:
  - PID 7.4.3 (Defensive programming at boundaries)
  - PID 7.4.7 (Contract test tier)

---

## Change History

| Date | Change | Reason |
| ------ | -------- | -------- |
| 2026-03-05 | Initial documentation | Issue #126 revealed lack of API contract documentation |
| 2026-03-05 | Added `collections` requirement for ID search | Planetary Computer API now requires this parameter |

---

**Last Updated**: 2026-03-05  
**Verified Against**: pystac-client 0.8.0
