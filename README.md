# Azure Workflow for KML Satellite Imagery Acquisition

Automated Azure pipeline that ingests KML files containing agricultural field
boundaries, extracts polygon geometry, acquires high-resolution satellite
imagery, and stores outputs in Azure Blob Storage.

> **Status:** Phase 1 — Foundation & KML Ingestion

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

**Compute:** Azure Functions v4 Flex Consumption (custom Docker with GDAL)
**Orchestration:** Azure Durable Functions — fan-out/fan-in, async polling with zero-cost timers
**Providers:** Planetary Computer (free, dev/test) · SkyWatch EarthCache (paid, production)

See [PID.md](PID.md) for the full Project Initiation Document.

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
| Compute | Azure Functions v4 Flex Consumption (custom Docker) |
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
