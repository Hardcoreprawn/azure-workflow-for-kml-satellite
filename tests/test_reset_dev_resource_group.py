from __future__ import annotations

from scripts import reset_dev_resource_group as reset


def test_is_preserved_matches_type() -> None:
    resource = {"type": "Microsoft.AzureActiveDirectory/ciamDirectories"}

    assert reset.is_preserved(resource, {"Microsoft.AzureActiveDirectory/ciamDirectories"}) is True


def test_deletable_resources_excludes_preserved_types() -> None:
    resources = [
        {
            "name": "treesightauth.onmicrosoft.com",
            "type": "Microsoft.AzureActiveDirectory/ciamDirectories",
        },
        {"name": "func-kmlsat-dev", "type": "Microsoft.Web/sites"},
        {"name": "cosmos-kmlsat-dev", "type": "Microsoft.DocumentDB/databaseAccounts"},
    ]

    deletable = reset.deletable_resources(
        resources, {"Microsoft.AzureActiveDirectory/ciamDirectories"}
    )

    assert [resource["name"] for resource in deletable] == ["func-kmlsat-dev", "cosmos-kmlsat-dev"]


def test_resource_delete_state_prefers_nested_properties() -> None:
    resource = {"properties": {"provisioningState": "Deleting"}}

    assert reset.resource_delete_state(resource) == "Deleting"


def test_is_delete_in_progress_matches_expected_states() -> None:
    assert reset.is_delete_in_progress({"properties": {"provisioningState": "Deleting"}}) is True
    assert (
        reset.is_delete_in_progress({"properties": {"provisioningState": "ScheduledForDelete"}})
        is True
    )
    assert reset.is_delete_in_progress({"properties": {"provisioningState": "Succeeded"}}) is False


def test_delete_command_uses_cosmosdb_cli_for_accounts() -> None:
    resource = {
        "name": "cosmos-kmlsat-dev",
        "type": "Microsoft.DocumentDB/databaseAccounts",
        "id": (
            "/subscriptions/test/resourceGroups/rg-kmlsat-dev/providers/"
            "Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev"
        ),
    }

    command = reset.delete_command(
        resource_group="rg-kmlsat-dev",
        resource=resource,
        resource_id=resource["id"],
    )

    assert command == [
        "az",
        "cosmosdb",
        "delete",
        "--name",
        "cosmos-kmlsat-dev",
        "--resource-group",
        "rg-kmlsat-dev",
        "--yes",
    ]


def test_delete_command_defaults_to_generic_resource_delete() -> None:
    resource = {
        "name": "func-kmlsat-dev",
        "type": "Microsoft.Web/sites",
        "id": (
            "/subscriptions/test/resourceGroups/rg-kmlsat-dev/providers/"
            "Microsoft.Web/sites/func-kmlsat-dev"
        ),
    }

    command = reset.delete_command(
        resource_group="rg-kmlsat-dev",
        resource=resource,
        resource_id=resource["id"],
    )

    assert command == ["az", "resource", "delete", "--ids", resource["id"]]
