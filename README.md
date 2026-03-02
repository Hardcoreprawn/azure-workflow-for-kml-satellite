# Azure Workflow for KML Satellite Imagery Acquisition

Automated Azure pipeline that ingests KML files containing agricultural field
boundaries, extracts polygon geometry, acquires high-resolution satellite
imagery, and stores outputs in Azure Blob Storage.

> **Status:** Phase 3 — v1 Hardening (see [ROADMAP.md](ROADMAP.md) for delivery plan)

## Architecture

```text
KML Upload → Blob Storage → Event Grid → Durable Functions Orchestrator
                                              │
                 ┌────────────────────────────┤
                 ▼                            ▼
           Parse KML                    Fan-out per polygon
           Extract Geometry                   │
                                 ┌────────────┼────────────┐
                                 ▼            ▼            ▼
                            Prepare AOI  Acquire Imagery  Post-Process
                                                          (Clip, Store)
                                              │
                                              ▼
                                    Blob Storage (GeoTIFF + Metadata JSON)
```

**Compute:** Azure Functions on Azure Container Apps (custom Docker with GDAL)
**Orchestration:** Azure Durable Functions — fan-out/fan-in, async polling with zero-cost timers
**Providers:** Planetary Computer (free STAC API, all tiers). Commercial adapters (Phase 5+).

See [PID.md](PID.md) for the full Project Initiation Document and [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) for implementation-level architecture notes.

## Architecture Reference

- **System architecture:** [PID.md §7](PID.md)
- **Codebase architecture review:** [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md)
- **Execution plan and phase gates:** [ROADMAP.md](ROADMAP.md)

## Operations Runbook

### Health and readiness checks

- `GET /api/health` — liveness probe (configuration loads successfully)
- `GET /api/readiness` — readiness probe (configuration + storage dependency checks)

Local checks:

```bash
curl -sS http://localhost:7071/api/health
curl -sS http://localhost:7071/api/readiness
```

### Orchestration status inspection

- `GET /api/orchestrator/{instance_id}` — returns Durable Functions check-status response

Local check:

```bash
curl -sS http://localhost:7071/api/orchestrator/<instance-id>
```

### Log and alert triage

1. Check Function App logs for `instance_id`, `order_id`, `blob`, and `feature` fields.
2. Check Application Insights traces and exceptions for failed stage names (`parse_kml`, `acquire_imagery`, `poll_order`, `download_imagery`, `post_process_imagery`, `write_metadata`).
3. Check Azure Monitor metric alerts:
   - `alert-<baseName>-failed-requests`
   - `alert-<baseName>-high-latency`
4. For persistent failures, query orchestration status endpoint and correlate with App Insights traces.

### Recovery actions

- **Malformed input event:** validate blob container naming and `.kml` extension; re-upload corrected input.
- **Provider transient failure:** allow orchestrator retries/backoff to complete before manual intervention.
- **Provider permanent failure:** review provider response in logs, fix configuration/credentials, then re-trigger with a new upload.
- **Storage connectivity failure:** verify Function App app settings (`AzureWebJobsStorage`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `KEY_VAULT_URI`) and managed identity RBAC.

### Deployment sequencing (critical)

For Azure Functions on Container Apps, infrastructure dependencies alone are not sufficient to guarantee Event Grid readiness. The `kml_blob_trigger` function must be indexed by the host before Event Grid subscription creation.

Required deployment order:

1. Deploy infra + Function App container image with `enableEventGridSubscription=false`.
2. Poll function discovery until `kml_blob_trigger` appears in `az functionapp function list`.
3. Re-apply infra with `enableEventGridSubscription=true`.
4. Verify `evgs-kml-upload` subscription exists on `evgt-<baseName>`.

This sequencing is enforced in [.github/workflows/deploy.yml](.github/workflows/deploy.yml) to prevent race conditions where Event Grid fails with "validation request did not receive expected response."

## API Reference

### Public HTTP endpoints

| Method | Path | Purpose | Success | Failure |
| --- | --- | --- | --- | --- |
| GET | `/api/health` | Liveness probe | 200 | 500 |
| GET | `/api/readiness` | Dependency readiness probe | 200 | 503 |
| GET | `/api/orchestrator/{instance_id}` | Durable instance status lookup | 200 | 400 / 404 |

### Event-driven entrypoint

- Event Grid trigger function: `kml_blob_trigger`
- Expected event source: blob-created events for input containers ending in `-input`
- Expected payload contract: canonical blob event fields (`blob_url`, `container_name`, `blob_name`, `content_length`, `content_type`, `event_time`, `correlation_id`)

### Durable orchestrations

- `kml_processing_orchestrator` — main 3-phase workflow
- `poll_order_suborchestrator` — bounded concurrent polling loop for imagery orders

### Durable activities

- `parse_kml`
- `prepare_aoi`
- `acquire_imagery`
- `poll_order`
- `download_imagery`
- `post_process_imagery`
- `write_metadata`

## Project Structure

```text
├── .github/workflows/ci.yml    CI pipeline (lint, type check, test)
├── infra/                       Bicep IaC templates
├── kml_satellite/               Application package
│   ├── activities/              Durable Functions activity functions
│   ├── orchestrators/           Durable Functions orchestrators
│   ├── models/                  Data models and schemas
│   ├── providers/               Imagery provider adapters
│   └── core/                    Config, constants, logging, geometry utils
├── tests/
│   ├── data/                    17 test KML files (valid + edge cases)
│   ├── unit/                    Unit tests
│   └── integration/             Integration tests
├── function_app.py              Azure Functions entry point (v2 model)
├── host.json                    Functions host configuration
├── Dockerfile                   Custom container (Python 3.12 + GDAL)
├── pyproject.toml               Dependencies and tool configuration
└── PID.md                       Project Initiation Document (v1.1)
```

## Tech Stack

| Layer | Technology |
| --- | --- |
| Runtime | Python 3.12 |
| Compute | Azure Functions on Azure Container Apps (custom Docker) |
| Orchestration | Azure Durable Functions (Python v2 model) |
| KML Parsing | Fiona (OGR) + lxml (fallback) |
| Geometry | Shapely, pyproj |
| Raster | Rasterio, GDAL |
| STAC | pystac-client |
| Linting | ruff |
| Type Checking | pyright |
| Testing | pytest |
| IaC | Bicep |
| CI/CD | GitHub Actions |

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (package manager — installs Python 3.12 automatically)
- GDAL system libraries (`gdal-bin`, `libgdal-dev`) — Linux only; uv handles Python
- [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local)
- Docker (for building the custom container)

### Local Development

```bash
# Clone the repository
git clone https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite.git
cd azure-workflow-for-kml-satellite

# Install Python 3.12 + all dependencies (creates .venv automatically)
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Copy local settings template
cp local.settings.json.template local.settings.json

# Run all quality checks manually
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest tests/unit -v

# Or run everything via pre-commit
uv run pre-commit run --all-files
```

### Pre-commit Hooks

The following hooks run automatically on every `git commit`:

| Hook | What it does |
| --- | --- |
| trailing-whitespace | Removes trailing whitespace |
| end-of-file-fixer | Ensures files end with a newline |
| check-yaml / json / toml | Validates config file syntax |
| check-added-large-files | Blocks files > 1 MB |
| detect-private-key | Prevents committing private keys |
| no-commit-to-branch | Blocks direct commits to `main` |
| ruff (lint) | Lints Python, auto-fixes where possible |
| ruff (format) | Checks Python formatting |
| pyright | Static type checking |
| detect-secrets | Scans for leaked credentials |
| markdownlint | Lints markdown files |

To bypass hooks for exceptional cases: `git commit --no-verify`

### Running with Azure Functions Core Tools

```bash
func start
```

### Building the Docker Image

```bash
docker build -t kml-satellite:dev .
```

## Contributing

1. Create a feature branch from `main` (`git checkout -b feature/issue-number-description`)
2. Make changes following the engineering principles in [PID.md §7.4](PID.md)
3. Pre-commit hooks enforce lint, format, and type checks automatically
4. Add/update tests — all new code requires unit tests
5. Open a PR using the provided template

## Licence

MIT
