#!/usr/bin/env bash
# Run the CI quality gates locally the SAME way CI does (#1086): inside the
# dev container image. This is the local equivalent of the ci.yml resolve-image
# + lint/test/integration jobs and exists so the containerised workflow can be
# validated without a CI round trip (catches "works on host, missing in image"
# bugs like a missing `make`, or Azurite API-version mismatches).
#
# Usage:
#   scripts/ci_local.sh [lint|test|integration|all]   (default: all)
#
# Env:
#   DEV_IMAGE   image tag to build/use (default: treesight-dev:local)
#   NO_BUILD=1  skip the image build and use DEV_IMAGE as-is
set -euo pipefail

cd "$(dirname "$0")/.."

DEV_IMAGE="${DEV_IMAGE:-treesight-dev:local}"
COMPOSE_PROJECT="canopex-ci-local"
COMPOSE=(docker compose -p "${COMPOSE_PROJECT}" -f docker-compose.yml)
TARGET="${1:-all}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

cleanup() {
  # Tear down the compose azurite/ci-gate started for the integration gate.
  "${COMPOSE[@]}" --profile ci down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── Build the dev image (mirrors dev-image.yml) ────────────────────────────
if [[ "${NO_BUILD:-0}" != "1" ]]; then
  log "Building ${DEV_IMAGE} from Dockerfile.dev"
  UVLOCK_SHA="$(sha256sum uv.lock | cut -d' ' -f1)"
  docker build -f Dockerfile.dev \
    --build-arg UVLOCK_SHA="${UVLOCK_SHA}" \
    -t "${DEV_IMAGE}" .
fi

# lint/test mount the checkout at /workspace and rely on deps baked into
# /opt/venv (outside the mount). UV_NO_SYNC=1 mirrors the CI env so `uv run`
# never re-resolves against the network.
run_gate() {
  docker run --rm \
    -e UV_NO_SYNC=1 \
    -v "${PWD}:/workspace" -w /workspace \
    "$@"
}

run_lint() {
  log "Gate: lint (inside ${DEV_IMAGE})"
  run_gate "${DEV_IMAGE}" make lint
}

run_test() {
  log "Gate: test (inside ${DEV_IMAGE})"
  local test_env=(
    -e AzureWebJobsStorage="UseDevelopmentStorage=true"  # pragma: allowlist secret
    -e DEMO_VALET_TOKEN_SECRET="ci-test-secret"  # pragma: allowlist secret
    -e CIAM_AUTHORITY="https://canopex.ciamlogin.com"
    -e CIAM_TENANT_ID="ci-test-tenant"
    -e CIAM_API_AUDIENCE="api://ci-test-audience"
  )
  run_gate "${test_env[@]}" "${DEV_IMAGE}" make test
}

run_integration() {
  log "Gate: integration (Azurite via docker compose, inside ${DEV_IMAGE})"
  # Reuse the maintained azurite service (correct --skipApiVersionCheck/--loose
  # flags + healthcheck). depends_on: service_healthy guarantees ordering; the
  # ci-gate service runs the suite inside the dev image on the same network.
  CI_GATE_IMAGE="${DEV_IMAGE}" "${COMPOSE[@]}" --profile ci run --rm ci-gate make test-int
}

case "${TARGET}" in
  lint)        run_lint ;;
  test)        run_test ;;
  integration) run_integration ;;
  all)         run_lint; run_test; run_integration ;;
  *) echo "Unknown target: ${TARGET} (expected lint|test|integration|all)" >&2; exit 2 ;;
esac

log "Local containerised gates passed: ${TARGET}"
