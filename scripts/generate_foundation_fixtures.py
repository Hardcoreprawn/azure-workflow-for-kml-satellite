"""Reproducible synthetic declarations, never real identity or permission evidence."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.application_contract import STAGES, ExpectedContext, create_artifact, digest, encode
from scripts.validate_foundation_contract import create_manifest, manifest_values

ROOT = Path(__file__).resolve().parents[1]


def fixtures(environment: str) -> dict[str, bytes]:
    source = ROOT / "tests/fixtures/application_governance"
    bootstrap_value = json.loads((source / "bootstrap.json").read_bytes().replace(b"dev", environment.encode()))
    bootstrap = encode({**bootstrap_value, "oidc_enabled": True})
    context_value = json.loads((source / "context.json").read_bytes().replace(b"dev", environment.encode()))
    context = encode({**context_value, "bootstrap_sha256": digest(bootstrap)})
    expected = ExpectedContext.from_bytes(context)
    result = {"bootstrap.json": bootstrap, "context.json": context}
    chain: tuple[bytes, ...] = ()
    for stage in STAGES:
        source_value = json.loads((source / f"{stage}.json").read_bytes().replace(b"dev", environment.encode()))
        payload = source_value["payload"] if stage in ("prerequisites", "key") else {}
        raw = create_artifact(stage, payload, bootstrap, chain, expected)
        result[f"{stage}.json"] = raw
        chain = (*chain, raw)
    name = f"kmlsat{environment}appabc123"
    result["manifest.json"] = create_manifest(
        encode(manifest_values(name, expected, chain)), name, bootstrap, chain, expected
    )
    return result


def main() -> None:
    for environment in ("dev", "prd"):
        directory = ROOT / "tests/fixtures/foundation" / environment
        directory.mkdir(parents=True, exist_ok=True)
        for name, raw in fixtures(environment).items():
            (directory / name).write_bytes(raw)


if __name__ == "__main__":
    main()
