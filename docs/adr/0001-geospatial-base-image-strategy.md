# ADR 0001: Geospatial Base Image Strategy (Issue #152)

## Status

Accepted

## Context

CI and deploy builds depend on heavyweight native geospatial dependencies (GDAL/Fiona/rasterio stack). Re-installing these on ephemeral runners is slow and can vary by package mirror state.

## Options Evaluated

1. Use an upstream geospatial image directly
2. Build and maintain a project-owned base image in GHCR
3. Hybrid model: upstream Azure Functions base plus project-controlled base image inputs

## Selected Strategy

Hybrid model (Option 3).

- Keep secure defaults pointing at a project-owned validated geospatial base (`geo-base-stable`)
- Make both builder and runtime base images explicit build inputs
- Allow controlled pinning (tag or digest) through manual deploy inputs
- Prepare path for project-owned GHCR base image rollout without breaking current deploys

## Provenance

- Base image source defaults to GHCR `geo-base-stable` produced by the refresh workflow
- Image provenance remains traceable through commit-SHA tagged final images in GHCR
- Build metadata labels remain attached in deploy workflow

## Pinning Approach

- `builder_base_image` and `runtime_base_image` are optional `workflow_dispatch` inputs in deploy
- Values can be pinned to immutable digests (recommended for production)
- Defaults remain tag-based to avoid breaking immediate builds while rollout occurs
- Base-image refresh publishes stable rolling refs (`geo-base-stable`, `geo-base-latest`) alongside immutable run-scoped tags

## Consequences

### Positive

- Non-breaking adoption path
- Clear migration path to project-owned base images
- Better reproducibility controls via explicit base inputs
- Refresh automation now validates a dedicated `Dockerfile.base` artifact before publication
- Published project-owned base images use run-scoped immutable tags for traceability

### Trade-offs

- Full digest pinning policy enforcement is deferred to follow-up automation work (Issue #151)

## Benchmark Evidence

Measurement method:

- Source: GitHub Actions `Deploy Function App` workflow wall-clock duration
- Metric: `updatedAt - run_started_at` for successful runs
- Cutover marker for strategy rollout: commit `e4d3e1c0` (PR #178 stream)

Baseline (Option 1 - upstream-only direct dependency install):

- Cohort: 10 successful deploy runs before cutover
- Average duration: **9.29 minutes**

Candidate (Option 3 - hybrid, project-owned `geo-base-stable` consumed by deploy):

- Cohort: 3 successful deploy runs after cutover
- Average duration: **4.66 minutes**

Observed improvement:

- Average deploy duration reduced by **49.8%** relative to baseline
- Representative successful post-cutover run: `23023881403` (6.10 minutes)

Notes:

- Candidate cohorts include non-build deploy tasks (readiness and Event Grid reconciliation), so this is a conservative whole-workflow measure rather than an isolated Docker build-only benchmark.
- Option 2 (fully project-owned base) is operationally enabled by the refresh workflow publishing immutable run tags plus `geo-base-stable`/`geo-base-latest`; deploy now consumes those refs via explicit base image inputs.
