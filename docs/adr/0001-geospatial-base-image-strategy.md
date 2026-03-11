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

- Keep secure defaults pointing at official Azure Functions Python image
- Make both builder and runtime base images explicit build inputs
- Allow controlled pinning (tag or digest) through workflow variables
- Prepare path for project-owned GHCR base image rollout without breaking current deploys

## Provenance

- Base image source defaults to Microsoft Azure Functions image
- Image provenance remains traceable through commit-SHA tagged final images in GHCR
- Build metadata labels remain attached in deploy workflow

## Pinning Approach

- `BUILDER_BASE_IMAGE` and `RUNTIME_BASE_IMAGE` are workflow-controlled inputs
- Values can be pinned to immutable digests (recommended for production)
- Defaults remain tag-based to avoid breaking immediate builds while rollout occurs

## Consequences

### Positive

- Non-breaking adoption path
- Clear migration path to project-owned base images
- Better reproducibility controls via explicit base inputs
- Refresh automation now validates a dedicated `Dockerfile.base` artifact before publication
- Published project-owned base images use run-scoped immutable tags for traceability

### Trade-offs

- Full digest pinning policy enforcement is deferred to follow-up automation work (Issue #151)
- Benchmarking comparisons will be captured in CI/deploy run history as rollout continues
