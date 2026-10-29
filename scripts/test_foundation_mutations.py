"""Execute security regressions against disposable copies of the real native root."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from scripts.application_contract import ContractError
from scripts.foundation_native_plans import export_plans

MUTATIONS = (
    ("shared-key", "shared_access_key_enabled         = false", "shared_access_key_enabled         = true"),
    ("open-firewall", 'default_action = "Deny"', 'default_action = "Allow"'),
    ("lost-recovery", "days = 30", "days = 7"),
    ("slow-rotation", 'time_after_creation = "P90D"', 'time_after_creation = "P270D"'),
    ("expired-key", 'expiration_date = timeadd(plantimestamp(), "4320h")', 'expiration_date = "2000-01-01T00:00:00Z"'),
    ("resource-only-audit", "allow_resource_only_permissions = false", "allow_resource_only_permissions = true"),
    ("missing-read-audit", 'category = "StorageRead"', 'category = "StorageWrite"'),
    ("provider-data-plane-default", "data_plane_available = false", ""),
)
COSMOS_MUTATIONS = (
    ("cosmos-local-keys", "disableLocalAuth                   = true", "disableLocalAuth                   = false"),
    (
        "cosmos-public",
        'publicNetworkAccess                = "Disabled"',
        'publicNetworkAccess                = "Enabled"',
    ),
    (
        "cosmos-bypass",
        'networkAclBypass                   = "None"',
        'networkAclBypass                   = "AzureServices"',
    ),
    ("cosmos-periodic-backup", 'tier = "Continuous7Days"', 'tier = "Continuous30Days"'),
    (
        "cosmos-first-party-identity",
        '"UserAssignedIdentity=${azurerm_user_assigned_identity.cosmos_cmk[0].id}"',
        '"FirstPartyIdentity"',
    ),
    (
        "cosmos-blob-identity",
        "identity_ids = [azurerm_user_assigned_identity.cosmos_cmk[0].id]",
        "identity_ids = [azurerm_user_assigned_identity.storage_cmk.id]",
    ),
    (
        "cosmos-blob-key",
        "keyVaultKeyUri                     = azurerm_key_vault_key.cosmos_cmk[0].versionless_id",
        "keyVaultKeyUri                     = azurerm_key_vault_key.storage_cmk[0].versionless_id",
    ),
    ("cosmos-query-logging", 'category = "ControlPlaneRequests"', 'category = "QueryRuntimeStatistics"'),
    ("cosmos-ttl", "default_ttl         = -1", "default_ttl         = 30"),
    (
        "cosmos-output-all",
        'response_export_values    = ["properties.documentEndpoint"]',
        'response_export_values    = ["*"]',
    ),
    ("cosmos-default-output", "disable_default_output     = true", "disable_default_output     = false"),
    ("cosmos-provider-registration", "skip_provider_registration = true", "skip_provider_registration = false"),
    ("cosmos-schema-validation", "schema_validation_enabled = true", "schema_validation_enabled = false"),
)


def run_mutation(
    tofu: str,
    name: str,
    before: str,
    after: str,
    *,
    with_module: bool = False,
    source_file: str = "main.tf",
    boundary: str = "foundation",
) -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "infra/tofu" / boundary
    destination = root / f".validation/{boundary}-mutations" / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
    if with_module:
        _prepare_module(source, destination)
    else:
        (destination / ".terraform").symlink_to(source / ".terraform", target_is_directory=True)
    if boundary == "bootstrap":
        contracts = root / ".validation/contracts"
        if not contracts.exists():
            contracts.symlink_to(root / "infra/contracts", target_is_directory=True)
    main = destination / source_file
    original = main.read_text()
    if before not in original:
        raise ContractError(f"{name}: mutation anchor missing")
    main.write_text(original.replace(before, after, 1))
    if with_module:
        initialized = subprocess.run(
            [tofu, f"-chdir={destination}", "init", "-backend=false", "-input=false", "-lockfile=readonly"],
            check=False,
            capture_output=True,
            text=True,
        )
        if initialized.returncode:
            raise ContractError(f"module mutation initialization failed: {initialized.stderr}")
    arguments = [tofu, f"-chdir={destination}", "test", "-json", "-verbose"]
    if boundary == "bootstrap":
        arguments.append("-filter=tests/application_stages.tftest.hcl")
    result = subprocess.run(arguments, check=False, capture_output=True, text=True)
    evidence = destination / "events.jsonl"
    evidence.write_text(result.stdout)
    (destination / "stderr.log").write_text(result.stderr)
    if result.returncode == 0:
        if boundary == "bootstrap":
            raise ContractError(f"{name}: native governance gates incorrectly accepted the regression")
        try:
            export_plans(evidence, destination / "plans")
        except ContractError as exc:
            print(f"REJECTED {name}: {exc}")
            return
        raise ContractError(f"{name}: native gates incorrectly accepted the regression")
    rejected = (
        _missing_egress_failure(result.stdout)
        if source_file == "variables.tf"
        else any(
            marker in result.stdout
            for marker in ("Test assertion failed", "Resource postcondition failed", "Resource precondition failed")
        )
    )
    if not rejected:
        raise ContractError(f"{name}: failed for an unexpected reason; inspect {evidence}")
    print(f"REJECTED {name}: native security assertion/condition")


def _missing_egress_failure(stdout: str) -> bool:
    messages = [json.loads(line) for line in stdout.splitlines()]
    errors = [
        message
        for message in messages
        if message.get("type") == "diagnostic" and message["diagnostic"]["severity"] == "error"
    ]
    return bool(errors) and all(
        message.get("@testrun") == "rejects_private_10_cidr"
        and message["diagnostic"]["summary"] == "Missing expected failure"
        and "var.approved_storage_ip_ranges" in message["diagnostic"]["detail"]
        for message in errors
    )


def _prepare_module(source: Path, destination: Path) -> None:
    data = destination / ".terraform"
    data.mkdir()
    (data / "providers").symlink_to(source / ".terraform/providers", target_is_directory=True)
    module = destination / "mutation-child"
    module.mkdir()
    (module / "main.tf").write_text('resource "random_string" "forbidden" { length = 6 }\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tofu", default="tofu")
    args = parser.parse_args()
    for name, before, after in MUTATIONS:
        run_mutation(args.tofu, name, before, after)
    for name, before, after in COSMOS_MUTATIONS:
        run_mutation(args.tofu, name, before, after, source_file="cosmos.tf")
    run_mutation(
        args.tofu,
        "cosmos-forbidden-key-permission",
        "actions          = local.application_actions",
        'actions          = concat(local.application_actions, ["Microsoft.DocumentDB/databaseAccounts/listKeys/action"])',
        source_file="application.tf",
        boundary="bootstrap",
    )
    run_mutation(
        args.tofu,
        "unsupported-storage-egress",
        r"""can(regex("^[0-9.]+(/[0-9]+)?$", value)) &&
      (can(cidrhost(value, 0)) || can(cidrhost("${value}/32", 0))) &&
      !can(regex("^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.)", value)) &&
      try(tonumber(split("/", value)[1]) >= 8 && tonumber(split("/", value)[1]) <= 30, true)""",
        """can(cidrhost(strcontains(value, "/") ? value : "${value}/32", 0)) &&
      !strcontains(value, ":") &&
      try(tonumber(split("/", value)[1]) >= 8, true)""",
        source_file="variables.tf",
    )
    run_mutation(
        args.tofu,
        "extra-resource",
        'data "external" "inputs" {',
        'resource "random_string" "forbidden" { length = 6 }\n\ndata "external" "inputs" {',
    )
    run_mutation(
        args.tofu,
        "child-module-resource",
        'data "external" "inputs" {',
        'module "forbidden" { source = "./mutation-child" }\n\ndata "external" "inputs" {',
        with_module=True,
    )
    print(f"All {len(MUTATIONS) + len(COSMOS_MUTATIONS) + 4} executable foundation/governance mutations were rejected.")


if __name__ == "__main__":
    main()
