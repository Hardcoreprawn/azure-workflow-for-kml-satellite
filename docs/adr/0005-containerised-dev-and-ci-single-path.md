# ADR 0005: Containerised Dev + CI as a Single Path

## Status

Proposed

## Context

We currently maintain two parallel ways to run the stack, and the toolchain is
inconsistent about how dependencies are installed:

- **Local path** — `make dev-func` (`func start --python`) + `make dev-web`
  (`scripts/dev_server.py`), with Azure Functions Core Tools installed on the
  host via `scripts/setup_func_tools.sh`. Azurite runs in Docker.
- **Docker path** — `make dev-all` / `dev-rebuild` / `dev-logs`, a full
  `docker compose` stack (func + web + azurite + init-storage).
- **Dependency installers** — the container images already use `uv`, but a
  handful of CI steps and operational scripts still use `pip`
  (`.github/workflows/infracost.yml`, `.github/workflows/security.yml`,
  `scripts/collect_infracost_usage.py`, `scripts/dashboard.py`).

Two consequences follow. First, the two dev paths duplicate environment
definitions (Makefile local settings vs the compose `environment:` block) and
can silently drift. Second, the local `func start` runtime is a code path that
**production never uses** — production runs the application as a container on
Azure Container Apps — so bugs can hide in, or appear only in, one path.

Production is containerised. Our development and CI environments should exercise
the same execution model rather than reconstruct "sameness" from a separate set
of pinned-version mechanisms.

## Options Evaluated

1. **Keep both paths.** Maintain local func-start *and* docker-compose, plus the
   status quo mix of `pip`/`uv`.
2. **Single path, host-based gates.** Containerise the runtime stack; run quality
   gates (lint/test/type) on the host/CI runner via `setup-uv` + `uv sync`,
   relying on `uv.lock` + pinned tool versions for local↔CI sameness.
3. **Single path, containerised gates.** Containerise the runtime stack *and* run
   the quality gates inside a project-owned dev container image that both
   developers and CI consume by digest. Sameness is guaranteed by a single
   artifact rather than a parallel version-pinning mechanism.

## Selected Strategy

**Option 3 — a single containerised path for both development and CI.**

### Execution-context rule

> **Every job runs inside a container by default.** A job may run on the bare
> runner **only if it builds or publishes a container image** (buildx), which
> cannot be expressed as GitHub Actions `container:` + `services:`. Speed is
> **not** a justification for leaving the path — non-interactive automated jobs
> may be slow, because no human waits on them synchronously.

This gives a decision *test* rather than a hand-maintained bucket list: "does
this job build an image? No → it runs in the container."

### What runs where

| Concern | Execution context | Rationale |
|---------|-------------------|-----------|
| Dev environment + gates (lint / test / type) | **Dev container image** (`container:` by digest; devcontainer locally) | Reproducible toolchain; where developers live |
| Unit tests | Dev container image | Same image as gates |
| Integration tests | Dev container image + Azurite as a `services:` entry | Native GHA — no docker-in-docker |
| e2e / smoke | Dev container image + published app image + Azurite as `services:` | The thing under test is a service container, not a host compose stack |
| App runtime (interactive dev) | `docker compose` (func + web + azurite) | Parity with prod Container Apps |
| **Image build / publish** (base → dev → app) | **Bare runner (buildx)** | The one irreducible exception — building an image is a host operation |

### Dev container image

- **Extends `treesight-base`** (`ghcr.io/<owner>/treesight-base`) so the
  Functions host runtime matches production. The native-library parity that
  matters for tests (GDAL/Fiona/rasterio and the `treesight_rs` Rust extension)
  comes from installing the **locked dependency layer** (`uv sync --all-extras`)
  plus the build toolchain needed for `treesight_rs`, not from the Functions
  host itself — the dev image adds both on top of the base.
- **Published to GHCR** by a workflow triggered on changes to
  `.devcontainer/**`, `pyproject.toml`, and `uv.lock`.
- **Consumed by digest** by both developers (devcontainer) and CI gate jobs
  (`jobs.<id>.container:`). No `setup-uv` step in gate jobs — `uv` and the tools
  are baked into the image.

### Sameness model

Sameness flows through **one artifact**:

```text
treesight-base ──▶ dev image (from uv.lock) ──▶ published to GHCR by digest
                                                   │
                        ┌──────────────────────────┴───────────────────────┐
                        ▼                                                    ▼
              developer devcontainer                                  CI gate jobs
```

To prevent the single artifact from going stale, CI gate jobs run a cheap
**lock-vs-image guard** (`uv sync --frozen` / lock-vs-installed check) inside the
container and fail if the image does not match `uv.lock`. This converts the
"separate sameness mechanism" concern into a single assertion that the shared
artifact is current.

### Other decisions

- **Docker is a hard prerequisite** for local development. The local func-start
  path is retired: remove `make dev-func`, `dev-web`, `dev-start`, and
  `scripts/setup_func_tools.sh`.
- **Live-reload dev override.** Add a `docker compose` dev override that
  volume-mounts source into the `func` container (as the `web` service already
  does) with watch, so the inner loop stays fast without a second stack.
- **`uv` everywhere.** `uv`/`uvx` is the dependency installer in all contexts —
  host, CI, and inside images. Remaining `pip` usages migrate to `uv`/`uvx`.
  "Containers vs uv" was never an either/or.
- **Makefile stays the single command source.** Local and CI invoke the same
  `make` targets; the change is the *context* they run in, not the commands.

## Consequences

### Positive

- Local, CI, and production descend from `treesight-base` — one execution model,
  fewer seams to drift at.
- `local == CI` holds **by construction** (shared image digest) rather than by a
  parallel version-pinning mechanism.
- Removes docker-in-docker from the test path entirely (via `container:` +
  `services:`); DinD/buildx is confined to image build/publish.
- Stronger reproducibility for ESG/EUDR auditability — the auditor's build, the
  developer's build, and CI's build are the same bytes.
- Eliminates duplicated environment definitions between Makefile and compose.

### Trade-offs

- **Image staleness risk** if the dev image is not rebuilt after a dependency
  change. Mitigated by the publish trigger on `pyproject.toml`/`uv.lock` and the
  lock-vs-image guard in CI.
- **Bootstrap ordering** — the dev image depends on `treesight-base`, which CI
  builds; the publish pipeline must sequence base → dev.
- **Cold image pulls** add latency to gate jobs vs a cached `setup-uv`. Accepted:
  gate jobs pull a prebuilt image by digest, and non-interactive jobs are allowed
  to be slow.
- **Docker becomes mandatory** for all contributors; there is no host-only
  fallback by design.

## Rejected Alternatives

- **Option 1 (keep both paths).** Rejected: the divergence and prod-parity gap
  are the problem we are solving.
- **Option 2 (host-based gates).** Rejected in favour of Option 3 because it
  relies on a *separate* sameness mechanism (`setup-uv` + `uv.lock` + pinned tool
  versions on `ubuntu-latest`) that must be kept aligned with the dev
  environment. Option 3 collapses that into a single shared artifact.
- **CI building/running the devcontainer image from scratch each run.** Rejected:
  slow. The image is prebuilt and published to GHCR; CI consumes it by digest.

## Follow-up

Delivery is tracked by umbrella issue #1082 with independent slices:

- **#1084 uv migration** — replace remaining `pip` usages with `uv`/`uvx`
  (touches two GitHub Actions workflows; approval-gated, kept separate from code
  slices).
- **#1085 Devcontainer + dev image** — add `.devcontainer/`, build/publish
  workflow, lock-vs-image guard.
- **#1086 CI gate jobs → `container:`** — move lint/test/type/integration/e2e
  into the dev image; keep only image build/publish on the runner.
- **#1087 Dev-stack consolidation** — retire local func-start targets and
  `setup_func_tools.sh`; add the live-reload compose override; collapse env
  config to compose.
