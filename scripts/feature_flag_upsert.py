#!/usr/bin/env python3
"""Upsert a feature flag document into the ``feature_flags`` Cosmos container.

Usage::

    python scripts/feature_flag_upsert.py \\
        --feature scheduled-monitoring-v2 \\
        --status preview_only \\
        [--rollout-pct 0] \\
        [--kill-switch] \\
        [--allow-anonymous] \\
        [--description "Next iteration of scheduled monitoring"] \\
        [--updated-by "operator-name"]

Status values: off | preview_only | percentage_rollout | on | blocked

Authentication: Uses DefaultAzureCredential. Run ``az login`` locally or
ensure the executing identity has the Cosmos DB Built-in Data Contributor role.

Required environment variables::

    COSMOS_ENDPOINT  — e.g. https://cosmos-kmlsat-prd.documents.azure.com:443/
    COSMOS_DATABASE_NAME — e.g. treesight
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

VALID_STATUSES = frozenset(["off", "preview_only", "percentage_rollout", "on", "blocked"])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Upsert a Canopex feature flag.")
    p.add_argument("--feature", required=True, help="Feature name (slug, e.g. my-feature-v2)")
    p.add_argument(
        "--status",
        required=True,
        choices=sorted(VALID_STATUSES),
        help="Desired rollout status",
    )
    p.add_argument("--rollout-pct", type=int, default=0, help="Percentage (0-100, default 0)")
    p.add_argument("--kill-switch", action="store_true", help="Activate kill switch")
    p.add_argument(
        "--allow-anonymous", action="store_true", help="Allow anonymous (unauthenticated) access"
    )
    p.add_argument("--description", default="", help="Human-readable description")
    p.add_argument(
        "--updated-by", default="operator", help="Identity performing the update (audit field)"
    )
    p.add_argument("--dry-run", action="store_true", help="Print the document; do not write")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    db_name = os.environ.get("COSMOS_DATABASE_NAME", "treesight")
    if not endpoint:
        print("ERROR: COSMOS_ENDPOINT environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    if not 0 <= args.rollout_pct <= 100:
        print("ERROR: --rollout-pct must be between 0 and 100.", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "id": args.feature,
        "feature_name": args.feature,
        "status": args.status,
        "kill_switch": args.kill_switch,
        "preview_enabled": args.status == "preview_only",
        "rollout_pct": args.rollout_pct,
        "allow_anonymous": args.allow_anonymous,
        "description": args.description,
        "updated_at": now,
        "updated_by": args.updated_by,
    }

    if args.dry_run:
        print(json.dumps(doc, indent=2))
        return

    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential)
    db = client.get_database_client(db_name)
    container = db.get_container_client("feature_flags")
    result = container.upsert_item(doc)
    print(f"Upserted: {result['id']} — status={result['status']}")


if __name__ == "__main__":
    main()
