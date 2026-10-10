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
api_verifier_compose=("${compose[@]}" -f "$root/docker-compose.api-verifier.yml")

action="${1:-status}"
case "$action" in
    prepare|up|rebuild|storage|down|clean|status|logs|config|api-verifier) ;;
    *) echo "Usage: bash scripts/dev_stack.sh {prepare|up|rebuild|storage|down|clean|status|logs|config|api-verifier}" >&2; exit 2 ;;
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
if [[ "$action" == "prepare" ]]; then
    # If the editor's base image was pruned, the Dev Containers CLI tries to pull it; drop the stopped container so it rebuilds.
    editor_image="$("${compose[@]}" config --images devcontainer 2>/dev/null || true)"
    if [[ -n "$editor_image" ]] && ! docker image inspect "$editor_image" >/dev/null 2>&1; then
        echo "Devcontainer image $editor_image is missing; removing the stopped devcontainer so it is rebuilt."
        "${compose[@]}" rm --force devcontainer
    fi
    # The relay's build context is a host path, so in-editor `up` cannot build it.
    relay_image="$("${compose[@]}" config --images event-grid-relay 2>/dev/null || true)"
    if [[ -n "$relay_image" ]] && ! docker image inspect "$relay_image" >/dev/null 2>&1; then
        "${compose[@]}" build event-grid-relay
    fi
    exec "${compose[@]}" rm --force "${services[@]}"
fi

stop_stack() {
    if [[ "${CANOPEX_DEVCONTAINER:-}" == "1" || "$action" == "storage" ]]; then
        "${compose[@]}" stop --timeout "${DEV_STOP_TIMEOUT:-20}" "${services[@]}" || return "$?"
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
        options=()
        # Build host-only contexts before installing the startup cleanup trap:
        # a failed preflight must not tear down an already healthy project.
        if [[ "$action" == "up" && "${CANOPEX_DEVCONTAINER:-}" != "1" ]]; then
            "${compose[@]}" build event-grid-relay
        elif [[ "$action" == "rebuild" ]]; then
            build_services=("${services[@]}")
            if [[ "${CANOPEX_DEVCONTAINER:-}" == "1" ]]; then
                filtered_services=()
                for service in "${build_services[@]}"; do
                    if [[ "$service" != "event-grid-relay" ]]; then
                        filtered_services+=("$service")
                    fi
                done
                build_services=("${filtered_services[@]}")
            fi
            "${compose[@]}" build "${build_services[@]}"
        fi
        trap cleanup_failed_start EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        if [[ "$action" == "storage" ]]; then
            services=(azurite init-storage)
        fi
        "${compose[@]}" rm --force "${services[@]}"
        options=()
        if [[ "$action" == "rebuild" ]]; then
            options+=(--force-recreate)
        fi
        if [[ "$action" == "storage" ]]; then
            "${compose[@]}" up -d --wait --wait-timeout "${DEV_WAIT_TIMEOUT:-240}" azurite
            "${compose[@]}" run --rm --no-deps init-storage
        else
            init_status="$("${compose[@]}" ps --all --format '{{.Service}} {{.State}} {{.ExitCode}}' init-storage 2>/dev/null || true)"
            if [[ "$init_status" =~ ^init-storage[[:space:]]+(exited|dead)[[:space:]]+[1-9][0-9]*$ ]]; then
                "${compose[@]}" rm --force init-storage >/dev/null 2>&1 || true
            fi
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
    api-verifier)
        verifier_active=0
        restore_api_verifier() {
            result=$?
            trap - EXIT INT TERM
            if [[ "$verifier_active" == 1 ]]; then
                "${api_verifier_compose[@]}" stop --timeout 10 local-ciam || result=1
                "${api_verifier_compose[@]}" rm --force local-ciam || result=1
                echo "Restoring the standard development auth configuration."
                if ! "${compose[@]}" up -d --wait --wait-timeout "${DEV_WAIT_TIMEOUT:-240}" --force-recreate func orch; then
                    echo "ERROR: Could not restore the standard func/orch services." >&2
                    result=1
                fi
            fi
            exit "$result"
        }
        verifier_active=1
        trap restore_api_verifier EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        "${api_verifier_compose[@]}" up -d --wait --wait-timeout "${DEV_WAIT_TIMEOUT:-240}" --force-recreate local-ciam func orch
        VERIFY_COMPUTE_BASE="http://func" \
            VERIFY_ORCH_BASE="http://orch" \
            VERIFY_WEB_BASE="http://web" \
            VERIFY_LOCAL_CIAM_TOKEN_URL="http://local-ciam:8080/tokens" \
            uv run python scripts/verify_local_stack.py --api-only
        ;;
esac
