"""Regenerate synthetic review fixtures; never use these identifiers in Azure."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.application_contract import STAGES, ExpectedContext, create_artifact, digest


def build_fixtures(bootstrap: bytes) -> tuple[tuple[str, bytes], ...]:
    source = json.loads(bootstrap)
    environment = source["environment"]
    context = {
        "environment": environment,
        "tenant_id": source["tenant_id"],
        "subscription_id": source["subscription_id"],
        "project_code": "kmlsat",
        "location": "westeurope",
        "vault_name": f"akmlsat{environment}vabc123",
        "governance_revision": "1" * 40,
        "foundation_revision": "2" * 40,
        "policy_revision": "3" * 40,
        "bootstrap_sha256": digest(bootstrap),
        "bootstrap_operator_principal_id": "99999999-9999-4999-8999-999999999999",
        "bootstrap_encryption_principal_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "foundation": source["identities"]["foundation"],
        "backend": source["backends"]["foundation"],
    }
    context_raw = (json.dumps(context, indent=2) + "\n").encode()
    artifacts = (("context.json", context_raw),)
    expected = ExpectedContext.from_bytes(context_raw)
    prerequisites = {
        "vault_id": expected.vault_id,
        "encryption_identity_id": f"{expected.namespace_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-{environment}-application-encryption",
        "encryption_client_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "encryption_principal_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "audit_workspace_id": f"{expected.namespace_id}/providers/Microsoft.OperationalInsights/workspaces/law-kmlsat-{environment}-application",
        "vault_diagnostic_id": f"{expected.vault_id}/providers/Microsoft.Insights/diagnosticSettings/application-key-audit",
    }
    key = {
        "key_id": f"{expected.vault_id}/keys/application-cmk",
        "key_uri": f"{expected.vault_uri}keys/application-cmk",
    }
    chain: tuple[bytes, ...] = ()
    cosmos_key = {
        "key_id": f"{expected.vault_id}/keys/cosmos-cmk",
        "key_uri": f"{expected.vault_uri}keys/cosmos-cmk",
        "encryption_identity_id": f"{expected.namespace_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-{environment}-application-cosmos-encryption",
        "encryption_client_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "encryption_principal_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    }
    for stage, payload in zip(STAGES, ({}, prerequisites, {}, key, {}, cosmos_key, {}), strict=True):
        raw = create_artifact(stage, payload, bootstrap, chain, expected)
        artifacts = (*artifacts, (f"{stage}.json", raw))
        chain = (*chain, raw)
    return artifacts


def scan_fixtures(bootstrap: bytes) -> tuple[tuple[str, bytes], ...]:
    artifacts = dict(build_fixtures(bootstrap))
    source = json.loads(bootstrap)
    common = {
        "environment": source["environment"],
        "location": "westeurope",
        "subscription_id": source["subscription_id"],
        "tenant_id": source["tenant_id"],
        "bootstrap_operator_object_id": "99999999-9999-4999-8999-999999999999",
        "bootstrap_phase": "state",
        "bootstrap_allowed_ip_ranges": ["203.0.113.10"],
        "application_allowed_ip_ranges": ["203.0.113.10"],
        "application_bootstrap_json": bootstrap.decode(),
        "application_bootstrap_sha256": digest(bootstrap),
        "application_revisions": {"governance": "1" * 40, "foundation": "2" * 40, "policy": "3" * 40},
    }
    result: tuple[tuple[str, bytes], ...] = ()
    for phase, count in (("namespace", 0), ("custody", 2), ("encryption", 4), ("cosmos-encryption", 6)):
        value = {
            **common,
            "application_phase": phase,
            "application_artifacts": [artifacts[f"{stage}.json"].decode() for stage in STAGES[:count]],
        }
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        result = (*result, (f"scan-{phase}.tfvars.json", raw))
    return result


def production_bootstrap(bootstrap: bytes) -> bytes:
    return (
        bootstrap.replace(b"dev", b"prd")
        .replace(b"33333333-3333-4333-8333-333333333333", b"13131313-1313-4131-8131-131313131313")
        .replace(b"44444444-4444-4444-8444-444444444444", b"14141414-1414-4141-8141-141414141414")
    )


def generate() -> None:
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/application_governance"
    bootstrap = (root / "bootstrap.json").read_bytes()
    for name, raw in (
        *build_fixtures(bootstrap),
        *scan_fixtures(bootstrap),
        ("production-bootstrap.json", production_bootstrap(bootstrap)),
    ):
        (root / name).write_bytes(raw)


if __name__ == "__main__":
    generate()
