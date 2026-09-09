#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source .github/image-config.env
export UV_VERSION
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-canopex-dev}"

if [[ "${CANOPEX_DEVCONTAINER:-}" == "1" && -z "${DEV_WORKSPACE:-}" ]]; then
    echo "ERROR: DEV_WORKSPACE must identify the host checkout inside the devcontainer." >&2
    exit 1
fi
export DEV_WORKSPACE="${DEV_WORKSPACE:-$root}"

compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --project-directory "$root"
    -f "$root/docker-compose.yml" -f "$root/docker-compose.override.yml"
    -f "$root/.devcontainer/docker-compose.yml")
if [[ "${CANOPEX_DEV_GPU:-0}" == "1" ]]; then
    compose+=(-f "$root/.devcontainer/docker-compose.gpu.yml")
fi

action="${1:-status}"
case "$action" in
    up|rebuild|storage|down|clean|status|logs|config) ;;
    *) echo "Usage: bash scripts/dev_stack.sh {up|rebuild|storage|down|clean|status|logs|config}" >&2; exit 2 ;;
esac
if [[ "$action" == "config" ]]; then
    exec "${compose[@]}" config --quiet
fi
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is unavailable. Start Docker and check access to its socket/context." >&2
    exit 1
fi
service_names="$("${compose[@]}" config --services)"
mapfile -t services < <(printf '%s\n' "$service_names" | sed '/^devcontainer$/d')

stop_stack() {
    if [[ "${CANOPEX_DEVCONTAINER:-}" == "1" || "$action" == "storage" ]]; then
        "${compose[@]}" stop --timeout "${DEV_STOP_TIMEOUT:-20}" "${services[@]}"
        "${compose[@]}" rm --force "${services[@]}"
    else
        "${compose[@]}" down --timeout "${DEV_STOP_TIMEOUT:-20}" --remove-orphans
    fi
}

cleanup_failed_start() {
    result=$?
    trap - EXIT INT TERM
    if [[ "$result" != "0" ]]; then
        echo "ERROR: Stack startup failed ($result); stopping project $COMPOSE_PROJECT_NAME." >&2
        "${compose[@]}" logs --no-color --tail=60 "${services[@]}" || echo "Could not retrieve logs." >&2
        stop_stack || echo "ERROR: Cleanup failed. Retry make dev-down after restoring Docker access." >&2
    fi
    exit "$result"
}

case "$action" in
    up|rebuild|storage)
        trap cleanup_failed_start EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        options=()
        if [[ "$action" == "rebuild" ]]; then
            "${compose[@]}" build "${services[@]}"
            options+=(--force-recreate)
        fi
        if [[ "$action" == "storage" ]]; then
            services=(azurite init-storage)
            "${compose[@]}" up -d --wait --wait-timeout "${DEV_WAIT_TIMEOUT:-240}" azurite
            "${compose[@]}" run --rm --no-deps init-storage
        else
            "${compose[@]}" up -d --wait --wait-timeout "${DEV_WAIT_TIMEOUT:-240}" "${options[@]}" "${services[@]}"
        fi
        trap - EXIT INT TERM
        echo "Project $COMPOSE_PROJECT_NAME is ready. Use make dev-status, make dev-logs, or make dev-down."
        ;;
    down) stop_stack ;;
    clean)
        if [[ "${DEV_RESET_DATA:-}" != "1" ]]; then
            echo "ERROR: Data reset deletes local storage and downloaded models. Run DEV_RESET_DATA=1 make clean." >&2
            exit 1
        fi
        if [[ "${CANOPEX_DEVCONTAINER:-}" == "1" ]]; then
            echo "ERROR: Close the devcontainer, then run DEV_RESET_DATA=1 make clean on the host." >&2
            exit 1
        fi
        "${compose[@]}" down --timeout "${DEV_STOP_TIMEOUT:-20}" --volumes --remove-orphans
        ;;
    status) "${compose[@]}" ps --all ;;
    logs) "${compose[@]}" logs --follow --tail=50 "${services[@]}" ;;
esac