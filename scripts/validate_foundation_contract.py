"""Foundation's separate persistent-data-core boundary."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import cast

from scripts.application_contract import (
    MAX_EXTERNAL_REQUEST_BYTES,
    ApplicationContract,
    ContractError,
    ExpectedContext,
    Stage,
    _ids_equal,
    create_artifact,
    decode,
    decode_artifact_bundle,
    decode_external_request,
    digest,
    encode,
    parse_bootstrap,
    parse_chain,
    read_artifact,
)

PHASE_PREDECESSORS: dict[str, Stage] = {
    "prerequisites": "namespace",
    "key": "custody",
    "storage": "encryption",
    "cosmos-key": "encryption",
    "cosmos": "cosmos-encryption",
}
CONTAINERS = {"kml_input": "kml-input", "kml_output": "kml-output", "pipeline_payloads": "pipeline-payloads"}


def validate_bootstrap(raw: bytes, expected: ExpectedContext, *, require_write_ready: bool = False) -> bool:
    """Reuse bootstrap v1 validation; inspection is not write readiness."""
    parse_bootstrap(raw, expected)
    enabled = cast(dict[str, object], decode(raw))["oidc_enabled"] is True
    if require_write_ready and not enabled:
        raise ContractError("bootstrap OIDC trust is disabled; inspect-only, not write-ready")
    return enabled


def validate_inputs(
    bootstrap: bytes,
    artifacts: tuple[bytes, ...],
    expected: ExpectedContext,
    phase: str,
    *,
    require_write_ready: bool,
) -> tuple[ApplicationContract, ...]:
    """Reject a missing/foreign/late predecessor before any foundation resource write."""
    if phase not in PHASE_PREDECESSORS:
        raise ContractError("unsupported foundation phase")
    validate_bootstrap(bootstrap, expected, require_write_ready=require_write_ready)
    return parse_chain(bootstrap, artifacts, expected, PHASE_PREDECESSORS[phase])


def manifest_values(storage_name: str, expected: ExpectedContext, artifacts: tuple[bytes, ...]) -> dict[str, object]:
    """Expected allowlisted projection; callers must separately validate the raw prefix."""
    prefix = f"{expected.project_code}{expected.environment}app"
    if re.fullmatch(re.escape(prefix) + r"[a-z0-9]{6}", storage_name) is None or len(storage_name) > 24:
        raise ContractError("storage name must match the independently supplied foundation namespace")
    if len(artifacts) not in (5, 7):
        raise ContractError("final manifest requires the complete encryption grant prefix")
    prerequisites = cast(dict[str, dict[str, str]], decode(artifacts[1]))["payload"]
    key = cast(dict[str, dict[str, str]], decode(artifacts[3]))["payload"]
    storage_id = f"{expected.namespace_id}/providers/Microsoft.Storage/storageAccounts/{storage_name}"
    return {
        "schema_version": 2,
        "contract_scope": "persistent-data-core",
        "status": "not-activated",
        "environment": expected.environment,
        "tenant_id": expected.tenant_id,
        "subscription_id": expected.subscription_id,
        "producer": "foundation",
        "producer_revision": expected.foundation_revision,
        "policy_revision": expected.policy_revision,
        "bootstrap_sha256": expected.bootstrap_sha256,
        "encryption_grant_sha256": digest(artifacts[4]),
        "namespace": {"id": expected.namespace_id, "name": expected.namespace_name, "location": expected.location},
        "storage": _storage_values(storage_id, storage_name),
        "encryption": {
            "vault_id": expected.vault_id,
            "vault_uri": expected.vault_uri,
            "key_id": key["key_id"],
            "key_uri": key["key_uri"],
            "identity_id": prerequisites["encryption_identity_id"],
            "client_id": prerequisites["encryption_client_id"],
            "principal_id": prerequisites["encryption_principal_id"],
        },
        "audit": {
            "workspace_id": prerequisites["audit_workspace_id"],
            "vault_diagnostic_id": prerequisites["vault_diagnostic_id"],
            "blob_diagnostic_id": f"{storage_id}/blobServices/default/providers/Microsoft.Insights/diagnosticSettings/application-blob-audit",
        },
        "approved_browser_origins": [],
        "cosmos": _cosmos_values(expected, artifacts) if len(artifacts) == 7 else None,
    }


def _cosmos_values(expected: ExpectedContext, artifacts: tuple[bytes, ...]) -> dict[str, object]:
    key = cast(dict[str, dict[str, str]], decode(artifacts[5]))["payload"]
    name = f"cosmos-{expected.project_code}-{expected.environment}-application"
    account_id = f"{expected.namespace_id}/providers/Microsoft.DocumentDB/databaseAccounts/{name}"
    database_id = f"{account_id}/sqlDatabases/treesight"
    return {
        "id": account_id,
        "name": name,
        "endpoint": f"https://{name}.documents.azure.com:443/",
        "data_plane_available": False,
        "database": {"id": database_id, "name": "treesight"},
        "containers": {
            name: {"id": f"{database_id}/containers/{name}", "name": name}
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
        "encryption": {
            "key_id": key["key_id"],
            "key_uri": key["key_uri"],
            "identity_id": key["encryption_identity_id"],
            "client_id": key["encryption_client_id"],
            "principal_id": key["encryption_principal_id"],
            "grant_sha256": digest(artifacts[6]),
        },
        "diagnostic_id": f"{account_id}/providers/Microsoft.Insights/diagnosticSettings/application-cosmos-control-plane",
    }


def _storage_values(storage_id: str, name: str) -> dict[str, object]:
    return {
        "id": storage_id,
        "name": name,
        "blob_endpoint": f"https://{name}.blob.core.windows.net/",
        "data_plane_available": False,
        "containers": {
            label: {"id": f"{storage_id}/blobServices/default/containers/{value}", "name": value}
            for label, value in CONTAINERS.items()
        },
    }


def validate_manifest(
    raw: bytes,
    storage_name: str,
    bootstrap: bytes,
    artifacts: tuple[bytes, ...],
    expected: ExpectedContext,
) -> dict[str, object]:
    """Enforce schema and semantics on raw input, before any typed projection."""
    phase = "cosmos" if len(artifacts) == 7 else "storage"
    validate_inputs(bootstrap, artifacts, expected, phase, require_write_ready=False)
    wanted = manifest_values(storage_name, expected, artifacts)
    value = decode(raw)
    # Share governance's UUID-only comparison, without rewriting raw digest inputs.
    # JSON type distinctions and every non-UUID field remain exact.
    if not _ids_equal(value, wanted):
        raise ContractError("foundation manifest does not match schema and approved context/references")
    return wanted


def create_manifest(
    candidate: bytes,
    storage_name: str,
    bootstrap: bytes,
    artifacts: tuple[bytes, ...],
    expected: ExpectedContext,
) -> bytes:
    """Publish only an already semantically validated projection of actual outputs."""
    return encode(validate_manifest(candidate, storage_name, bootstrap, artifacts, expected))


def _query(raw: bytes, fields: set[str]) -> dict[str, str]:
    value = decode_external_request(raw)
    if not isinstance(value, dict) or set(value) != fields or not all(isinstance(v, str) for v in value.values()):
        raise ContractError("external query has missing, extra or non-string fields")
    return value


def _bundle(query: dict[str, str]) -> tuple[ExpectedContext, bytes, tuple[bytes, ...]]:
    expected = ExpectedContext.from_bytes(query["context"].encode())
    artifacts = decode_artifact_bundle(query["artifacts"].encode())
    if not isinstance(artifacts, list) or not all(isinstance(item, str) for item in artifacts):
        raise ContractError("artifacts must be an ordered array of raw JSON strings")
    return expected, query["bootstrap"].encode(), tuple(item.encode() for item in artifacts)


def external_gate(raw: bytes) -> bytes:
    """Mandatory OpenTofu dependency, not an optional preflight command."""
    query = _query(raw, {"context", "bootstrap", "artifacts", "phase", "writes_enabled"})
    if query["writes_enabled"] != "true":
        raise ContractError("foundation writes are closed by default")
    expected, bootstrap, artifacts = _bundle(query)
    chain = validate_inputs(bootstrap, artifacts, expected, query["phase"], require_write_ready=True)
    return encode(
        {
            "context": encode(asdict(expected)).decode(),
            "namespace_id": expected.namespace_id,
            "namespace_name": expected.namespace_name,
            "vault_id": expected.vault_id,
            "vault_uri": expected.vault_uri,
            "payloads": encode([contract.values() for contract in chain]).decode(),
            "write_ready": "true",
        }
    )


def external_output(raw: bytes) -> bytes:
    """Use exactly the fixture validator for generated native outputs."""
    query = _query(raw, {"context", "bootstrap", "artifacts", "phase", "candidate", "storage_name"})
    expected, bootstrap, artifacts = _bundle(query)
    validate_inputs(bootstrap, artifacts, expected, query["phase"], require_write_ready=True)
    if query["phase"] in ("storage", "cosmos"):
        artifact = create_manifest(query["candidate"].encode(), query["storage_name"], bootstrap, artifacts, expected)
    else:
        if query["storage_name"]:
            raise ContractError("partial foundation phases cannot supply a future storage name")
        payload = decode(query["candidate"].encode())
        if not isinstance(payload, dict) or not all(isinstance(value, str) for value in payload.values()):
            raise ContractError("foundation prerequisite payload must contain only string references")
        artifact = create_artifact(cast(Stage, query["phase"]), payload, bootstrap, artifacts, expected)
    return encode({"contract": artifact.decode()})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "external-gate", "external-output"))
    parser.add_argument("--context", type=Path)
    parser.add_argument("--bootstrap", type=Path)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--storage-name")
    parser.add_argument("--phase", choices=tuple(PHASE_PREDECESSORS), default="storage")
    parser.add_argument("--require-write-ready", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "external-gate":
            result = external_gate(sys.stdin.buffer.read(MAX_EXTERNAL_REQUEST_BYTES + 1))
        elif args.command == "external-output":
            result = external_output(sys.stdin.buffer.read(MAX_EXTERNAL_REQUEST_BYTES + 1))
        else:
            result = _validate_cli(args)
        sys.stdout.buffer.write(result)
        return 0
    except (ContractError, OSError) as exc:
        print(f"foundation contract error: {exc}", file=sys.stderr)
        return 2


def _validate_cli(args: argparse.Namespace) -> bytes:
    if args.context is None or args.bootstrap is None:
        raise ContractError("--context and --bootstrap are required")
    expected = ExpectedContext.from_bytes(read_artifact(args.context))
    bootstrap = read_artifact(args.bootstrap)
    artifacts = tuple(read_artifact(path) for path in args.artifact)
    validate_inputs(bootstrap, artifacts, expected, args.phase, require_write_ready=args.require_write_ready)
    if args.manifest is not None:
        if args.phase != "storage" or args.storage_name is None:
            raise ContractError("manifest validation requires storage phase and --storage-name")
        validate_manifest(read_artifact(args.manifest), args.storage_name, bootstrap, artifacts, expected)
    enabled = validate_bootstrap(bootstrap, expected)
    return encode({"status": "not-activated", "write_ready": enabled, "cloud_authorized": False})


if __name__ == "__main__":
    raise SystemExit(main())
