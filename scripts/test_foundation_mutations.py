"""Execute security regressions against disposable copies of the real native root."""

from __future__ import annotations

import argparse
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
)


def run_mutation(tofu: str, name: str, before: str, after: str) -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "infra/tofu/foundation"
    destination = root / ".validation/foundation-mutations" / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
    (destination / ".terraform").symlink_to(source / ".terraform", target_is_directory=True)
    main = destination / "main.tf"
    original = main.read_text()
    if before not in original:
        raise ContractError(f"{name}: mutation anchor missing")
    main.write_text(original.replace(before, after, 1))
    result = subprocess.run(
        [tofu, f"-chdir={destination}", "test", "-json", "-verbose"], check=False, capture_output=True, text=True
    )
    evidence = destination / "events.jsonl"
    evidence.write_text(result.stdout)
    (destination / "stderr.log").write_text(result.stderr)
    if result.returncode == 0:
        try:
            export_plans(evidence, destination / "plans")
        except ContractError:
            print(f"REJECTED {name}: strict evaluated-plan inventory/output validator")
            return
        raise ContractError(f"{name}: native gates incorrectly accepted the regression")
    if not any(
        marker in result.stdout
        for marker in ("Test assertion failed", "Resource postcondition failed", "Resource precondition failed")
    ):
        raise ContractError(f"{name}: failed for an unexpected reason; inspect {evidence}")
    print(f"REJECTED {name}: native security assertion/condition")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tofu", default="tofu")
    args = parser.parse_args()
    for name, before, after in MUTATIONS:
        run_mutation(args.tofu, name, before, after)
    run_mutation(
        args.tofu,
        "extra-resource",
        'data "external" "inputs" {',
        'resource "random_string" "forbidden" { length = 6 }\n\ndata "external" "inputs" {',
    )
    print("All 8 executable foundation mutations were rejected.")


if __name__ == "__main__":
    main()
