"""Prove phase rollback cannot revoke CMK grants, using only persisted mock state."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from scripts.application_contract import STAGES, ContractError

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_MOCK_RESOURCES = (
    'azurerm_storage_container.state["foundation"]',
    'azurerm_storage_container.state["workload"]',
    "azurerm_key_vault.application[0]",
    "azurerm_log_analytics_workspace.audit",
    "azurerm_role_assignment.application_encryption[0]",
    "azurerm_role_assignment.application_cosmos_encryption[0]",
)


def _run_block(name: str, phase: str, length: int, command: str) -> str:
    paths = [f'file("../../../tests/fixtures/application_governance/{stage}.json")' for stage in STAGES[:length]]
    return f"""
run "{name}" {{
  command = {command}
  variables {{
    application_phase = "{phase}"
    application_artifacts = [{", ".join(paths)}]
  }}
}}
"""


def prepare_case(name: str, established: str, prior: str) -> Path:
    source = ROOT / "infra/tofu/bootstrap"
    destination = ROOT / ".validation/grant-retention" / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*", "tests"))
    (destination / ".terraform").symlink_to(source / ".terraform", target_is_directory=True)
    contracts = ROOT / ".validation/contracts"
    if not contracts.exists():
        contracts.symlink_to(ROOT / "infra/contracts", target_is_directory=True)
    original = (source / "tests/application_stages.tftest.hcl").read_text()
    mocks = original.split('run "namespace_and_vault_are_governance_owned"', 1)[0]
    if mocks.count('mock_provider "azurerm"') != 2 or 'mock_provider "random"' not in mocks:
        raise ContractError("retention proof requires all existing native cloud provider mocks")
    (destination / "tests").mkdir()
    lengths = {"custody": 2, "encryption": 4, "cosmos-encryption": 6}
    test = (
        mocks
        + _run_block("establish", established, lengths[established], "apply")
        + _run_block("rollback", prior, lengths[prior], "plan")
    )
    (destination / "tests/retention.tftest.hcl").write_text(test)
    return destination


def verify_rejection(raw: str, grant: str) -> None:
    messages = [json.loads(line) for line in raw.splitlines()]
    setup = [
        item["test_run"]["status"]
        for item in messages
        if item.get("type") == "test_run" and item.get("@testrun") == "establish"
    ]
    states = [item["test_state"] for item in messages if item.get("@testrun") == "establish" and "test_state" in item]
    if setup != ["pass"] or len(states) != 1:
        raise ContractError("retention proof must first successfully persist native mock state")
    managed = states[0]["values"]["root_module"]["resources"]
    if not any(item["address"] == grant for item in managed):
        raise ContractError("retention proof did not persist the actual grant")
    errors = [
        item for item in messages if item.get("type") == "diagnostic" and item["diagnostic"]["severity"] == "error"
    ]
    rollback = [item for item in errors if item.get("@testrun") == "rollback"]
    if not rollback or not all(
        item.get("@testrun") == "rollback"
        and item["diagnostic"]["summary"] in ("Instance cannot be destroyed", "Resource instance cannot be destroyed")
        and grant in item["diagnostic"]["detail"]
        and "prevent_destroy" in item["diagnostic"]["detail"]
        for item in rollback
    ):
        raise ContractError("phase rollback did not reject destruction of the persisted CMK grant")
    cleanup = [item for item in errors if item.get("@testrun") != "rollback"]
    if not all(
        item.get("@testrun") == "establish"
        and item["diagnostic"]["summary"] == "Resource instance cannot be destroyed"
        and "prevent_destroy" in item["diagnostic"]["detail"]
        and any(address in item["diagnostic"]["detail"] for address in PROTECTED_MOCK_RESOURCES)
        for item in cleanup
    ):
        raise ContractError("unexpected native error outside the guarded rollback")


def run_case(tofu: str, name: str, established: str, prior: str, grant: str) -> None:
    destination = prepare_case(name, established, prior)
    result = subprocess.run(
        [tofu, f"-chdir={destination}", "test", "-json", "-verbose"],
        capture_output=True,
        text=True,
        check=False,
    )
    (destination / "events.jsonl").write_text(result.stdout)
    (destination / "stderr.log").write_text(result.stderr)
    if result.returncode != 1:
        raise ContractError(f"{name}: expected blocked rollback, native exit={result.returncode}")
    verify_rejection(result.stdout, grant)
    # Native teardown also respects these guards. Only this verified mock-only
    # copied root's synthetic state is discarded; production guards stay intact.
    (destination / "errored_test.tfstate").unlink(missing_ok=True)
    print(f"PROVED {name}: persisted {grant}; phase regression rejected before destruction")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tofu", default="tofu")
    args = parser.parse_args()
    run_case(
        args.tofu,
        "cosmos",
        "cosmos-encryption",
        "encryption",
        "azurerm_role_assignment.application_cosmos_encryption[0]",
    )
    run_case(
        args.tofu,
        "blob",
        "encryption",
        "custody",
        "azurerm_role_assignment.application_encryption[0]",
    )


if __name__ == "__main__":
    main()
