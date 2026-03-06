# Modern Python Patterns & Libraries

This document showcases modern Python 3.12+ features and clever library techniques that improve code quality, readability, and maintainability.

## Applied Improvements

### 1. `itertools.batched()` (Python 3.12+)

**Before:**

```python
for batch_start in range(0, len(items), batch_size):
    batch = items[batch_start : batch_start + batch_size]
    process(batch)
```

**After:**

```python
from itertools import batched

for batch in batched(items, batch_size):
    process(list(batch))
```

**Benefits:**

- No slice arithmetic (eliminates off-by-one errors)
- More Pythonic and declarative
- Standard library solution

### 2. `operator` module for Functional Programming

**Before:**

```python
aoi_by_feature = {
    str(a.get("feature_name", "")): a
    for a in aois
    if isinstance(a, dict) and a.get("feature_name")
}
```

**After:**

```python
from operator import itemgetter

get_feature_name = itemgetter("feature_name")
aoi_by_feature = {
    str(get_feature_name(a)): a
    for a in aois
    if isinstance(a, dict) and a.get("feature_name")
}
```

**Benefits:**

- More declarative intent
- Reusable field accessors
- Better for map/filter operations

### 3. Pattern Matching with `match`/`case` (Python 3.10+)

**Before:**

```python
if state == "ready" or state == "completed":
    return "success"
elif state == "failed":
    return "failed"
else:
    return "unknown"
```

**After:**

```python
match result.get("state"):
    case "ready" | "completed" | "success":
        return "success"
    case "failed" | "error":
        return "failed"
    case _:
        return "unknown"
```

**Benefits:**

- More maintainable
- Exhaustiveness checking
- Or-patterns with `|`
- Guard clauses: `case x if x > 0:`

### 4. `functools.partial` for Function Composition

**Before:**

```python
failed_count = sum(1 for d in downloads if d.get("state") == "failed")
pp_failed = sum(1 for p in post_process if p.get("state") == "failed")
clipped = sum(1 for p in post_process if p.get("clipped"))
```

**After:**

```python
from functools import partial

def count_by_field(results, field, value):
    return sum(1 for r in results if r.get(field) == value)

count_failed = partial(count_by_field, field="state", value="failed")
count_true = partial(count_by_field, value=True)

failed_count = count_failed(downloads)
pp_failed = count_failed(post_process)
clipped = count_true(post_process, field="clipped")
```

**Benefits:**

- DRY principle
- Reusable specialized functions
- Cleaner configuration

## Additional Opportunities

### 5. Pydantic Models (Already installed!)

**Current:** TypedDict + manual validation

```python
class OrchestrationInput(TypedDict):
    blob_url: str
    container_name: str
    blob_name: str

def validate_payload(raw: dict, schema: type, *, activity: str):
    required = REQUIRED_KEYS[schema]
    missing = required - raw.keys()
    if missing:
        raise ContractError(f"Missing: {missing}")
```

**Could be:** Pydantic with automatic validation

```python
from pydantic import BaseModel, Field, HttpUrl

class OrchestrationInput(BaseModel):
    blob_url: HttpUrl  # Auto-validates URL format
    container_name: str = Field(min_length=1, pattern=r'^[a-z0-9-]+$')
    blob_name: str = Field(min_length=1)
    content_length: int = Field(ge=0)

    model_config = {"str_strip_whitespace": True}

# Usage - auto validates and gives detailed errors
try:
    input_data = OrchestrationInput(**raw_dict)
except ValidationError as e:
    # Rich error details: which field, what's wrong, how to fix
    logger.error(e.json())
```

**Benefits:**

- Automatic type coercion
- Rich validation (regex, ranges, URLs, UUIDs)
- Detailed error messages
- JSON schema generation
- `.model_dump()` for serialization
- `.model_validate()` for deserialization

### 6. `more-itertools` Library

```python
from more_itertools import chunked, partition, first

# Chunked iteration (like batched but more features)
for batch in chunked(items, 10):
    process(batch)

# Partition by condition
failed, succeeded = partition(lambda r: r["state"] == "failed", results)

# First matching item (or default)
ready = first((r for r in results if r["state"] == "ready"), default=None)
```

### 7. Structural Pattern Matching for Complex Types

```python
match result:
    case {"state": "ready", "order_id": order_id, **rest}:
        process_ready(order_id, rest)
    case {"state": "failed", "error": error_msg}:
        handle_error(error_msg)
    case {"state": state, **rest} if state not in KNOWN_STATES:
        logger.warning(f"Unknown state: {state}")
    case _:
        handle_unexpected(result)
```

### 8. `contextlib` for Resource Management

```python
from contextlib import contextmanager, suppress

@contextmanager
def blob_download_context(client, container, blob):
    """Context manager for safe blob operations."""
    blob_client = client.get_blob_client(container, blob)
    try:
        data = blob_client.download_blob()
        yield data
    finally:
        # Cleanup if needed
        pass

# Usage
with blob_download_context(client, "kml", "test.kml") as blob_data:
    content = blob_data.readall()

# Suppress expected exceptions
with suppress(KeyError):
    optional_field = data["might_not_exist"]
```

### 9. Typed `NamedTuple` for Immutable Data

**Instead of:**

```python
def parse_bbox(coords: list) -> dict:
    return {
        "min_x": coords[0],
        "min_y": coords[1],
        "max_x": coords[2],
        "max_y": coords[3],
    }
```

**Use:**

```python
from typing import NamedTuple

class BBox(NamedTuple):
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

bbox = BBox(0.0, 0.0, 10.0, 5.0)
print(bbox.width)  # 10.0
```

### 10. `enum.StrEnum` for State Constants (Python 3.11+)

```python from enum import StrEnum

class WorkflowState(StrEnum):
    READY = "ready"
    PENDING = "pending"
    FAILED = "failed"
    COMPLETED = "completed"

# Usage - auto-string conversion
state = WorkflowState.READY
assert state == "ready"  # True
assert state.value == "ready"  # True

# Pattern matching works beautifully
match state:
    case WorkflowState.READY:
        process()
    case WorkflowState.FAILED:
        handle_error()
```

### 11. `functools.cache` for Memoization (Python 3.9+)

```python
from functools import cache, lru_cache

@cache  # Unlimited cache
def get_crs_transform(source_crs: str, target_crs: str):
    """Expensive CRS transformation - cache it."""
    return pyproj.Transformer.from_crs(source_crs, target_crs)

@lru_cache(maxsize=128)  # LRU cache with size limit
def parse_iso_date(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str)
```

### 12. Walrus Operator `:=` for Cleaner Code (Python 3.8+)

**Before:**

```python
state = result.get("state")
if state == "ready":
    process(state)
```

**After:**

```python
if (state := result.get("state")) == "ready":
    process(state)
```

**Better example:**

```python
# Avoid repeated calculations
if (area := calculate_area(polygon)) > 1000:
    logger.warning(f"Large area: {area} ha")
    handle_large_area(area)
```

## Implementation Priority

1. **High Impact, Easy Win:**
   - ✅ `itertools.batched()` - Already applied
   - ✅ `operator module` - Already applied
   - ✅ Pattern matching - Already applied
   - ✅ `functools.partial` - Already applied
   - 🔲 Pydantic models (replace TypedDict + manual validation)

2. **Medium Impact:**
   - 🔲 `enum.StrEnum` for state constants
   - 🔲 `more-itertools` for advanced iteration
   - 🔲 `functools.cache` for expensive operations

3. **Nice to Have:**
   - 🔲 NamedTuple for immutable data structures
   - 🔲 Walrus operator for cleaner conditionals
   - 🔲 Context managers for resource safety

## Performance Considerations

- **`itertools.batched()`**: O(n) memory for tuple conversion, but cleaner code
- **`operator` functions**: Slight overhead vs inline lambda, but more reusable
- **Pattern matching**: Compiled to efficient lookup tables by CPython
- **Pydantic**: Validation overhead (~5-10% slower than `dict`), but safer
- **`functools.cache`**: Pure speed win for repeated expensive calls

## References

- [Python 3.12 What's New](https://docs.python.org/3/whatsnew/3.12.html)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [more-itertools on PyPI](https://pypi.org/project/more-itertools/)
- [Real Python: Pattern Matching](https://realpython.com/python310-new-features/#structural-pattern-matching)

## Next Steps

Consider migrating TypedDict contracts to Pydantic models for:

- Richer validation (field constraints, custom validators)
- Automatic coercion (strings → URLs, dates, etc.)
- Better error messages for API consumers
- JSON Schema generation for documentation
- Compatibility with FastAPI/Azure Functions OpenAPI specs
