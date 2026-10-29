"""Offline tests of the mandatory evaluated-plan/output evidence boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.application_contract import ContractError
from scripts.foundation_native_plans import INVENTORY, PHASE_COUNTS, PHASE_INVENTORY, export_plans, validate_plan
from tests.test_foundation_contract import external_query


def test_cosmos_resources_match_approved_inventory() -> None:
    expected = {
        "azapi_resource.cosmos",
        "azurerm_user_assigned_identity.cosmos_cmk",
        "azurerm_key_vault_key.cosmos_cmk",
        "azurerm_cosmosdb_sql_database.main",
        "azurerm_monitor_diagnostic_setting.cosmos",
        *{
            f"azurerm_cosmosdb_sql_container.{name}"
            for name in (
                "runs",
                "subscriptions",
                "users",
                "monitors",
                "catalogue",
                "orgs",
                "feature_flags",
                "feature_flag_overrides",
            )
        },
    }
    assert expected <= INVENTORY, f"Missing approved Cosmos inventory: {sorted(expected - INVENTORY)}"


def plan_fixture(phase: str = "storage") -> dict:
    length = {"prerequisites": 1, "key": 3, "storage": 5}[phase]
    query = external_query(phase, length)
    directory = Path(__file__).parent / "fixtures/foundation/dev"
    manifest = (directory / ("manifest.json" if phase == "storage" else f"{phase}.json")).read_text()
    return {
        "configuration": {
            "provider_config": {
                "azurerm": {
                    "expressions": {"features": [{"storage": [{"data_plane_available": {"constant_value": False}}]}]}
                },
                "azapi": {
                    "expressions": {
                        **{
                            field: {"constant_value": value}
                            for field, value in {
                                "use_oidc": True,
                                "use_cli": False,
                                "use_msi": False,
                                "skip_provider_registration": True,
                                "disable_default_output": True,
                                "enable_preflight": False,
                            }.items()
                        },
                        **{
                            field: {"references": [f"local.context.{path}"]}
                            for field, path in {
                                "client_id": "foundation.client_id",
                                "tenant_id": "tenant_id",
                                "subscription_id": "subscription_id",
                            }.items()
                        },
                    }
                },
            },
            "root_module": {"resources": [{"mode": "managed", "address": name} for name in sorted(INVENTORY)]},
        },
        "planned_values": {
            "root_module": {
                "resources": [
                    *[{"mode": "managed", "address": name} for name in sorted(PHASE_INVENTORY[phase])],
                    {
                        "mode": "data",
                        "address": "data.external.artifact",
                        "values": {
                            "query": {
                                **{key: value for key, value in query.items() if key != "writes_enabled"},
                                "storage_name": "kmlsatdevappabc123" if phase == "storage" else "",
                                "candidate": manifest
                                if phase == "storage"
                                else json.dumps(json.loads(manifest)["payload"]),
                            }
                        },
                    },
                ]
            },
            "outputs": {"foundation_artifact": {}},
        },
    }


def test_evaluated_plan_uses_same_semantic_validator() -> None:
    plan = plan_fixture()
    original = deepcopy(plan)
    artifact = validate_plan(plan, "storage")
    assert json.loads(artifact)["storage"]["data_plane_available"] is False
    assert plan == original


def test_rejects_extra_resource_declaration() -> None:
    plan = plan_fixture()
    plan["configuration"]["root_module"]["resources"].append(
        {"mode": "managed", "address": "azurerm_role_assignment.forbidden"}
    )
    with pytest.raises(ContractError, match="inventory"):
        validate_plan(plan, "storage")


@pytest.mark.parametrize(
    "features", [[{}], [{"storage": [{}]}], [{"storage": [{"data_plane_available": {"constant_value": True}}]}]]
)
def test_rejects_provider_data_plane_default_or_enabled(features: list[dict]) -> None:
    plan = plan_fixture()
    plan["configuration"]["provider_config"]["azurerm"]["expressions"]["features"] = features
    with pytest.raises(ContractError, match=r"provider.*data plane"):
        validate_plan(plan, "storage")


@pytest.mark.parametrize(
    "field",
    ["use_oidc", "use_cli", "use_msi", "skip_provider_registration", "disable_default_output", "enable_preflight"],
)
def test_rejects_azapi_provider_default_or_weakened_boundary(field: str) -> None:
    for remove in (True, False):
        plan = plan_fixture()
        expressions = plan["configuration"]["provider_config"]["azapi"]["expressions"]
        if remove:
            del expressions[field]
        else:
            expressions[field]["constant_value"] = not expressions[field]["constant_value"]
        with pytest.raises(ContractError, match="AzAPI"):
            validate_plan(plan, "storage")


@pytest.mark.parametrize("field", ["client_id", "tenant_id", "subscription_id"])
def test_rejects_azapi_foreign_identity_configuration(field: str) -> None:
    plan = plan_fixture()
    plan["configuration"]["provider_config"]["azapi"]["expressions"][field] = {"constant_value": "foreign"}
    with pytest.raises(ContractError, match="approved"):
        validate_plan(plan, "storage")


def test_rejects_account_action_resource_and_provider_credentials() -> None:
    plan = plan_fixture()
    plan["configuration"]["root_module"]["resources"].append(
        {"mode": "managed", "address": "azapi_resource_action.list_keys"}
    )
    with pytest.raises(ContractError, match="inventory"):
        validate_plan(plan, "storage")
    plan = plan_fixture()
    plan["configuration"]["provider_config"]["azapi"]["expressions"]["client_secret"] = {"constant_value": "invalid"}
    with pytest.raises(ContractError, match="credentials"):
        validate_plan(plan, "storage")


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("configuration", "module_calls", {"forbidden": {"module": {"resources": []}}}),
        ("planned_values", "child_modules", [{"address": "module.forbidden", "resources": []}]),
    ],
)
def test_rejects_modules_even_when_root_inventory_matches(section: str, field: str, value: object) -> None:
    plan = plan_fixture()
    plan[section]["root_module"][field] = value
    with pytest.raises(ContractError, match="module-free"):
        validate_plan(plan, "storage")


def test_rejects_incomplete_phase_inventory() -> None:
    plan = plan_fixture()
    plan["planned_values"]["root_module"]["resources"].pop(0)
    with pytest.raises(ContractError, match="exactly 10"):
        validate_plan(plan, "storage")


def test_rejects_generated_candidate_and_published_output_mutations() -> None:
    plan = plan_fixture()
    plan["planned_values"]["root_module"]["resources"][-1]["values"]["query"]["candidate"] = "{}"
    with pytest.raises(ContractError, match="manifest"):
        validate_plan(plan, "storage")
    plan = plan_fixture()
    plan["planned_values"]["outputs"]["foundation_artifact"]["value"] = "{}"
    with pytest.raises(ContractError, match="differs"):
        validate_plan(plan, "storage")


def test_requires_successful_complete_native_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path("unused.jsonl")
    monkeypatch.setattr(Path, "read_text", lambda _: '{"type":"test_summary","test_summary":{"status":"fail"}}')
    with pytest.raises(ContractError, match="must pass"):
        export_plans(path, Path("unused-output"))
    monkeypatch.setattr(Path, "read_text", lambda _: '{"type":"test_summary","test_summary":{"status":"pass"}}')
    with pytest.raises(ContractError, match="all five"):
        export_plans(path, Path("unused-output"))


def test_native_root_keeps_persistent_guards_and_no_cloud_test_commands() -> None:
    root = Path(__file__).parents[1] / "infra/tofu/foundation"
    main = "\n".join(path.read_text() for path in root.glob("*.tf"))
    assert main.count("prevent_destroy = true") == len(INVENTORY)
    assert "ignore_changes = [expiration_date]" in main
    assert "timecmp(self.expiration_date, plantimestamp()) > 0" in main
    for path in (root / "tests").glob("*.tftest.hcl"):
        assert "command = apply" not in path.read_text()
    assert PHASE_COUNTS == {"prerequisites": 4, "key": 5, "storage": 10, "cosmos-key": 12, "cosmos": 23}


@pytest.mark.parametrize("phase", ["prerequisites", "key", "storage"])
def test_validates_already_published_native_outputs(phase: str) -> None:
    plan = plan_fixture(phase)
    candidate = plan["planned_values"]["root_module"]["resources"].pop()["values"]["query"]
    from scripts.application_contract import STAGES

    directory = Path(__file__).parent / "fixtures/foundation/dev"
    published = (directory / ("manifest.json" if phase == "storage" else f"{phase}.json")).read_text()
    plan["planned_values"]["outputs"]["foundation_artifact"]["value"] = published
    length = len(json.loads(candidate["artifacts"]))
    plan["variables"] = {
        "context_path": {"value": "../../../tests/fixtures/foundation/dev/context.json"},
        "bootstrap_path": {"value": "../../../tests/fixtures/foundation/dev/bootstrap.json"},
        "artifacts": {"value": [f"../../../tests/fixtures/foundation/dev/{stage}.json" for stage in STAGES[:length]]},
    }
    assert validate_plan(plan, phase) == published.encode()
    plan["planned_values"]["outputs"]["foundation_artifact"] = {}
    with pytest.raises(ContractError, match="published artifact"):
        validate_plan(plan, phase)


def test_exports_every_successful_phase_without_modifying_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [{"@testrun": phase, "test_plan": plan_fixture()} for phase in PHASE_COUNTS] + [
        {"type": "test_summary", "test_summary": {"status": "pass"}}
    ]
    text = "\n".join(json.dumps(message) for message in messages)
    writes: dict[str, bytes] = {}
    monkeypatch.setattr(Path, "read_text", lambda _: text)
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "write_bytes", lambda path, raw: writes.setdefault(path.name, raw))
    monkeypatch.setattr("scripts.foundation_native_plans.validate_plan", lambda plan, phase: b"validated")
    export_plans(Path("input"), Path("output"))
    assert set(writes) == {
        "prerequisites.json",
        "prerequisites.artifact.json",
        "key.json",
        "key.artifact.json",
        "storage.json",
        "storage.artifact.json",
        "cosmos-key.json",
        "cosmos-key.artifact.json",
        "cosmos.json",
        "cosmos.artifact.json",
    }
    assert json.loads(writes["storage.json"]) == messages[2]["test_plan"]
