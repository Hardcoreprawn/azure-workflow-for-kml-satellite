"""Validate the dev infra gate after a clean-slate redeploy or manual deploy."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any

try:
    from scripts import reconcile_eventgrid_subscription as reconcile
except ImportError:  # pragma: no cover - direct script execution path
    import reconcile_eventgrid_subscription as reconcile


DEFAULT_TIMEOUT_SECONDS = 10


def run_az_json(args: list[str]) -> Any:
    return reconcile.run_az_json(args)


def find_first_value(payload: Any, key: str) -> str | None:
    """Return the first string value for *key* found in a nested payload."""
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        for child in payload.values():
            found = find_first_value(child, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for child in payload:
            found = find_first_value(child, key)
            if found is not None:
                return found
    return None


def fetch_json(url: str) -> dict[str, Any]:
    """Fetch a JSON document and require HTTP 200."""
    with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Expected HTTP 200 from {url}, got {response.status}")
        return json.load(response)


def resolve_workspace_name(resource_group: str, workspace_name: str | None) -> str:
    """Resolve the target Log Analytics workspace name for the resource group."""
    if workspace_name:
        return workspace_name

    payload = run_az_json(
        ["monitor", "log-analytics", "workspace", "list", "--resource-group", resource_group]
    )
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(
            "Could not resolve a single Log Analytics workspace automatically; pass --workspace-name explicitly"
        )
    name = payload[0].get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError("Resolved Log Analytics workspace is missing a name")
    return name


def validate_gate(
    *,
    resource_group: str,
    function_app: str,
    hostname: str,
    system_topic_name: str,
    subscription_name: str,
    function_name: str,
    expected_daily_cap_gb: float,
    workspace_name: str | None,
) -> None:
    """Validate runtime health, Event Grid wiring, and Log Analytics cap."""
    health = fetch_json(f"https://{hostname}/api/health")
    readiness = fetch_json(f"https://{hostname}/api/readiness")
    if health.get("status") != "healthy":
        raise RuntimeError(f"Health endpoint returned unexpected payload: {health}")
    if readiness.get("status") != "ready":
        raise RuntimeError(f"Readiness endpoint returned unexpected payload: {readiness}")

    keys = run_az_json(
        [
            "functionapp",
            "keys",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            function_app,
        ]
    )
    expected_endpoint = reconcile.build_eventgrid_endpoint(
        hostname=hostname,
        function_name=function_name,
        function_key=reconcile.select_eventgrid_key(keys),
    )
    subscription = run_az_json(
        [
            "eventgrid",
            "system-topic",
            "event-subscription",
            "show",
            "--resource-group",
            resource_group,
            "--system-topic-name",
            system_topic_name,
            "--name",
            subscription_name,
        ]
    )
    actual_endpoint = find_first_value(subscription, "endpointUrl")
    if actual_endpoint != expected_endpoint:
        raise RuntimeError(
            "Event Grid subscription endpoint does not match the current function hostname/key"
        )

    workspace = run_az_json(
        [
            "monitor",
            "log-analytics",
            "workspace",
            "show",
            "--resource-group",
            resource_group,
            "--workspace-name",
            resolve_workspace_name(resource_group, workspace_name),
        ]
    )
    capping = workspace.get("workspaceCapping") or {}
    actual_cap = capping.get("dailyQuotaGb")
    if actual_cap is None:
        raise RuntimeError("Log Analytics workspace is missing workspaceCapping.dailyQuotaGb")
    if float(actual_cap) > expected_daily_cap_gb:
        raise RuntimeError(
            f"Log Analytics daily quota is {actual_cap} GB, expected <= {expected_daily_cap_gb} GB"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", required=True, help="Azure resource group name")
    parser.add_argument("--function-app", required=True, help="Azure Function App name")
    parser.add_argument("--hostname", required=True, help="Function App hostname")
    parser.add_argument("--system-topic-name", required=True, help="Event Grid system topic name")
    parser.add_argument(
        "--subscription-name",
        default=reconcile.DEFAULT_SUBSCRIPTION_NAME,
        help="Event Grid subscription name",
    )
    parser.add_argument(
        "--function-name",
        default=reconcile.DEFAULT_FUNCTION_NAME,
        help="Event Grid trigger function name",
    )
    parser.add_argument(
        "--expected-daily-cap-gb",
        type=float,
        required=True,
        help="Expected maximum Log Analytics daily quota in GB",
    )
    parser.add_argument(
        "--workspace-name", default=None, help="Optional Log Analytics workspace name"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_gate(
        resource_group=args.resource_group,
        function_app=args.function_app,
        hostname=args.hostname,
        system_topic_name=args.system_topic_name,
        subscription_name=args.subscription_name,
        function_name=args.function_name,
        expected_daily_cap_gb=args.expected_daily_cap_gb,
        workspace_name=args.workspace_name,
    )
    print("Infra gate validated successfully")


if __name__ == "__main__":
    main()
