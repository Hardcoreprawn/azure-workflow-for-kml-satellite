#!/usr/bin/env bash
# Run the CI quality gates locally the SAME way CI does: inside the dev
# container image for lint/test/integration (#1086), and directly on the
# host for pipeline-e2e (ADR 0005 amendment, #1215/#1218 — the Durable Task
# Framework's storage provider needs Azurite at the caller's own localhost,
# which a sibling container breaks). This is the local equivalent of the
# ci.yml jobs, letting the containerised/host workflow be validated without a
# CI round trip (catches "works on host, missing in image" bugs like a
# missing `make`, or Azurite API-version mismatches).
#
# Usage:
#   scripts/ci_local.sh [lint|test|integration|pipeline-e2e|all]   (default: all)
#
# Env:
#   DEV_IMAGE   image tag to build/use for lint/test/integration
#               (default: treesight-dev:local)
#   NO_BUILD=1  skip the lint/test/integration image build and use DEV_IMAGE
#               as-is (does not affect pipeline-e2e, which runs on the host)
set -euo pipefail

cd "$(dirname "$0")/.."

# Docker-outside-of-Docker detection: when `docker compose` here talks to a
# remote/sibling daemon (e.g. Docker Desktop reached via a bind-mounted host
# socket from inside a devcontainer), a relative bind-mount source (`.`)
# resolves against THIS container's filesystem, which the real daemon can't
# see — it silently mounts an empty directory instead. Detect it and pass the
# real host path through CI_GATE_WORKSPACE so docker-compose.yml can use it.
# Only matters for `integration` (ci-gate) — pipeline-e2e doesn't use ci-gate.
if [[ -z "${CI_GATE_WORKSPACE:-}" ]]; then
  host_path="$(scripts/detect_dood_workspace.sh)"
  if [[ -n "${host_path}" ]]; then
    export CI_GATE_WORKSPACE="${host_path}"
    echo "Detected Docker-outside-of-Docker — using host path ${CI_GATE_WORKSPACE} for the ci-gate bind mount"
  fi
fi

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
  log "Building ${DEV_IMAGE} from Dockerfile.dev (--target dev)"
  source .github/image-config.env
  UVLOCK_SHA="$(sha256sum uv.lock | cut -d' ' -f1)"
  docker build -f Dockerfile.dev --target dev \
    --build-arg UV_VERSION="${UV_VERSION}" \
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

run_pipeline_e2e() {
  log "Gate: pipeline e2e (bare host — see ADR 0005 amendment, #1215/#1218)"
  # Runs directly on the host, not inside a container: the Durable Task
  # Framework's storage provider hard-resolves the well-known Azurite
  # account name to 127.0.0.1, only correct when Azurite is reachable at
  # the caller's own localhost — true here, false for a sibling container.
  uv sync --all-extras
  command -v func >/dev/null 2>&1 || bash scripts/setup_func_tools.sh
  docker compose up -d azurite
  uv run python scripts/init_storage.py
  make test-pipeline-local
}

case "${TARGET}" in
  lint)         run_lint ;;
  test)         run_test ;;
  integration)  run_integration ;;
  pipeline-e2e) run_pipeline_e2e ;;
  all)          run_lint; run_test; run_integration; run_pipeline_e2e ;;
  *) echo "Unknown target: ${TARGET} (expected lint|test|integration|pipeline-e2e|all)" >&2; exit 2 ;;
esac

log "Local containerised gates passed: ${TARGET}"
