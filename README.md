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

- Python 3.12
- GDAL system libraries (`gdal-bin`, `libgdal-dev`)
- [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local)
- Docker (for building the custom container)

### Local Development

```bash
# Clone the repository
git clone https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite.git
cd azure-workflow-for-kml-satellite

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Install dependencies (including dev tools)
pip install -e ".[dev]"

# Copy local settings template
cp local.settings.json.template local.settings.json

# Run linting
ruff check .
ruff format --check .

# Run type checking
pyright

# Run tests
pytest tests/unit -v
```

### Running with Azure Functions Core Tools

```bash
func start
```

### Building the Docker Image

```bash
docker build -t kml-satellite:dev .
```

## Contributing

1. Create a feature branch from `main`
2. Make changes following the engineering principles in [PID.md §7.4](PID.md)
3. Ensure `ruff check`, `ruff format --check`, and `pyright` all pass
4. Add/update tests — all new code requires unit tests
5. Open a PR using the provided template

## Licence

MIT
