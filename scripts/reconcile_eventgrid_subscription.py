"""Create or update the Event Grid webhook subscription for the blob trigger."""

from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any
from urllib.parse import urlencode

DEFAULT_FUNCTION_NAME = "blob_trigger"
DEFAULT_SUBSCRIPTION_NAME = "evgs-kml-upload"
DEFAULT_EVENT_TYPE = "Microsoft.Storage.BlobCreated"
DEFAULT_SUBJECT_SUFFIX = ".kml"


def select_eventgrid_key(payload: dict[str, Any]) -> str:
    """Return the best available Event Grid system key from function host keys."""
    system_keys = payload.get("systemKeys") or {}
    if not isinstance(system_keys, dict):
        system_keys = {}

    key = (
        system_keys.get("eventgrid_extension")
        or system_keys.get("eventgridextensionconfig_extension")
        or payload.get("masterKey")
    )
    if not isinstance(key, str) or not key:
        raise RuntimeError("Could not resolve an Event Grid webhook key for the function app")
    return key


def build_eventgrid_endpoint(hostname: str, function_name: str, function_key: str) -> str:
    """Build the runtime webhook endpoint for Event Grid delivery."""
    query = urlencode({"functionName": function_name, "code": function_key})
    return f"https://{hostname}/runtime/webhooks/eventgrid?{query}"


def run_az_json(args: list[str]) -> dict[str, Any]:
    """Run an Azure CLI command that returns JSON."""
    completed = subprocess.run(
        ["az", *args, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}


def subscription_exists(
    resource_group: str, system_topic_name: str, subscription_name: str
) -> bool:
    """Return whether the Event Grid subscription already exists."""
    completed = subprocess.run(
        [
            "az",
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
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def build_subscription_command(
    *,
    action: str,
    resource_group: str,
    system_topic_name: str,
    subscription_name: str,
    endpoint: str,
) -> list[str]:
    """Build the Azure CLI command for creating or updating the webhook subscription."""
    command = [
        "az",
        "eventgrid",
        "system-topic",
        "event-subscription",
        action,
        "--resource-group",
        resource_group,
        "--system-topic-name",
        system_topic_name,
        "--name",
        subscription_name,
        "--endpoint",
        endpoint,
        "--endpoint-type",
        "webhook",
        "--included-event-types",
        DEFAULT_EVENT_TYPE,
        "--subject-ends-with",
        DEFAULT_SUBJECT_SUFFIX,
    ]
    if action == "create":
        command.extend(
            [
                "--max-delivery-attempts",
                "30",
                "--event-ttl",
                "1440",
                "--max-events-per-batch",
                "1",
                "--preferred-batch-size-in-kilobytes",
                "64",
            ]
        )
    command.extend(["--only-show-errors", "-o", "none"])
    return command


def reconcile_subscription(
    *,
    resource_group: str,
    function_app: str,
    hostname: str,
    system_topic_name: str,
    subscription_name: str,
    function_name: str,
) -> str:
    """Create or update the Event Grid webhook subscription and return the endpoint."""
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
    endpoint = build_eventgrid_endpoint(
        hostname=hostname,
        function_name=function_name,
        function_key=select_eventgrid_key(keys),
    )

    action = (
        "update"
        if subscription_exists(resource_group, system_topic_name, subscription_name)
        else "create"
    )
    subprocess.run(
        build_subscription_command(
            action=action,
            resource_group=resource_group,
            system_topic_name=system_topic_name,
            subscription_name=subscription_name,
            endpoint=endpoint,
        ),
        check=True,
    )
    return endpoint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resource-group", required=True, help="Azure resource group containing the system topic"
    )
    parser.add_argument("--function-app", required=True, help="Azure Function App name")
    parser.add_argument("--hostname", required=True, help="Function App default hostname")
    parser.add_argument("--system-topic-name", required=True, help="Event Grid system topic name")
    parser.add_argument(
        "--subscription-name",
        default=DEFAULT_SUBSCRIPTION_NAME,
        help=f"Event Grid subscription name (default: {DEFAULT_SUBSCRIPTION_NAME})",
    )
    parser.add_argument(
        "--function-name",
        default=DEFAULT_FUNCTION_NAME,
        help=f"Indexed Event Grid trigger function name (default: {DEFAULT_FUNCTION_NAME})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    endpoint = reconcile_subscription(
        resource_group=args.resource_group,
        function_app=args.function_app,
        hostname=args.hostname,
        system_topic_name=args.system_topic_name,
        subscription_name=args.subscription_name,
        function_name=args.function_name,
    )
    redacted = endpoint.split("&code=")[0] + "&code=***REDACTED***"
    print(f"Event Grid subscription reconciled -> {redacted}")


if __name__ == "__main__":
    main()
