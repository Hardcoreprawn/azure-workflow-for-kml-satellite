# Canopex

Canopex processes KML/KMZ parcel boundaries into satellite imagery and supporting
geospatial evidence. The current product focus is EUDR due-diligence support;
satellite screening and AI narratives are not legal compliance certificates.
See the [roadmap](docs/ROADMAP.md) for direction and delivery status.

## Canonical Documentation

| Question | Owning reference |
| --- | --- |
| Repository structure and processing | [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md) |
| API, activity and storage contracts | [API reference](docs/API_INTERFACE_REFERENCE.md), [OpenAPI](docs/openapi.yaml) |
| Run, verify, deploy and recover | [Operations runbook](docs/OPERATIONS_RUNBOOK.md) |
| Data ownership and evidence schemas | [Data model](docs/DATA_MODEL.md), [enrichment model](docs/ENRICHMENT_AOI_MODEL.md) |
| Direction and audience | [Roadmap](docs/ROADMAP.md), [persona research](docs/PERSONA_DEEP_DIVE.md) |
| Product requirements | [PID](docs/PID.md) |
| Scientific interpretation | [EUDR methodology](website/docs/eudr-methodology.html) |

The architecture, API reference and runbook describe checked-in behavior, not proof
of live deployment. Requirements and design specifications are not a shipped-feature
inventory. Dated material under [docs/archive](docs/archive) is historical context,
not current operating guidance. Reconcile implementation/documentation discrepancies;
do not silently treat either as an approved architecture change.

## Processing Overview

```text
Browser -> API-facing Function App -> Blob upload -> Event Grid
                                  -> Durable start/query
Durable task hub -> compute Function App
                -> ingest -> acquire -> fulfil -> enrich -> evidence artifacts
```

The API-facing app is named `orchestrator`, but compute currently executes both
Durable orchestration functions and activities. Both currently register HTTP
handlers. The intended target is a lightweight admission/API service with durable
buffering and independently scaled workers, retaining health probes but not the
full user API on compute. Azure coupling is intentional. Scale-to-zero is preferred
where wake-up latency is acceptable; hosting choice, latency budget and Batch
capacity require measured evidence. See the architecture overview for current/target
differences and follow-up work.

Authentication uses MSAL.js and Entra External ID (CIAM) bearer JWTs. SWA serves
static files, not trusted authentication headers. Diagnostics currently allow
anonymous access by instance ID; authentication and run-access authorization are
required before leaving local development. That change is not yet enforced.

## Development

Use the repository's VS Code devcontainer with Docker and Compose available.
Python 3.12 is the container/CI runtime; declarations live in
[pyproject.toml](pyproject.toml) and [uv.lock](uv.lock).

```bash
make dev-all
make test-fast TESTS="tests/test_docs_route_drift.py"
make check
```

The local website is `http://localhost:4280`; its development proxy targets the
compute host at `http://localhost:7071`. Direct orchestrator checks use
`http://localhost:7072`. For host/container differences, lifecycle hooks,
credentials, rebuilds and shutdown, use the [runbook](docs/OPERATIONS_RUNBOOK.md).
Starting the stack does not establish an authenticated browser session.

`make test-fast` accepts paths/node IDs only, not pytest flags. `make check` runs
lint, format, types, unit tests, JavaScript tests and changed-lines coverage. It
does not replace integration or pipeline acceptance:

| Command | Evidence |
| --- | --- |
| `make test` | Non-integration Python suite; coverage currently measures only `treesight` |
| `make test-js` | Executable JavaScript correctness tests |
| `make test-int` | Required Azurite integration tier |
| `make test-int-live` | Opt-in running-stack integration tier |
| `make test-int-stripe` | Opt-in external Stripe test-mode tier |
| `make test-pipeline-local` | Disposable synthetic pipeline gate |
| `make verify-local` | Running-stack surface/integration verification |

The [CI workflow](.github/workflows/ci.yml) is the executable CI definition.
Do not infer CI coverage from local target names: JavaScript CI wiring and expanded
Python coverage measurement remain tracked by #1525 and #1524. OpenAPI inventory
and payload coverage remain incomplete (#1530). Run `uv sync --all-extras` in a
writable project environment before interpreting full-gate dependency failures.

## Repository Retention

Keep runtime source, dependency locks, infrastructure, type stubs, test fixtures,
verification tools and decision records with identifiable consumers. Generated
coverage, caches, build output and local secrets are excluded by [.gitignore](.gitignore).
Unreferenced source is a review candidate, not proof of dead code: Function bindings,
CLI entrypoints and native extension calls may not appear as Python imports.
The architecture overview records ownership and cleanup boundaries.

## Contributing

Work from a linked issue, add regression tests before runtime changes, run
`make check`, and follow the [PR template](.github/pull_request_template.md).
Required CI and owner review remain mandatory; local success does not certify a
deployment. Do not bypass failing gates or discard unrelated working-tree changes.

## Licence

[MIT](LICENSE)
