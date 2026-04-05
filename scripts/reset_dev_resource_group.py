"""Delete app-managed resources from a resource group while preserving bootstrap resources."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_POLL_INTERVAL_SECONDS = 15


def resource_group_exists(resource_group: str) -> bool:
    """Return whether the target resource group exists."""
    completed = subprocess.run(
        ["az", "group", "exists", "--name", resource_group],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().lower() == "true"


def run_az_json(args: list[str]) -> Any:
    """Run an Azure CLI command that returns JSON."""
    completed = subprocess.run(
        ["az", *args, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}


def list_resources(resource_group: str) -> list[dict[str, Any]]:
    """Return all resources in the resource group."""
    payload = run_az_json(["resource", "list", "--resource-group", resource_group])
    if not isinstance(payload, list):
        raise RuntimeError(f"Expected a list of resources for {resource_group}")
    return payload


def is_preserved(resource: dict[str, Any], preserve_types: set[str]) -> bool:
    """Return whether the resource type should be preserved during reset."""
    resource_type = resource.get("type")
    return isinstance(resource_type, str) and resource_type in preserve_types


def deletable_resources(resources: list[dict[str, Any]], preserve_types: set[str]) -> list[dict[str, Any]]:
    """Return resources that should be deleted for a clean-slate app reset."""
    return [resource for resource in resources if not is_preserved(resource, preserve_types)]


def delete_resources(resources: list[dict[str, Any]]) -> None:
    """Delete each resource individually via Azure CLI."""
    for resource in resources:
        resource_id = resource.get("id")
        name = resource.get("name", "<unknown>")
        if not isinstance(resource_id, str) or not resource_id:
            raise RuntimeError(f"Resource {name} is missing an id")
        print(f"Deleting {name} ({resource.get('type', 'unknown')})")
        subprocess.run(["az", "resource", "delete", "--ids", resource_id], check=True)


def wait_for_reset(
    *,
    resource_group: str,
    preserve_types: set[str],
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> list[dict[str, Any]]:
    """Wait until only preserved resources remain in the resource group."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        resources = list_resources(resource_group)
        remaining = deletable_resources(resources, preserve_types)
        if not remaining:
            return resources
        names = ", ".join(str(resource.get("name", "<unknown>")) for resource in remaining)
        print(f"Waiting for dev reset to finish. Remaining app resources: {names}")
        time.sleep(poll_interval_seconds)
    names = ", ".join(
        str(resource.get("name", "<unknown>"))
        for resource in deletable_resources(list_resources(resource_group), preserve_types)
    )
    raise TimeoutError(f"Timed out waiting for dev reset. Remaining app resources: {names}")


def reset_resource_group(
    *,
    resource_group: str,
    preserve_types: set[str],
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> list[dict[str, Any]]:
    """Reset app-managed resources while preserving shared/bootstrap resources."""
    if not resource_group_exists(resource_group):
        print(f"Resource group {resource_group} does not exist; nothing to reset.")
        return []

    resources = list_resources(resource_group)
    to_delete = deletable_resources(resources, preserve_types)
    if not to_delete:
        print(f"No app-managed resources found in {resource_group}; nothing to reset.")
        return resources

    delete_resources(to_delete)
    return wait_for_reset(
        resource_group=resource_group,
        preserve_types=preserve_types,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", required=True, help="Azure resource group name")
    parser.add_argument(
        "--preserve-type",
        action="append",
        default=[],
        help="Azure resource type to preserve during reset; may be provided multiple times",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum time to wait for resource deletion",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Polling interval while waiting for resources to delete",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preserved = set(args.preserve_type)
    reset_resource_group(
        resource_group=args.resource_group,
        preserve_types=preserved,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    if preserved:
        print("Dev resource reset completed while preserving resource types:", ", ".join(sorted(preserved)))
    else:
        print("Dev resource reset completed")


if __name__ == "__main__":
    main()