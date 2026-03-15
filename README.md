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

See [PID.md](docs/PID.md) for the full Project Initiation Document and [ARCHITECTURE_REVIEW.md](docs/reviews/ARCHITECTURE_REVIEW.md) for implementation-level architecture notes.

## Architecture Reference

- **System architecture:** [PID.md §7](docs/PID.md)
- **Deployed component/data-flow guide:** [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md)
- **Codebase architecture review:** [docs/reviews/ARCHITECTURE_REVIEW.md](docs/reviews/ARCHITECTURE_REVIEW.md)
- **Execution plan and phase gates:** [ROADMAP.md](ROADMAP.md)

## Documentation Index

- **Operations runbook:** [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md)
- **API and interfaces:** [docs/API_INTERFACE_REFERENCE.md](docs/API_INTERFACE_REFERENCE.md)
- **Metadata JSON schema:** [docs/schemas/aoi-metadata-v2.schema.json](docs/schemas/aoi-metadata-v2.schema.json)
- **UAT execution plan:** [docs/reviews/UAT_VALIDATION.md](docs/reviews/UAT_VALIDATION.md)

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

- `GET /api/orchestrator/{instance_id}` — returns direct JSON diagnostics with runtime state, summary counts, and discovered artifact blob paths

Local check:

```bash
curl -sS http://localhost:7071/api/orchestrator/<instance-id>
```

### Endpoint Access Contract (Issue #163)

Anonymous-by-design endpoints (safe for probes and operator diagnostics):

- `GET /api/health`: liveness only (host/config loaded)
- `GET /api/readiness`: dependency readiness summary (config + storage)
- `GET /api/orchestrator/{instance_id}`: bounded orchestration diagnostics for a known instance id

Protected management endpoints (never anonymous):

- `POST /admin/host/status` and `GET /admin/functions` (host management API)
- `POST /host/default/listKeys` via ARM management plane
- Durable runtime admin APIs under `/runtime/webhooks/durabletask/*`

Why this boundary exists:

- Public probes must be callable by Container Apps/ops tooling without key distribution.
- Runtime/admin endpoints expose host control and key material; they require function/admin or ARM auth.

Deployment readiness contract:

1. Deploy workflow uses protected host/admin endpoints only inside OIDC-authenticated pipeline steps.
2. Event Grid webhook reconciliation uses runtime system key after host readiness is confirmed.
3. Remote smoke checks for operators should use anonymous endpoints plus blob artifact verification.

Do not expose anonymously:

- Any endpoint that returns secrets/keys, host admin metadata, or mutable runtime control.
- Generic Durable runtime management URLs for broad instance enumeration.

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

For Azure Functions on Container Apps, infrastructure dependencies alone are not sufficient to guarantee Event Grid readiness. Python v2 functions are discovered by the Functions host at runtime, and the host must fully load before Event Grid subscription creation.

**Container Apps vs Consumption Plan differences:**

- **Function discovery:** `az functionapp function list` does not work reliably for Container Apps. Use HTTP endpoint checks (`/api/health`) instead.
- **Python v2 discovery:** Function routes are indexed when the host starts; no `func build` step is required in the container image build.
- **TLS termination:** Azure handles HTTPS at ingress; containers listen on port 80 internally.

Required deployment order:

1. Deploy infra + Function App container image with `enableEventGridSubscription=false`.
2. Poll function host readiness (HTTP `/api/health` endpoint) as advisory telemetry.
3. Re-apply infra with `enableEventGridSubscription=true` using retry-on-validation-failure.
4. Verify `evgs-kml-upload` subscription exists on `evgt-<baseName>`.

This sequencing is enforced in [.github/workflows/deploy.yml](.github/workflows/deploy.yml) to prevent race conditions where Event Grid fails with "validation request did not receive expected response."

#### Defensive coding principles (Margaret Hamilton standard)

The deployment retry loops implement production-grade defensive patterns designed for autonomous operation over years:

**Wall-clock timeouts:** Each retry loop has both attempt count limits AND wall-clock timeouts. This prevents scenarios where slow-failing deployments (e.g., 2-3 minutes per Azure deployment) could run for 60+ minutes.

- Function discovery: 30 attempts max OR 300s wall-clock (5 minutes), whichever comes first
- Event Grid enablement: 15 attempts max OR 900s wall-clock (15 minutes), whichever comes first

**Exponential backoff:** Event Grid retry uses exponential backoff (10s, 20s, 30s... capped at 60s) rather than fixed 15s intervals, reducing Azure API load and respecting transient error recovery patterns.

**Fail-fast detection:** Non-transient errors (authorization/credential failures) trigger immediate loop exit rather than exhausting all retry attempts. Only endpoint validation errors (expected transient) continue retries.

**Observability:** Each attempt logs:

- Attempt number and elapsed time
- Individual operation duration
- Error details with pattern detection
- Calculated backoff intervals

**Graceful degradation:** Function discovery failures emit warnings (not errors) and allow the authoritative Event Grid retry loop to determine final success/failure.

Implementation reference: [deploy.yml L100-L185](.github/workflows/deploy.yml#L100-L185)
Test coverage: [test_deploy_workflow.py](tests/unit/test_deploy_workflow.py)

## API Reference

### Public HTTP endpoints

| Method | Path | Purpose | Success | Failure |
| --- | --- | --- | --- | --- |
| GET | `/api/health` | Liveness probe | 200 | 500 |
| GET | `/api/readiness` | Dependency readiness probe | 200 | 503 |
| GET | `/api/orchestrator/{instance_id}` | Durable instance status + output artifact diagnostics | 200 | 400 / 404 |

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
├── infra/                       OpenTofu IaC modules and environments
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
| IaC | OpenTofu (Terraform-compatible) |
| CI/CD | GitHub Actions |

## CI Lanes (Issue #150)

The CI pipeline is intentionally split into two lanes with different cost/latency profiles:

- `Fast Lint Type Unit`: fast feedback lane (ruff, pyright, targeted unit tests) with no runner-level APT install.
- `Native Geo Validation`: correctness lane for native geospatial/runtime surfaces (GDAL system deps, native import validation, broader test execution).

Trade-off and policy:

- Fast lane optimizes PR iteration time for typical application edits.
- Native lane preserves safety for geospatial/runtime correctness and remains required in CI.

Reference: `.github/workflows/ci.yml`

## Geospatial Base Image Refresh (Issue #151)

Base image automation runs in `.github/workflows/base-image-refresh.yml` on a weekly schedule and manual dispatch.

Publication model:

- Immutable run-scoped tag: `geo-base-<sha>-<run-id>-<attempt>`
- Rolling stable refs: `geo-base-stable`, `geo-base-latest`

Consumer update path:

1. Default deploy behavior consumes `geo-base-stable`.
2. For a controlled validation run, execute `Deploy Function App` via manual dispatch and provide optional overrides (`builder_base_image`, `runtime_base_image`).

3. After validation, keep defaults on `geo-base-stable` or pin to a specific immutable tag/digest if stricter reproducibility is required.

References:

- `.github/workflows/base-image-refresh.yml`
- `.github/workflows/deploy.yml`
- `docs/adr/0001-geospatial-base-image-strategy.md`

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

## Troubleshooting

### Common Container Build Issues

#### APT repository conflict error

**Symptom:**

```text
E: Conflicting values set for option Signed-By regarding source  
https://packages.microsoft.com/debian/12/prod/ bookworm:
/usr/share/keyrings/microsoft-archive-keyring.gpg !=
/usr/share/keyrings/microsoft-prod.gpg
```

**Cause:** The Azure Functions Python base image (`mcr.microsoft.com/azure-functions/python:4-python3.12`) already has Microsoft's APT repository configured with a signing key at `/usr/share/keyrings/microsoft-prod.gpg`. Attempting to add the same repository with a different keyring path creates a duplicate entry that APT rejects.

**Solution:** Do not re-add Microsoft package repositories in this image:

```dockerfile
# ❌ Wrong: Adding duplicate repo with different signing key
RUN curl https://packages.microsoft.com/keys/microsoft.asc | \
    gpg --dearmor -o /usr/share/keyrings/microsoft-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/microsoft-archive-keyring.gpg] ..." \
    > /etc/apt/sources.list.d/microsoft-prod.list && \
  apt-get update
```

**Test coverage:** [`tests/unit/test_dockerfile.py::TestAptRepositorySafety::test_no_manual_microsoft_repo_setup`](tests/unit/test_dockerfile.py)

### Common Deployment Issues

#### Functions not discovered (0 functions found)

**Symptom:** Deployment succeeds, but Functions host logs show:

```text
Reading functions metadata (Custom)
0 functions found (Custom)
Generating 0 job function(s)
Host started (no HTTP routes)
```

HTTP requests to function endpoints return 404.

**Cause:** In Container Apps, discovery can fail while the host is still starting, dependencies are not loaded, or app configuration is invalid. Unlike older assumptions, Python v2 does not require a build-time `func build` step.

**Solution:**

1. Keep a clean multi-stage image with required runtime dependencies
2. Copy application code (`function_app.py`, `host.json`, `kml_satellite/`) into `/home/site/wwwroot`
3. Verify startup via `/api/health` and container logs

```dockerfile
FROM mcr.microsoft.com/azure-functions/python:4-python3.12 AS builder
WORKDIR /build
COPY host.json function_app.py ./
COPY kml_satellite/ ./kml_satellite/

FROM mcr.microsoft.com/azure-functions/python:4-python3.12
COPY --from=builder /build/host.json /home/site/wwwroot/
COPY --from=builder /build/function_app.py /home/site/wwwroot/
COPY --from=builder /build/kml_satellite/ /home/site/wwwroot/kml_satellite/
```

**Verification:**

```bash
# Build locally and verify host startup
docker build -t test:latest .
docker run --rm -p 8080:80 test:latest
# Then call: curl http://localhost:8080/api/health
```

**Test coverage:** [`tests/unit/test_dockerfile.py::TestFunctionMetadataGeneration`](tests/unit/test_dockerfile.py)

#### Readiness check failures on Container Apps

**Symptom:** Deployment workflow times out or fails with "Functions not discoverable after 30 attempts"

**Cause:** Management plane APIs (`az functionapp function list`) don't work reliably for Container Apps. The Functions host may be running but not yet loaded all functions, or the API may return stale/empty results.

**Solution:** Use data plane HTTP checks instead:

```bash
# ❌ Wrong: Management plane API (unreliable for Container Apps)
az functionapp function list \
  --name func-app-name \
  --resource-group rg-name

# ✅ Correct: Data plane HTTP endpoint
fqdn=$(az functionapp show \
  --name func-app-name \
  --resource-group rg-name \
  --query defaultHostName -o tsv)

http_response=$(curl -sS -o /dev/null -w "%{http_code}" \
  "https://${fqdn}/api/health")

# Interpret response codes:
# 200 = Functions loaded and ready
# 404 = Host running but functions still loading
# 503 = Host not ready yet
```

**Test coverage:** [`tests/unit/test_deploy_workflow.py::TestReadinessCheck::test_readiness_uses_function_list`](tests/unit/test_deploy_workflow.py)

#### Event Grid validation failures

**Symptom:**

```text
Webhook validation handshake failed for 'https://func-app.azurewebsites.net/...'
Destination endpoint not found or did not respond within expected timeout.
```

**Cause:** For Azure Functions hosted on Azure Container Apps, using `endpointType: AzureFunction` with ARM resource ID (`.../functions/kml_blob_trigger`) can fail because the function child resource is not reliably discoverable by Event Grid during subscription creation.

**Solution:** Use webhook destination wiring to the Functions runtime endpoint and keep two-pass deployment:

1. **First pass:** Deploy infrastructure + Function App with `enableEventGridSubscription=false`
2. **Poll readiness:** Wait for `/api/health` to return 200 (functions loaded)
3. **Second pass:** Deploy with `enableEventGridSubscription=true` (with retry/backoff), where Event Grid points to:
  `https://<function-host>/runtime/webhooks/eventgrid?functionName=kml_blob_trigger&code=<eventgrid-system-key>`

This sequence is enforced in [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml).

**Test coverage:** [`tests/unit/test_deploy_workflow.py::TestReadinessCheck::test_event_grid_uses_two_pass_toggle`](tests/unit/test_deploy_workflow.py)

### Container Apps Platform Differences

These behaviors differ from Azure Functions Consumption Plan:

| Aspect | Consumption Plan | Container Apps |
| --- | --- | --- |
| Function discovery API | `az functionapp function list` works | Unreliable; use HTTP `/api/health` |
| Python v2 metadata | Runtime generation supported | Runtime generation supported (no `func build`) |
| TLS termination | Port 443 internal | Port 80 internal, Azure ingress handles TLS |
| Cold start | <1s (pre-warmed) | 5-15s (container startup) |
| Scale-to-zero | Yes (Consumption) | Yes (Container Apps) |
| Custom system deps | No (restricted runtime) | Yes (custom Docker) |

**Documentation:** See "Container Apps vs Consumption Plan differences" in [Operations Runbook](#operations-runbook) section above.

### Debugging Container Locally

```bash
# Pull deployed image
docker pull ghcr.io/hardcoreprawn/azure-workflow-for-kml-satellite:<commit-sha>

# Run locally with storage emulator
docker run --rm -d -p 8080:80 \
  -e "AzureWebJobsStorage=UseDevelopmentStorage=true" \
  ghcr.io/hardcoreprawn/azure-workflow-for-kml-satellite:<commit-sha>

# Check logs (wait 30s for host to start)
docker logs <container-id>

# Look for "Host started" and function indexing output

# Test health endpoint
curl http://localhost:8080/api/health
```

## API Contract Versioning

The frontend and backend share a contract version string that enforces backend-first deployment discipline. The website deploy workflow **will not proceed** unless the live backend reports the expected version at `/api/api-contract`.

Current contract version: `2026-03-15.1` (defined in `function_app.py` as `_API_CONTRACT_VERSION` and in `website/static/app.js` as `REQUIRED_API_CONTRACT_VERSION`).

### When to bump the version

Bump the contract version whenever the frontend requires a new API capability that does not yet exist in the deployed backend. Examples:

- A new HTTP route that the frontend will call
- A changed response schema that the frontend depends on
- A renamed or removed endpoint

Do **not** bump for backend-only changes (new logic, bug fixes, performance improvements) that do not affect the frontend interface.

### How to bump

1. Decide on the new version string using the format `YYYY-MM-DD.N` (e.g. `2026-04-01.1`).
2. In `function_app.py`, update `_API_CONTRACT_VERSION = "NEW_VERSION"`.
3. In `website/static/app.js`, update `REQUIRED_API_CONTRACT_VERSION = 'NEW_VERSION'`.
4. Implement the new API capability in `function_app.py`.
5. **Deploy the backend first** and confirm the deploy workflow passes (`/api/api-contract` returns the new version).
6. Then deploy the frontend — the preflight gate in `deploy-website-swapp.yml` reads `REQUIRED_API_CONTRACT_VERSION` from source, calls the live endpoint, and only continues if the versions match.

If you deploy the frontend before the backend is ready, the gate will fail with a version mismatch error. This is intentional.

## Contributing

1. Create a feature branch from `main` (`git checkout -b feature/issue-number-description`)
2. Make changes following the engineering principles in [PID.md §7.4](PID.md)
3. Pre-commit hooks enforce lint, format, and type checks automatically
4. Add/update tests — all new code requires unit tests
5. Open a PR using the provided template

## Licence

MIT
