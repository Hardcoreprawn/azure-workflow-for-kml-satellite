"""Validate evaluated mock plans and export the same plans for unsuppressed scanning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.application_contract import ContractError, encode, read_artifact
from scripts.validate_foundation_contract import external_output

INVENTORY = {
    "random_string.storage_suffix",
    "azurerm_storage_account.main",
    "azurerm_storage_container.kml_input",
    "azurerm_storage_container.kml_output",
    "azurerm_storage_container.pipeline_payloads",
    "azurerm_key_vault_key.storage_cmk",
    "azurerm_user_assigned_identity.storage_cmk",
    "azurerm_log_analytics_workspace.main",
    "azurerm_monitor_diagnostic_setting.storage_blob",
    "azurerm_monitor_diagnostic_setting.vault",
}
PHASE_COUNTS = {"prerequisites": 4, "key": 5, "storage": 10}
PREREQUISITES = {
    "random_string.storage_suffix",
    "azurerm_user_assigned_identity.storage_cmk",
    "azurerm_log_analytics_workspace.main",
    "azurerm_monitor_diagnostic_setting.vault",
}
PHASE_INVENTORY = {
    "prerequisites": PREREQUISITES,
    "key": PREREQUISITES | {"azurerm_key_vault_key.storage_cmk"},
    "storage": INVENTORY,
}


def validate_plan(plan: dict[str, object], phase: str) -> bytes:
    """Require exact inventories and validate actual generated candidate references."""
    if plan["configuration"]["root_module"].get("module_calls") or plan["planned_values"]["root_module"].get(
        "child_modules"
    ):
        raise ContractError("foundation is module-free; child resources cannot bypass the root inventory")
    _validate_provider(plan["configuration"]["provider_config"])
    declarations = plan["configuration"]["root_module"]["resources"]
    actual = {resource["address"] for resource in declarations if resource["mode"] == "managed"}
    if actual != INVENTORY:
        raise ContractError(f"foundation resource declaration inventory mismatch: {sorted(actual ^ INVENTORY)}")
    resources = plan["planned_values"]["root_module"]["resources"]
    managed = [resource for resource in resources if resource["mode"] == "managed"]
    instance_names = {resource["address"].split("[")[0] for resource in managed}
    if len(managed) != PHASE_COUNTS[phase] or instance_names != PHASE_INVENTORY[phase]:
        raise ContractError(f"{phase} must contain exactly {PHASE_COUNTS[phase]} approved resource instances")
    pending = [resource for resource in resources if resource["address"] == "data.external.artifact"]
    published = plan["planned_values"]["outputs"]["foundation_artifact"].get("value")
    query = pending[0]["values"]["query"] if pending else _published_query(plan, published, phase)
    result = json.loads(external_output(encode(query)))["contract"].encode()
    if published is not None and published.encode() != result:
        raise ContractError("native output differs from semantic-validator result")
    return result


def _validate_provider(providers: dict[str, object]) -> None:
    try:
        value = providers["azurerm"]["expressions"]["features"][0]["storage"][0]["data_plane_available"][
            "constant_value"
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise ContractError("AzureRM provider storage data plane must be explicitly disabled") from exc
    if value is not False:
        raise ContractError("AzureRM provider storage data plane must be explicitly disabled")


def _published_query(plan: dict[str, object], published: str | None, phase: str) -> dict[str, str]:
    if published is None:
        raise ContractError("native plan must contain a published artifact or an evaluated deferred candidate")
    root = Path(__file__).resolve().parents[1] / "infra/tofu/foundation"
    variables = plan["variables"]
    value = json.loads(published)
    return {
        "context": read_artifact(root / variables["context_path"]["value"]).decode(),
        "bootstrap": read_artifact(root / variables["bootstrap_path"]["value"]).decode(),
        "artifacts": json.dumps([read_artifact(root / path).decode() for path in variables["artifacts"]["value"]]),
        "phase": phase,
        "candidate": json.dumps(value if phase == "storage" else value["payload"]),
        "storage_name": value["storage"]["name"] if phase == "storage" else "",
    }


def export_plans(events: Path, destination: Path) -> None:
    """Export only complete, successful plan-only phases; never invent scanner values."""
    messages = [json.loads(line) for line in events.read_text().splitlines()]
    summary = [message["test_summary"] for message in messages if message.get("type") == "test_summary"]
    if len(summary) != 1 or summary[0]["status"] != "pass":
        raise ContractError("native test run must pass before exporting scanner evidence")
    selected = {
        message["@testrun"]: message["test_plan"]
        for message in messages
        if "test_plan" in message and message.get("@testrun") in PHASE_COUNTS
    }
    if set(selected) != set(PHASE_COUNTS):
        raise ContractError("all three native foundation phase plans are required")
    destination.mkdir(parents=True, exist_ok=True)
    for phase, plan in selected.items():
        artifact = validate_plan(plan, phase)
        (destination / f"{phase}.json").write_bytes(encode(plan))
        (destination / f"{phase}.artifact.json").write_bytes(artifact)
    print("Validated exact 10-declaration inventory and generated prerequisites/key/storage contracts.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export_plans(args.events, args.destination)


if __name__ == "__main__":
    main()
