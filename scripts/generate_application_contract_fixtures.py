"""Regenerate synthetic review fixtures; never use these identifiers in Azure."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.application_contract import STAGES, ExpectedContext, create_artifact, digest


def build_fixtures(bootstrap: bytes) -> tuple[tuple[str, bytes], ...]:
    source = json.loads(bootstrap)
    context = {
        "environment": "dev",
        "tenant_id": source["tenant_id"],
        "subscription_id": source["subscription_id"],
        "project_code": "kmlsat",
        "location": "westeurope",
        "vault_name": "akmlsatdevvabc123",
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
        "encryption_identity_id": f"{expected.namespace_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-application-encryption",
        "encryption_client_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "encryption_principal_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "audit_workspace_id": f"{expected.namespace_id}/providers/Microsoft.OperationalInsights/workspaces/law-kmlsat-dev-application",
        "vault_diagnostic_id": f"{expected.vault_id}/providers/Microsoft.Insights/diagnosticSettings/application-key-audit",
    }
    key = {
        "key_id": f"{expected.vault_id}/keys/application-cmk",
        "key_uri": f"{expected.vault_uri}keys/application-cmk",
    }
    chain: tuple[bytes, ...] = ()
    for stage, payload in zip(STAGES, ({}, prerequisites, {}, key, {}), strict=True):
        raw = create_artifact(stage, payload, bootstrap, chain, expected)
        artifacts = (*artifacts, (f"{stage}.json", raw))
        chain = (*chain, raw)
    return artifacts


def generate() -> None:
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/application_governance"
    for name, raw in build_fixtures((root / "bootstrap.json").read_bytes()):
        (root / name).write_bytes(raw)


if __name__ == "__main__":
    generate()
