#!/usr/bin/env bash
# Print the real host path backing this container's /workspace mount, or
# nothing if we're not inside a Docker-outside-of-Docker (DooD) devcontainer.
#
# When `docker compose` runs from inside a devcontainer whose own /workspace
# is itself bind-mounted from the real host (DooD, e.g. the
# docker-outside-of-docker devcontainer feature + a forwarded docker.sock), a
# relative bind-mount source (".") resolves against THIS container's
# filesystem — meaningless to the real daemon reached via that socket, which
# silently mounts an empty directory instead. Callers substitute the real
# host path this script prints for their bind-mount sources.
#
# Usage: host_path="$(scripts/detect_dood_workspace.sh)"
set -euo pipefail

[[ -f /.dockerenv ]] || exit 0
command -v docker >/dev/null 2>&1 || exit 0

docker inspect "$(hostname)" \
  --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true
