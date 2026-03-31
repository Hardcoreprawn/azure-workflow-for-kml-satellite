# TreeSight — Automated Satellite Analysis Platform

Azure-hosted pipeline that ingests KML/KMZ boundaries, acquires
multi-provider satellite imagery, and delivers enriched analysis
(NDVI, weather, fire, flood, EUDR compliance) with AI-generated narratives.

> **Status:** Milestone 4 — Revenue (12/13 items complete). See [PRODUCT_ROADMAP.md](docs/PRODUCT_ROADMAP.md) for delivery plan.

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
**Providers:** Planetary Computer (Sentinel-2, Landsat C2 L2, NAIP, ESA WorldCover) via geo-routing provider with region-based collection selection
**Billing:** Stripe Checkout with multi-currency (GBP/EUR/USD) and UK Consumer Contracts compliance
**AI:** Azure AI Foundry (pay-per-token) with circuit breaker and result caching

See [PID.md](docs/PID.md) for the full Project Initiation Document and [ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md) for the deployed component guide.

## Features

- **KML/KMZ ingestion** — upload or paste boundaries, multi-polygon support
- **Multi-provider imagery** — geo-routing selects optimal collection per region (NAIP 0.6m US, Sentinel-2 10m global, Landsat 30m historical)
- **NDVI analysis** — vegetation index computation, change detection, canopy loss quantification
- **Weather integration** — Open-Meteo historical weather synced to imagery timeline
- **Event detection** — fire hotspots (FIRMS) and flood extent overlay
- **EUDR compliance** — post-2020 date filtering, WorldCover land-cover sampling, WDPA protected area check, coordinate-to-KML converter, AI deforestation-free assessment
- **AI narratives** — Azure AI Foundry generates plain-English analysis summaries
- **Export** — PDF audit reports, GeoJSON FeatureCollections, CSV timeseries
- **Billing** — Stripe-powered tiered subscriptions (Free / Starter / Pro / Team)
- **Auth** — Azure Entra External ID (CIAM) with JWT validation and per-user quotas

## Architecture Reference

- **System architecture:** [PID.md §7](docs/PID.md)
- **Deployed component/data-flow guide:** [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md)
- **Product roadmap & business strategy:** [docs/PRODUCT_ROADMAP.md](docs/PRODUCT_ROADMAP.md)
- **OpenAPI specification:** [docs/openapi.yaml](docs/openapi.yaml)

## Documentation Index

- **Operations runbook:** [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md)
- **API and interfaces:** [docs/API_INTERFACE_REFERENCE.md](docs/API_INTERFACE_REFERENCE.md)
- **Metadata JSON schema:** [docs/schemas/aoi-metadata-v2.schema.json](docs/schemas/aoi-metadata-v2.schema.json)
- **Signed-in UX spec:** [docs/SIGNED_IN_EXPERIENCE_SPEC.md](docs/SIGNED_IN_EXPERIENCE_SPEC.md)
- **EUDR methodology:** [website/eudr-methodology.html](website/eudr-methodology.html)
- **Infrastructure naming standard:** [docs/INFRA_NAMING_STANDARD.md](docs/INFRA_NAMING_STANDARD.md)

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
| GET | `/api/demo-results?token=...` | Validate valet token and reveal one authorized demo artifact | 200 | 401 / 403 |
| GET | `/api/demo-results/download?token=...` | Proxy a single authorized demo artifact download | 200 | 401 / 403 / 404 |
| POST | `/api/eudr-assessment` | EUDR compliance assessment (NDVI + WorldCover + WDPA) | 200 | 400 |
| POST | `/api/convert-coordinates` | Convert lat/lon coordinates to KML | 200 | 400 |
| POST | `/api/export` | Export analysis results (GeoJSON, CSV, PDF) | 200 | 400 |
| POST | `/api/create-checkout-session` | Create Stripe Checkout session | 200 | 400 |
| POST | `/api/stripe-webhook` | Handle Stripe webhook events | 200 | 400 |
| POST | `/api/create-portal-session` | Create Stripe customer portal session | 200 | 400 |

Protected/internal endpoint:

- `POST /api/demo-results-token` — mint a short-lived, replay-limited valet token for one demo artifact (Function auth)

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
├── .github/workflows/          CI, deploy, base-image-refresh, security
├── blueprints/                  Azure Functions HTTP blueprints
│   ├── analysis.py              EUDR assessment, AI insights
│   ├── billing.py               Stripe Checkout, webhooks, customer portal
│   ├── contact.py               Contact form endpoint
│   ├── demo.py                  Demo valet token + artifact download
│   ├── eudr.py                  Coordinate conversion endpoint
│   ├── export.py                GeoJSON, CSV, PDF export
│   ├── health.py                Liveness + readiness probes
│   └── pipeline.py              Orchestrator status + pipeline trigger
├── infra/tofu/                  OpenTofu IaC (Azure resources)
├── treesight/                   Application package
│   ├── ai/                      Azure AI Foundry client + circuit breaker
│   ├── models/                  Data models (AOI metadata, pipeline state)
│   ├── parsers/                 KML/KMZ parsing (Fiona + lxml fallback)
│   ├── pipeline/                Orchestration, enrichment, EUDR, acquisition
│   ├── providers/               Imagery providers (Planetary Computer, geo-routing)
│   ├── security/                Auth (JWT), rate limiting, replay protection, valet tokens
│   ├── storage/                 Blob storage helpers
│   ├── config.py                App configuration (Key Vault, env vars)
│   ├── constants.py             EUDR cutoff, API contract version, limits
│   ├── errors.py                Custom exception hierarchy
│   ├── geo.py                   Geometry utilities (Shapely, pyproj)
│   └── log.py                   Structured JSON logging
├── tests/                       595 tests (unit + integration)
│   ├── fixtures/                KML test files (valid + edge cases)
│   └── conftest.py              Shared fixtures and mocks
├── website/                     Static Web App (HTML/CSS/JS)
├── function_app.py              Azure Functions entry point (v2 model)
├── host.json                    Functions host configuration
├── Dockerfile                   Custom container (Python 3.12 + GDAL)
└── pyproject.toml               Dependencies and tool configuration
```

## Tech Stack

| Layer | Technology |
| --- | --- |
| Runtime | Python 3.12 |
| Compute | Azure Functions on Azure Container Apps (custom Docker) |
| Orchestration | Azure Durable Functions (Python v2 model) |
| KML Parsing | Fiona (OGR) + lxml (fallback) |
| Geometry | Shapely, pyproj |
| Raster | Rasterio, GDAL, NumPy |
| STAC | pystac-client, planetary-computer |
| AI | Azure AI Foundry (pay-per-token, circuit breaker) |
| Billing | Stripe (Checkout, webhooks, customer portal) |
| Auth | Azure Entra External ID (CIAM), JWT RS256 |
| Export | fpdf2 (PDF), GeoJSON, CSV |
| Linting | ruff |
| Type Checking | pyright |
| Testing | pytest (595 tests) |
| IaC | OpenTofu (Terraform-compatible) |
| CI/CD | GitHub Actions |
| Security | Semgrep, Trivy, pip-audit, CodeQL, detect-secrets |

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

For the full local product surface, run the Functions host and the website proxy
in separate terminals so `/api/*` stays same-origin and the signed-in app uses
the CIAM localhost redirect URI:

```bash
# Terminal 1
make dev-func

# Terminal 2
make dev-web
```

Then open `http://localhost:4280`.

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

### CIAM Sign-In Setup

TreeSight uses Azure Entra External ID (CIAM) for hosted SPA sign-in. The
CIAM bootstrap flow in `scripts/_create_user_flow.py` now defaults to
social/passwordless sign-in rather than dedicated TreeSight passwords.

```bash
# Graph token with permission to manage CIAM flows and identity providers
export CIAM_TOKEN=<entra-graph-token>

# Optional social providers
export CIAM_GOOGLE_CLIENT_ID=<google-client-id>
export CIAM_GOOGLE_CLIENT_SECRET=<google-client-secret>
export CIAM_FACEBOOK_CLIENT_ID=<facebook-client-id>
export CIAM_FACEBOOK_CLIENT_SECRET=<facebook-client-secret>

# Optional: disable the built-in email OTP fallback and allow only social sign-in
export CIAM_SOCIAL_ONLY=true

uv run python scripts/_create_user_flow.py
```

Behavior:

- If Google and/or Facebook credentials are present, those providers are created in the tenant (if needed) and linked to the TreeSight self-service flow.
- `EmailOtpSignup-OAUTH` stays enabled as the default fallback unless `CIAM_SOCIAL_ONLY=true`.
- Dedicated local passwords are off by default. Re-enable them only with an explicit override such as `CIAM_USER_FLOW_IDENTITY_PROVIDERS=EmailPassword-OAUTH`.
- `CIAM_USER_FLOW_IDENTITY_PROVIDERS` fully overrides the defaults, for example `Google-OAUTH,EmailOtpSignup-OAUTH`.

Local auth testing:

- Serve the website from `http://localhost:4280` so the SPA redirect URI matches the CIAM app registration.
- Use `uv run python scripts/dev_server.py --port 4280 --func-port 7071` when testing sign-in locally.

### Load Testing Baseline (#320)

Use the baseline runner to execute four scenarios and produce JSON/Markdown artifacts
for threshold analysis:

```bash
uv run python scripts/load_baseline.py --runs-per-scenario 3 --concurrency 2
```

If your local Event Grid webhook requires auth, provide the system key:

```bash
export EVENT_GRID_FUNCTION_KEY=<local-eventgrid-system-key>
uv run python scripts/load_baseline.py --runs-per-scenario 3 --concurrency 2
```

Scenarios covered:

- `baseline` (1 AOI)
- `moderate_bulk` (50 AOIs)
- `stress_bulk` (200 AOIs)
- `massive_polygon` (single large polygon)

Artifacts are written to `docs/baselines/` and include:

- scenario-level success/failure rates and p50/p95 durations
- per-run orchestration instance IDs and terminal states
- heuristic signals for throttling (`429`), timeout, and memory pressure

Limitation:

- External CIAM self-service flows support Google/Facebook social providers and email-based methods. Microsoft personal-account federation is not exposed as a self-service provider in this tenant model.

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
2. Copy application code (`function_app.py`, `host.json`, `treesight/`, `blueprints/`) into `/home/site/wwwroot`
3. Verify startup via `/api/health` and container logs

```dockerfile
FROM mcr.microsoft.com/azure-functions/python:4-python3.12 AS builder
WORKDIR /build
COPY host.json function_app.py ./
COPY treesight/ ./treesight/
COPY blueprints/ ./blueprints/

FROM mcr.microsoft.com/azure-functions/python:4-python3.12
COPY --from=builder /build/host.json /home/site/wwwroot/
COPY --from=builder /build/function_app.py /home/site/wwwroot/
COPY --from=builder /build/treesight/ /home/site/wwwroot/treesight/
COPY --from=builder /build/blueprints/ /home/site/wwwroot/blueprints/
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

Current contract version: `2026-03-15.1` (defined in `treesight/constants.py` as `API_CONTRACT_VERSION` and checked inline in `website/index.html`).

### When to bump the version

Bump the contract version whenever the frontend requires a new API capability that does not yet exist in the deployed backend. Examples:

- A new HTTP route that the frontend will call
- A changed response schema that the frontend depends on
- A renamed or removed endpoint

Do **not** bump for backend-only changes (new logic, bug fixes, performance improvements) that do not affect the frontend interface.

### How to bump

1. Decide on the new version string using the format `YYYY-MM-DD.N` (e.g. `2026-04-01.1`).
2. In `treesight/constants.py`, update `API_CONTRACT_VERSION = "NEW_VERSION"`.
3. Update the version check in `website/index.html` if the frontend validates the version string.
4. Implement the new API capability in `function_app.py`.
5. **Deploy the backend first** and confirm the deploy workflow passes (`/api/api-contract` returns the new version).
6. Then deploy the frontend — the deploy workflow checks that the live backend version matches before proceeding.

If you deploy the frontend before the backend is ready, the gate will fail with a version mismatch error. This is intentional.

## Contributing

1. Create a feature branch from `main` (`git checkout -b feature/issue-number-description`)
2. Make changes following the engineering principles in [PID.md §7.4](PID.md)
3. Run `uv run ruff format .` before opening or updating a PR
4. Pre-commit hooks enforce lint, format, and type checks automatically, and PR CI uploads a formatting patch artifact if drift is detected
5. Add/update tests — all new code requires unit tests
6. Open a PR using the provided template; changes to `main` should go through PRs rather than direct pushes

## Licence

MIT
