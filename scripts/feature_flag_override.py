#!/usr/bin/env python3
"""Manage per-user feature flag overrides in the ``feature_flag_overrides`` container.

Usage::

    # Grant preview access
    python scripts/feature_flag_override.py \\
        --user-id user@example.com \\
        --feature scheduled-monitoring-v2 \\
        --enable \\
        [--updated-by "operator-name"]

    # Revoke preview access
    python scripts/feature_flag_override.py \\
        --user-id user@example.com \\
        --feature scheduled-monitoring-v2 \\
        --disable

    # Remove the override entirely (revert to flag-level status)
    python scripts/feature_flag_override.py \\
        --user-id user@example.com \\
        --feature scheduled-monitoring-v2 \\
        --clear

Required environment variables::

    COSMOS_ENDPOINT       — e.g. https://cosmos-kmlsat-prd.documents.azure.com:443/
    COSMOS_DATABASE_NAME  — e.g. treesight
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Manage Canopex feature flag overrides.")
    p.add_argument("--user-id", required=True, help="User ID to override")
    p.add_argument("--feature", required=True, help="Feature name (slug)")

    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", action="store_true", help="Enable feature for this user")
    action.add_argument("--disable", action="store_true", help="Disable feature for this user")
    action.add_argument(
        "--clear", action="store_true", help="Remove override (reverts to flag-level status)"
    )

    p.add_argument(
        "--updated-by", default="operator", help="Identity performing the update (audit field)"
    )
    p.add_argument("--dry-run", action="store_true", help="Print the resulting document; no write")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    db_name = os.environ.get("COSMOS_DATABASE_NAME", "treesight")
    if not endpoint:
        print("ERROR: COSMOS_ENDPOINT environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    from azure.cosmos import CosmosClient
    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential)
    db = client.get_database_client(db_name)
    container = db.get_container_client("feature_flag_overrides")

    # Fetch existing doc (or start fresh)
    try:
        doc = container.read_item(item=args.user_id, partition_key=args.user_id)
    except CosmosResourceNotFoundError:
        doc = {
            "id": args.user_id,
            "user_id": args.user_id,
            "features": {},
        }

    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["updated_at"] = now
    doc["updated_by"] = args.updated_by

    if args.clear:
        doc["features"].pop(args.feature, None)
        action_label = "cleared"
    elif args.enable:
        doc["features"][args.feature] = {"enabled": True}
        action_label = "enabled"
    else:  # --disable
        doc["features"][args.feature] = {"enabled": False}
        action_label = "disabled"

    if args.dry_run:
        import json

        print(json.dumps(doc, indent=2))
        return

    container.upsert_item(doc)
    print(f"{action_label} feature '{args.feature}' for user '{args.user_id}'")


if __name__ == "__main__":
    main()
