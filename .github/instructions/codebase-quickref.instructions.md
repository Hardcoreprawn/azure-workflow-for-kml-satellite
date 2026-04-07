---
description: "Always-on codebase quick-reference. Use for project structure, key commands, environment setup, test conventions, and module layout. Loaded automatically for all files."
name: "Codebase Quick Reference"
applyTo: "**"
---
# Codebase Quick Reference

## Commands

| Task | Command |
|------|---------|
| Install deps | `make setup` (uses `uv sync --all-extras`) |
| Run all tests | `make test` → `python -m pytest` |
| Run one test file | `python -m pytest tests/test_parsers.py -x -q` |
| Run one test | `python -m pytest tests/test_parsers.py::test_rejects_zip_bomb -x` |
| Lint | `make lint` → `ruff check` |
| Format | `make fmt` → `ruff format` |
| Lint + test | `make check` |
| Start local stack | `make dev-init` then `make dev-func` + `make dev-web` in separate terminals |
| Upload sample KML | `make test-upload` |

## Project Layout

```text
function_app.py          # Azure Functions entry point (imports blueprints)
blueprints/              # HTTP + pipeline function handlers
  pipeline/              # submission, blob_trigger, orchestrator, activities
treesight/               # Core library (no Azure Functions dependency)
  parsers/               # KML/KMZ parsing (fiona + lxml fallback)
  pipeline/              # Ingestion, acquisition, fulfilment, enrichment
  security/              # Auth, billing, quota
  storage/               # Blob + Cosmos clients
  constants.py           # All size limits, defaults, magic numbers
rust/src/lib.rs          # PyO3 extension: NDVI, change detection, SCL resample
website/                 # Static site (vanilla JS, no framework, no build step)
  js/app-shell.js        # Main SPA logic (~3k lines)
  staticwebapp.config.json
infra/tofu/              # OpenTofu infrastructure
scripts/                 # One-off setup and operational scripts
tests/                   # ~1200 tests across 52 files
  conftest.py            # Shared fixtures
  fixtures/              # Sample KML, GeoJSON, raster data
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `treesight/constants.py` | All limits and defaults — never inline magic numbers |
| `treesight/parsers/__init__.py` | KML/KMZ detection, unzip, parser dispatch |
| `treesight/parsers/fiona_parser.py` | Primary KML parser (Fiona/GDAL) |
| `treesight/parsers/lxml_parser.py` | Fallback KML parser (lxml, XXE-safe) |
| `blueprints/pipeline/submission.py` | POST /api/analysis/submit handler |
| `blueprints/pipeline/blob_trigger.py` | Event Grid → orchestrator |
| `blueprints/pipeline/orchestrator.py` | Durable Functions fan-out/fan-in |
| `blueprints/pipeline/activities.py` | Activity functions (parse, acquire, fulfil) |
| `blueprints/_helpers.py` | Auth check, CORS, error response helpers |

## Environment

- Python 3.12, managed by `uv`, config in `pyproject.toml`
- Rust crate built via `maturin` (PyO3), consumed as `treesight_rs` Python module
- Azurite for local blob/table storage (`make dev-up`)
- Azure Functions Core Tools for local function host (`func start`)

## Test Conventions

- Fixtures in `tests/conftest.py` and `tests/fixtures/`
- Test files mirror source: `treesight/parsers/` → `tests/test_parsers.py`
- Use `TEST_ORIGIN` and `TEST_LOCAL_ORIGIN` from conftest for CORS tests
- Tests run fast (~1000 tests in <60s) — no network, no real Azure calls
- Integration tests (`test-int`) require Azurite running
