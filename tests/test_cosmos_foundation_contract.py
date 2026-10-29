"""Cosmos custody evolves the shared raw-byte contract, never bootstrap v1."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.application_contract import (
    STAGES,
    ContractError,
    ExpectedContext,
    actions,
    create_artifact,
    encode,
    parse_chain,
)
from scripts.validate_foundation_contract import external_gate, external_output

FIXTURES = Path(__file__).parent / "fixtures/foundation/dev"


@pytest.mark.parametrize(
    "phase,length,filename",
    [
        ("storage", 5, "manifest.json"),
        ("cosmos", 7, "cosmos-manifest.json"),
    ],
)
def test_cli_validates_each_manifest_phase_and_rejects_missing_prefix(phase: str, length: int, filename: str) -> None:
    arguments = [
        sys.executable,
        "-m",
        "scripts.validate_foundation_contract",
        "validate",
        "--context",
        str(FIXTURES / "context.json"),
        "--bootstrap",
        str(FIXTURES / "bootstrap.json"),
        "--phase",
        phase,
        "--storage-name",
        "kmlsatdevappabc123",
        "--manifest",
        str(FIXTURES / filename),
    ]
    for stage in STAGES[:length]:
        arguments.extend(("--artifact", str(FIXTURES / f"{stage}.json")))
    result = subprocess.run(arguments, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout)["status"] == "not-activated"
    missing = subprocess.run(arguments[:-2], capture_output=True, check=False)
    assert missing.returncode == 2
    assert b"missing prerequisite artifact or skipped stage" in missing.stderr
    assert missing.stdout == b""


def bundle() -> tuple[ExpectedContext, bytes, tuple[bytes, ...]]:
    return (
        ExpectedContext.from_bytes((FIXTURES / "context.json").read_bytes()),
        (FIXTURES / "bootstrap.json").read_bytes(),
        tuple((FIXTURES / f"{stage}.json").read_bytes() for stage in STAGES),
    )


def test_cosmos_chain_is_acyclic_frozen_and_dedicated() -> None:
    assert STAGES[-2:] == ("cosmos-key", "cosmos-encryption")
    expected, bootstrap, chain = bundle()
    parsed = parse_chain(bootstrap, chain, expected, "cosmos-encryption")
    key = parsed[5].values()
    grant = parsed[6].values()
    assert grant["scope"] == key["key_id"]
    assert grant["principal_id"] == key["encryption_principal_id"]
    assert grant["principal_id"] != parsed[1].values()["encryption_principal_id"]
    assert key["key_uri"].endswith("/keys/cosmos-cmk")
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed[-1].status = "ready"  # type: ignore[misc] # Prove runtime immutability.


@pytest.mark.parametrize(
    "field,value",
    [
        ("key_id", "foreign"),
        ("key_uri", "https://akmlsatdevvabc123.vault.azure.net/keys/application-cmk"),
        ("encryption_identity_id", "foreign"),
        ("encryption_client_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("encryption_principal_id", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    ],
)
def test_rejects_foreign_or_reused_cosmos_key_identity(field: str, value: str) -> None:
    expected, bootstrap, chain = bundle()
    payload = {**json.loads(chain[5])["payload"], field: value}
    with pytest.raises(ContractError):
        create_artifact("cosmos-key", payload, bootstrap, chain[:5], expected)


@pytest.mark.parametrize("index", range(7))
def test_cosmos_write_gate_rejects_missing_or_tampered_lineage(index: int) -> None:
    expected, bootstrap, chain = bundle()
    for changed in (
        (*chain[:index], *chain[index + 1 :]),
        (*chain[:index], chain[index] + b" ", *chain[index + 1 :]),
    ):
        query = {
            "context": encode(dataclasses.asdict(expected)).decode(),
            "bootstrap": bootstrap.decode(),
            "artifacts": json.dumps([raw.decode() for raw in changed]),
            "phase": "cosmos",
            "writes_enabled": "true",
        }
        # Last-artifact whitespace is bound by the final manifest, not a following envelope.
        if index == 6 and len(changed) == 7:
            continue
        with pytest.raises(ContractError):
            external_gate(encode(query))


def test_cosmos_generated_output_validates_actual_refs() -> None:
    expected, bootstrap, chain = bundle()
    candidate = json.loads((FIXTURES / "cosmos-manifest.json").read_bytes())
    query = {
        "context": encode(dataclasses.asdict(expected)).decode(),
        "bootstrap": bootstrap.decode(),
        "artifacts": json.dumps([raw.decode() for raw in chain]),
        "phase": "cosmos",
        "storage_name": candidate["storage"]["name"],
        "candidate": json.dumps(candidate),
    }
    assert json.loads(external_output(encode(query)))["contract"] == encode(candidate).decode()
    candidate["cosmos"]["encryption"]["identity_id"] = candidate["encryption"]["identity_id"]
    with pytest.raises(ContractError, match="manifest"):
        external_output(encode({**query, "candidate": json.dumps(candidate)}))


def test_cosmos_action_allowlist_is_exact_management_crud() -> None:
    actual = {action for action in actions() if action.startswith("Microsoft.DocumentDB/")}
    assert actual == {
        f"Microsoft.DocumentDB/databaseAccounts{suffix}/{verb}"
        for suffix in ("", "/sqlDatabases", "/sqlDatabases/containers")
        for verb in ("read", "write", "delete")
    } | {
        "Microsoft.DocumentDB/databaseAccounts/operationResults/read",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/operationResults/read",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/operationResults/read",
        "Microsoft.DocumentDB/locations/operationsStatus/read",
    }
    assert not any(
        forbidden.lower() in action.lower()
        for action in actions()
        for forbidden in ("listKeys", "readonlykeys", "connectionstrings", "restore", "*", "sqlRole", "dataAction")
    )


@pytest.mark.parametrize(
    "action",
    [
        "Microsoft.DocumentDB/databaseAccounts/listKeys/action",
        "Microsoft.DocumentDB/databaseAccounts/readonlykeys/action",
        "Microsoft.DocumentDB/databaseAccounts/listConnectionStrings/action",
        "Microsoft.DocumentDB/databaseAccounts/restore/action",
        "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments/write",
        "Microsoft.DocumentDB/*",
    ],
)
def test_permission_mutations_fail_before_contract_write(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    expected, bootstrap, chain = bundle()
    value = encode([*actions(), action])
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: value if path.name == "actions.json" else original(path))
    with pytest.raises(ContractError, match="action allowlist"):
        parse_chain(bootstrap, chain, expected, "cosmos-encryption")


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "foreign"),
        ("principal_id", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ("role_definition_id", "Contributor"),
    ],
)
def test_cosmos_grant_tampering_is_rejected(field: str, value: str) -> None:
    expected, bootstrap, chain = bundle()
    grant = json.loads(chain[6])
    grant["payload"][field] = value
    with pytest.raises(ContractError, match="scope/principal/ancestry/role"):
        parse_chain(bootstrap, (*chain[:6], encode(grant)), expected, "cosmos-encryption")


@pytest.mark.parametrize(
    "field,value",
    [
        ("foundation_revision", "9" * 40),
        ("policy_revision", "9" * 40),
        ("environment", "prd"),
    ],
)
def test_cosmos_rejects_foreign_expected_context(field: str, value: str) -> None:
    expected, bootstrap, chain = bundle()
    with pytest.raises(ContractError):
        parse_chain(bootstrap, chain, dataclasses.replace(expected, **{field: value}), "cosmos-encryption")


def test_cosmos_manifest_schema_and_last_raw_grant_digest() -> None:
    import jsonschema

    expected, bootstrap, chain = bundle()
    manifest = json.loads((FIXTURES / "cosmos-manifest.json").read_bytes())
    schema = json.loads(
        (FIXTURES.parents[3] / "docs/schemas/foundation-persistent-data-core-v2.schema.json").read_bytes()
    )
    jsonschema.Draft202012Validator(schema).validate(manifest)
    from scripts.validate_foundation_contract import validate_manifest

    with pytest.raises(ContractError, match="manifest"):
        validate_manifest(
            encode(manifest), manifest["storage"]["name"], bootstrap, (*chain[:6], chain[6] + b" "), expected
        )


@pytest.mark.parametrize(
    "path,value",
    [
        (("id",), "foreign"),
        (("endpoint",), "https://foreign.documents.azure.com:443/"),
        (("data_plane_available",), True),
        (("database", "id"), "foreign"),
        (("containers", "runs", "id"), "foreign"),
        (("encryption", "grant_sha256"), "0" * 64),
        (("diagnostic_id",), "foreign"),
    ],
)
def test_cosmos_actual_generated_reference_mutations_fail(path: tuple[str, ...], value: object) -> None:
    from scripts.validate_foundation_contract import validate_manifest

    expected, bootstrap, chain = bundle()
    manifest = json.loads((FIXTURES / "cosmos-manifest.json").read_bytes())
    target = manifest["cosmos"]
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(ContractError, match="manifest"):
        validate_manifest(encode(manifest), manifest["storage"]["name"], bootstrap, chain, expected)
