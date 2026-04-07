#!/usr/bin/env python3
"""Collect observed Azure usage metrics and generate an Infracost usage file.

Queries Azure Monitor and Resource Graph to capture actual resource
consumption, then writes ``infra/tofu/infracost-usage.yml`` with values
that Infracost uses for usage-based cost estimation.

Prerequisites (one-time)::

    pip install azure-identity azure-monitor-query azure-mgmt-monitor azure-mgmt-storage

Usage::

    # Last 31 days (default)
    python scripts/collect_infracost_usage.py

    # Last 7 days
    python scripts/collect_infracost_usage.py --lookback 7

    # Dry-run (print values without writing file)
    python scripts/collect_infracost_usage.py --dry-run

The script authenticates via ``DefaultAzureCredential`` — either
``az login`` locally or managed identity / OIDC in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.mgmt.storage import StorageManagementClient
    from azure.monitor.query import MetricAggregationType, MetricsQueryClient
except ImportError:
    print(
        "Missing Azure SDK packages. Install with:\n"
        "  pip install azure-identity azure-monitor-query "
        "azure-mgmt-monitor azure-mgmt-storage",
        file=sys.stderr,
    )
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
USAGE_FILE = REPO_ROOT / "infra" / "tofu" / "infracost-usage.yml"

# Resource IDs are discovered from ``tofu output -json`` or tags.
# For now, read from a well-known tag query or env-var override.


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--lookback",
        type=int,
        default=31,
        choices=[1, 3, 7, 14, 31],
        help="Lookback window in days (default: 31).",
    )
    p.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID.",
    )
    p.add_argument(
        "--resource-group",
        required=True,
        help="Resource group name containing the infrastructure.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print collected values without writing the usage file.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=USAGE_FILE,
        help=f"Output path (default: {USAGE_FILE}).",
    )
    return p.parse_args()


# ── Metric collectors ────────────────────────────────────────


def _query_metric(
    client: MetricsQueryClient,
    resource_uri: str,
    metric_name: str,
    aggregation: MetricAggregationType,
    start: datetime,
    end: datetime,
) -> float | None:
    """Query a single Azure Monitor metric, return the aggregated value."""
    try:
        response = client.query_resource(
            resource_uri,
            metric_names=[metric_name],
            timespan=(start, end),
            aggregations=[aggregation],
        )
    except Exception as exc:
        print(f"  ⚠ metric query failed for {metric_name}: {exc}", file=sys.stderr)
        return None

    for metric in response.metrics:
        for ts in metric.timeseries:
            total = 0.0
            for dp in ts.data:
                val = getattr(dp, aggregation.value.lower(), None) or getattr(dp, "total", None)
                if val is not None:
                    total += val
            if total > 0:
                return total
    return 0.0


def collect_log_analytics_ingestion(
    client: MetricsQueryClient,
    resource_uri: str,
    start: datetime,
    end: datetime,
    lookback_days: int,
) -> float:
    """Return monthly data ingestion in GB for Log Analytics workspace."""
    total_bytes = _query_metric(
        client, resource_uri, "IngestionVolumeMB", MetricAggregationType.TOTAL, start, end
    )
    if total_bytes is None:
        return 0.5  # fallback default
    # Convert MB over the lookback window to monthly GB estimate.
    daily_avg_mb = total_bytes / lookback_days
    monthly_gb = (daily_avg_mb * 30) / 1024
    return round(monthly_gb, 3)


def collect_storage_used_gb(
    storage_client: StorageManagementClient,
    resource_group: str,
    account_name: str,
) -> float:
    """Return current used capacity in GB from the storage account."""
    try:
        storage_client.storage_accounts.get_properties(resource_group, account_name)
        # The REST API doesn't directly expose used capacity inline.
        # Fall back to a reasonable estimate from blob service stats.
        return 1.0  # placeholder — real implementation uses metrics below
    except Exception:
        return 1.0


def collect_storage_metrics(
    client: MetricsQueryClient,
    resource_uri: str,
    start: datetime,
    end: datetime,
    lookback_days: int,
) -> dict:
    """Collect storage account usage metrics."""
    used_capacity = _query_metric(
        client, resource_uri, "UsedCapacity", MetricAggregationType.AVERAGE, start, end
    )
    transactions = _query_metric(
        client, resource_uri, "Transactions", MetricAggregationType.TOTAL, start, end
    )

    storage_gb = round((used_capacity or 0) / (1024**3), 3)
    monthly_ops = round(((transactions or 0) / lookback_days) * 30)

    return {
        "storage_gb": max(storage_gb, 0.01),
        "monthly_read_operations": monthly_ops,
    }


def collect_keyvault_operations(
    client: MetricsQueryClient,
    resource_uri: str,
    start: datetime,
    end: datetime,
    lookback_days: int,
) -> int:
    """Return estimated monthly secret operations for Key Vault."""
    total = _query_metric(
        client, resource_uri, "ServiceApiHit", MetricAggregationType.TOTAL, start, end
    )
    if total is None or total == 0:
        return 500  # fallback default
    daily_avg = total / lookback_days
    return round(daily_avg * 30)


def collect_cosmos_request_units(
    client: MetricsQueryClient,
    resource_uri: str,
    start: datetime,
    end: datetime,
    lookback_days: int,
) -> int:
    """Return estimated monthly request units for Cosmos DB."""
    total = _query_metric(
        client,
        resource_uri,
        "TotalRequestUnits",
        MetricAggregationType.TOTAL,
        start,
        end,
    )
    if total is None or total == 0:
        return 50000  # fallback default
    daily_avg = total / lookback_days
    return round(daily_avg * 30)


def collect_cosmos_storage_gb(
    client: MetricsQueryClient,
    resource_uri: str,
    start: datetime,
    end: datetime,
) -> float:
    """Return Cosmos DB data usage in GB."""
    total_bytes = _query_metric(
        client, resource_uri, "DataUsage", MetricAggregationType.AVERAGE, start, end
    )
    if total_bytes is None or total_bytes == 0:
        return 0.1
    return round(total_bytes / (1024**3), 3)


# ── Resource discovery ───────────────────────────────────────


def _find_resources(
    monitor_client: MonitorManagementClient,
    subscription_id: str,
    resource_group: str,
) -> dict:
    """Discover resource IDs by type within the resource group."""
    prefix = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers"
    # We construct known resource URIs based on naming conventions.
    # In practice, you could also use Resource Graph queries here.
    return {"prefix": prefix}


# ── YAML generation ──────────────────────────────────────────


def _generate_usage_yaml(metrics: dict) -> str:
    """Render infracost-usage.yml from collected metrics."""
    lookback = metrics.get("lookback_days", 31)
    timestamp = metrics.get("collected_at", datetime.now(datetime.UTC).isoformat())

    lines = [
        "# Infracost usage file — generated from observed Azure metrics.",
        f"# Lookback: {lookback} days | Collected: {timestamp}",
        "#",
        "# Re-generate with:",
        f"#   python scripts/collect_infracost_usage.py --lookback {lookback}",
        "#",
        "# See https://www.infracost.io/docs/features/usage_based_resources/",
        "",
        "version: 0.1",
        "",
        "resource_usage:",
        "",
        "  # ── Log Analytics ──────────────────────────────────────────",
        "  azurerm_log_analytics_workspace.main:",
        f"    monthly_data_ingestion_gb: {metrics['log_analytics_ingestion_gb']}",
        "",
        "  # ── Storage Account ───────────────────────────────────────",
        "  azurerm_storage_account.main:",
        f"    storage_gb: {metrics['storage']['storage_gb']}",
        "    monthly_tier_to_cool_storage_gb: 0",
        "    monthly_tier_to_archive_storage_gb: 0",
        "",
        "  # ── Key Vault ─────────────────────────────────────────────",
        "  azurerm_key_vault.main:",
        f"    monthly_secrets_operations: {metrics['keyvault_operations']}",
        "    monthly_keys_operations: 0",
        "    monthly_certificate_operations: 0",
        "",
    ]

    if metrics.get("cosmos_enabled"):
        cosmos = metrics["cosmos"]
        lines.extend(
            [
                "  # ── Cosmos DB (serverless) ────────────────────────────────",
                "  azurerm_cosmosdb_sql_container.runs[0]:",
                f"    monthly_request_units: {cosmos['runs_ru']}",
                f"    storage_gb: {cosmos['runs_gb']}",
                "  azurerm_cosmosdb_sql_container.subscriptions[0]:",
                f"    monthly_request_units: {cosmos['subscriptions_ru']}",
                f"    storage_gb: {cosmos['subscriptions_gb']}",
                "  azurerm_cosmosdb_sql_container.users[0]:",
                f"    monthly_request_units: {cosmos['users_ru']}",
                f"    storage_gb: {cosmos['users_gb']}",
                "  azurerm_cosmosdb_sql_container.monitors[0]:",
                f"    monthly_request_units: {cosmos['monitors_ru']}",
                f"    storage_gb: {cosmos['monitors_gb']}",
                "  azurerm_cosmosdb_sql_container.catalogue[0]:",
                f"    monthly_request_units: {cosmos['catalogue_ru']}",
                f"    storage_gb: {cosmos['catalogue_gb']}",
                "",
            ]
        )

    lines.append("")
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    args = _parse_args()

    credential = DefaultAzureCredential()
    metrics_client = MetricsQueryClient(credential)
    sub_id = args.subscription_id
    rg = args.resource_group

    end = datetime.now(datetime.UTC)
    start = end - timedelta(days=args.lookback)

    print(f"Collecting Azure metrics (lookback: {args.lookback}d, rg: {rg})")

    # We need the actual resource names. Use azure.mgmt.resource to list them.
    from azure.mgmt.resource import ResourceManagementClient

    resource_client = ResourceManagementClient(credential, sub_id)
    resources = {r.type: r for r in resource_client.resources.list_by_resource_group(rg)}

    # Build resource URIs from discovered resources
    la_resource = resources.get("Microsoft.OperationalInsights/workspaces")
    la_uri = la_resource.id if la_resource else None

    storage_resource = resources.get("Microsoft.Storage/storageAccounts")
    storage_uri = storage_resource.id if storage_resource else None

    kv_resource = resources.get("Microsoft.KeyVault/vaults")
    kv_uri = kv_resource.id if kv_resource else None

    cosmos_resource = resources.get("Microsoft.DocumentDB/databaseAccounts")
    cosmos_uri = cosmos_resource.id if cosmos_resource else None

    # ── Collect metrics ──────────────────────────────────────
    print("  Log Analytics ingestion…")
    la_gb = (
        collect_log_analytics_ingestion(metrics_client, la_uri, start, end, args.lookback)
        if la_uri
        else 0.5
    )
    print(f"    → {la_gb} GB/month")

    print("  Storage account usage…")
    storage_metrics = (
        collect_storage_metrics(metrics_client, storage_uri, start, end, args.lookback)
        if storage_uri
        else {"storage_gb": 1.0, "monthly_read_operations": 0}
    )
    print(f"    → {storage_metrics['storage_gb']} GB stored")

    print("  Key Vault operations…")
    kv_ops = (
        collect_keyvault_operations(metrics_client, kv_uri, start, end, args.lookback)
        if kv_uri
        else 500
    )
    print(f"    → {kv_ops} ops/month")

    cosmos_enabled = cosmos_uri is not None
    cosmos_data = {}
    if cosmos_enabled:
        print("  Cosmos DB request units…")
        total_ru = collect_cosmos_request_units(
            metrics_client, cosmos_uri, start, end, args.lookback
        )
        total_gb = collect_cosmos_storage_gb(metrics_client, cosmos_uri, start, end)
        # Distribute across containers proportionally (estimated split)
        cosmos_data = {
            "runs_ru": round(total_ru * 0.35),
            "runs_gb": round(total_gb * 0.4, 3),
            "subscriptions_ru": round(total_ru * 0.15),
            "subscriptions_gb": max(round(total_gb * 0.05, 3), 0.01),
            "users_ru": round(total_ru * 0.1),
            "users_gb": max(round(total_gb * 0.05, 3), 0.01),
            "monitors_ru": round(total_ru * 0.1),
            "monitors_gb": max(round(total_gb * 0.1, 3), 0.01),
            "catalogue_ru": round(total_ru * 0.3),
            "catalogue_gb": round(total_gb * 0.4, 3),
        }
        print(f"    → {total_ru} RU/month, {total_gb} GB stored")

    collected = {
        "lookback_days": args.lookback,
        "collected_at": datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "log_analytics_ingestion_gb": la_gb,
        "storage": storage_metrics,
        "keyvault_operations": kv_ops,
        "cosmos_enabled": cosmos_enabled,
        "cosmos": cosmos_data,
    }

    yaml_content = _generate_usage_yaml(collected)

    if args.dry_run:
        print("\n── Dry run — generated usage file ──")
        print(yaml_content)
        print("\n── Collected metrics (JSON) ──")
        print(json.dumps(collected, indent=2))
        return

    args.output.write_text(yaml_content)
    print(f"\n✅ Wrote {args.output}")


if __name__ == "__main__":
    main()
