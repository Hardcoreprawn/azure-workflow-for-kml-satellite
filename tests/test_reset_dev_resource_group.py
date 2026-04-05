from __future__ import annotations

from scripts import reset_dev_resource_group as reset


def test_is_preserved_matches_type() -> None:
    resource = {"type": "Microsoft.AzureActiveDirectory/ciamDirectories"}

    assert reset.is_preserved(resource, {"Microsoft.AzureActiveDirectory/ciamDirectories"}) is True


def test_deletable_resources_excludes_preserved_types() -> None:
    resources = [
        {"name": "treesightauth.onmicrosoft.com", "type": "Microsoft.AzureActiveDirectory/ciamDirectories"},
        {"name": "func-kmlsat-dev", "type": "Microsoft.Web/sites"},
        {"name": "cosmos-kmlsat-dev", "type": "Microsoft.DocumentDB/databaseAccounts"},
    ]

    deletable = reset.deletable_resources(resources, {"Microsoft.AzureActiveDirectory/ciamDirectories"})

    assert [resource["name"] for resource in deletable] == ["func-kmlsat-dev", "cosmos-kmlsat-dev"]