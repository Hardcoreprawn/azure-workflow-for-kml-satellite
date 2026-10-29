"""Offline foundation trust-boundary tests; all identities are synthetic."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.application_contract import ContractError, ExpectedContext, create_artifact, digest, encode
from scripts.validate_foundation_contract import (
    create_manifest,
    external_gate,
    external_output,
    manifest_values,
    validate_bootstrap,
    validate_inputs,
    validate_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures/application_governance"
STAGES = ("namespace", "prerequisites", "custody", "key", "encryption")


def test_rejects_workload_identity_for_foundation_backend() -> None:
    expected = ExpectedContext.from_bytes((FIXTURES / "context.json").read_bytes())
    value = json.loads((FIXTURES / "bootstrap.json").read_bytes())
    value["backends"]["foundation"]["client_id"] = value["identities"]["workload"]["client_id"]
    raw = encode(value)
    expected = replace(expected, bootstrap_sha256=digest(raw))
    with pytest.raises(ContractError, match="foundation backend principal"):
        validate_bootstrap(raw, expected)


def bundle() -> tuple[ExpectedContext, bytes, tuple[bytes, ...]]:
    return (
        ExpectedContext.from_bytes((FIXTURES / "context.json").read_bytes()),
        (FIXTURES / "bootstrap.json").read_bytes(),
        tuple((FIXTURES / f"{stage}.json").read_bytes() for stage in STAGES),
    )


def test_disabled_trust_is_inspect_only() -> None:
    context, bootstrap, chain = bundle()
    assert validate_bootstrap(bootstrap, context) is False
    validate_inputs(bootstrap, chain[:1], context, "prerequisites", require_write_ready=False)
    with pytest.raises(ContractError, match="OIDC"):
        validate_inputs(bootstrap, chain[:1], context, "prerequisites", require_write_ready=True)


@pytest.mark.parametrize("phase", ["identity", "key", "prerequisites", "namespace"])
def test_rejects_non_state_bootstrap(phase: str) -> None:
    context, bootstrap, _ = bundle()
    raw = encode({**json.loads(bootstrap), "phase": phase})
    with pytest.raises(ContractError, match="state phase"):
        validate_bootstrap(raw, replace(context, bootstrap_sha256=digest(raw)))


@pytest.mark.parametrize("phase,length", [("prerequisites", 1), ("key", 3), ("storage", 5)])
def test_exact_acyclic_prefix_required(phase: str, length: int) -> None:
    context, bootstrap, chain = bundle()
    validate_inputs(bootstrap, chain[:length], context, phase, require_write_ready=False)
    with pytest.raises(ContractError, match="skipped stage"):
        validate_inputs(bootstrap, chain[: length - 1], context, phase, require_write_ready=False)


def test_manifest_is_strict_not_activated_and_immutable() -> None:
    context, bootstrap, chain = bundle()
    candidate = manifest_values("kmlsatdevappabc123", context, chain)
    raw = create_manifest(encode(candidate), "kmlsatdevappabc123", bootstrap, chain, context)
    assert validate_manifest(raw, "kmlsatdevappabc123", bootstrap, chain, context) == candidate
    assert candidate["status"] == "not-activated"
    assert candidate["storage"]["data_plane_available"] is False
    assert candidate["approved_browser_origins"] == []
    assert raw.endswith(b"\n")


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("schema_version",), 1),
        (("status",), "ready"),
        (("producer_revision",), "4" * 40),
        (("policy_revision",), "4" * 40),
        (("bootstrap_sha256",), "0" * 64),
        (("encryption_grant_sha256",), "0" * 64),
        (("tenant_id",), "99999999-9999-4999-8999-999999999999"),
        (("subscription_id",), "99999999-9999-4999-8999-999999999999"),
        (("environment",), "prd"),
        (("approved_browser_origins",), ["https://example.com"]),
        (("storage", "blob_endpoint"), "https://attacker.blob.core.windows.net/"),
        (("storage", "data_plane_available"), True),
        (("storage", "data_plane_available"), 0),
        (("encryption", "key_uri"), "https://akmlsatdevvabc123.vault.azure.net/keys/bootstrap-state"),
        (("encryption", "principal_id"), "44444444-4444-4444-8444-444444444444"),
        (("audit", "blob_diagnostic_id"), "provider-private|application-blob-audit"),
    ],
)
def test_rejects_manifest_mutations(path: tuple[str, ...], value: object) -> None:
    context, bootstrap, chain = bundle()
    candidate = manifest_values("kmlsatdevappabc123", context, chain)
    target = candidate
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(ContractError):
        validate_manifest(encode(candidate), "kmlsatdevappabc123", bootstrap, chain, context)


@pytest.mark.parametrize("section", [None, "namespace", "storage", "encryption", "audit"])
def test_rejects_unknown_secret_fields(section: str | None) -> None:
    context, bootstrap, chain = bundle()
    candidate = manifest_values("kmlsatdevappabc123", context, chain)
    target = candidate if section is None else candidate[section]
    target["connection_string"] = "forbidden"
    with pytest.raises(ContractError):
        validate_manifest(encode(candidate), "kmlsatdevappabc123", bootstrap, chain, context)


def test_raw_byte_chain_and_manifest_digest_are_not_reencoded() -> None:
    context, bootstrap, chain = bundle()
    changed = (*chain[:-1], chain[-1] + b" ")
    candidate = manifest_values("kmlsatdevappabc123", context, changed)
    assert candidate["encryption_grant_sha256"] == digest(changed[-1])
    validate_manifest(encode(candidate), "kmlsatdevappabc123", bootstrap, changed, context)
    with pytest.raises(ContractError):
        validate_manifest(encode(candidate), "kmlsatdevappabc123", bootstrap, chain, context)


def test_prd_context_is_separate() -> None:
    context, bootstrap, chain = bundle()
    prd_bootstrap = bootstrap.replace(b"dev", b"prd")
    prd_context = ExpectedContext.from_bytes(
        encode(
            {
                **json.loads((FIXTURES / "context.json").read_bytes().replace(b"dev", b"prd")),
                "bootstrap_sha256": digest(prd_bootstrap),
            }
        )
    )
    prd_chain: tuple[bytes, ...] = ()
    for stage, raw in zip(STAGES, chain, strict=True):
        payload = json.loads(raw.replace(b"dev", b"prd"))["payload"]
        if stage not in ("prerequisites", "key"):
            payload = {}
        prd_chain = (*prd_chain, create_artifact(stage, payload, prd_bootstrap, prd_chain, prd_context))
    candidate = manifest_values("kmlsatprdappabc123", prd_context, prd_chain)
    validate_manifest(encode(candidate), "kmlsatprdappabc123", prd_bootstrap, prd_chain, prd_context)
    with pytest.raises(ContractError):
        validate_manifest(encode(candidate), "kmlsatprdappabc123", bootstrap, chain, context)


@pytest.mark.parametrize("field", ["schema_version", "storage", "audit", "bootstrap_sha256"])
def test_rejects_missing_manifest_fields(field: str) -> None:
    context, bootstrap, chain = bundle()
    candidate = manifest_values("kmlsatdevappabc123", context, chain)
    del candidate[field]
    with pytest.raises(ContractError):
        validate_manifest(encode(candidate), "kmlsatdevappabc123", bootstrap, chain, context)


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), 2),
        (("tenant_id",), "99999999-9999-4999-8999-999999999999"),
        (("subscription_id",), "99999999-9999-4999-8999-999999999999"),
        (("environment",), "prd"),
        (("identities", "foundation", "github_environment"), "dev-workload"),
        (("identities", "foundation", "resource_id"), "/wrong"),
        (("identities", "foundation", "principal_id"), "66666666-6666-4666-8666-666666666666"),
        (("backends", "foundation", "container_name"), "workload"),
        (("backends", "foundation", "key"), "other.tfstate"),
        (("backends", "foundation", "storage_account_name"), "otheraccount"),
        (("backends", "foundation", "use_oidc"), False),
        (("backends", "foundation", "use_azuread_auth"), False),
        (("backends", "foundation", "use_cli"), True),
        (("backends", "foundation", "use_oidc"), 1),
    ],
)
def test_rejects_bootstrap_context_mutations(path: tuple[str, ...], value: object) -> None:
    context, bootstrap, _ = bundle()
    candidate = json.loads(bootstrap)
    target = candidate
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    raw = encode(candidate)
    with pytest.raises(ContractError):
        validate_bootstrap(raw, replace(context, bootstrap_sha256=digest(raw)))


def test_rejects_duplicate_json_fields_before_projection() -> None:
    context, bootstrap, chain = bundle()
    raw = encode(manifest_values("kmlsatdevappabc123", context, chain))
    duplicate = raw.replace(b'"schema_version":2', b'"schema_version":1,"schema_version":2')
    with pytest.raises(ContractError, match="duplicate"):
        validate_manifest(duplicate, "kmlsatdevappabc123", bootstrap, chain, context)


@pytest.mark.parametrize("raw", [b"NaN", b"{}", b"\xff", b" " * 65537])
def test_rejects_bad_or_unbounded_raw_json(raw: bytes) -> None:
    context, bootstrap, chain = bundle()
    with pytest.raises(ContractError):
        validate_manifest(raw, "kmlsatdevappabc123", bootstrap, chain, context)


@pytest.mark.parametrize("environment", ["dev", "prd"])
def test_reproducible_fixtures_satisfy_schema_and_semantics(environment: str) -> None:
    from jsonschema import Draft202012Validator

    from scripts.generate_foundation_fixtures import fixtures

    generated = fixtures(environment)
    directory = FIXTURES.parent / "foundation" / environment
    for filename, raw in generated.items():
        assert (directory / filename).read_bytes() == raw
    schema = json.loads(
        (FIXTURES.parents[2] / "docs/schemas/foundation-persistent-data-core-v2.schema.json").read_bytes()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(json.loads(generated["manifest.json"]))
    context = ExpectedContext.from_bytes(generated["context.json"])
    validate_manifest(
        generated["manifest.json"],
        f"kmlsat{environment}appabc123",
        generated["bootstrap.json"],
        tuple(generated[f"{stage}.json"] for stage in STAGES),
        context,
    )


def external_query(phase: str, length: int) -> dict[str, str]:
    directory = FIXTURES.parent / "foundation/dev"
    return {
        "context": (directory / "context.json").read_text(),
        "bootstrap": (directory / "bootstrap.json").read_text(),
        "artifacts": json.dumps([(directory / f"{stage}.json").read_text() for stage in STAGES[:length]]),
        "phase": phase,
        "writes_enabled": "true",
    }


@pytest.mark.parametrize("phase,length", [("prerequisites", 1), ("key", 3), ("storage", 5)])
def test_external_gate_and_producer_validate_actual_outputs(phase: str, length: int) -> None:
    query = external_query(phase, length)
    gate = json.loads(external_gate(encode(query)))
    assert gate["write_ready"] == "true"
    expected = ExpectedContext.from_bytes(query["context"].encode())
    directory = FIXTURES.parent / "foundation/dev"
    source = directory / ("manifest.json" if phase == "storage" else f"{phase}.json")
    value = json.loads(source.read_bytes())
    output_query = {
        **{key: value for key, value in query.items() if key != "writes_enabled"},
        "candidate": json.dumps(value if phase == "storage" else value["payload"]),
        "storage_name": "kmlsatdevappabc123" if phase == "storage" else "",
    }
    produced = json.loads(external_output(encode(output_query)))["contract"].encode()
    assert produced == source.read_bytes()
    assert expected.vault_id in gate["payloads"]
    with pytest.raises(ContractError):
        external_output(encode({**output_query, "candidate": '{"unexpected":"forbidden"}'}))


@pytest.mark.parametrize("mutation", [{"writes_enabled": "false"}, {"phase": "namespace"}, {"secret": "no"}])
def test_external_gate_fails_closed(mutation: dict[str, str]) -> None:
    with pytest.raises(ContractError):
        external_gate(encode({**external_query("prerequisites", 1), **mutation}))


def test_external_gate_rejects_malformed_artifacts_and_foreign_context() -> None:
    query = external_query("prerequisites", 1)
    for artifacts in ("{}", "[true]", "[]"):
        with pytest.raises(ContractError):
            external_gate(encode({**query, "artifacts": artifacts}))
    with pytest.raises(ContractError):
        external_gate(encode({**query, "context": query["context"].replace("dev", "prd")}))


@pytest.mark.parametrize("storage_name", ["other", "kmlsatprdappabc123", "kmlsatdevappabc123.evil"])
def test_manifest_rejects_unapproved_storage_name(storage_name: str) -> None:
    context, bootstrap, chain = bundle()
    with pytest.raises(ContractError):
        validate_manifest(b"{}", storage_name, bootstrap, chain, context)


def test_cli_inspection_and_rejection_have_no_traceback() -> None:
    args = [
        sys.executable,
        "-m",
        "scripts.validate_foundation_contract",
        "validate",
        "--phase",
        "prerequisites",
        "--context",
        str(FIXTURES / "context.json"),
        "--bootstrap",
        str(FIXTURES / "bootstrap.json"),
        "--artifact",
        str(FIXTURES / "namespace.json"),
    ]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {"status": "not-activated", "write_ready": False, "cloud_authorized": False}
    rejected = subprocess.run([*args, "--require-write-ready"], check=False, capture_output=True, text=True)
    assert rejected.returncode == 2
    assert "OIDC" in rejected.stderr
    assert "Traceback" not in rejected.stderr


@pytest.mark.parametrize("mode", ["external-gate", "external-output"])
def test_main_external_protocol(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.validate_foundation_contract import main

    query = external_query("prerequisites", 1)
    if mode == "external-output":
        query = {
            **{key: value for key, value in query.items() if key != "writes_enabled"},
            "storage_name": "",
            "candidate": json.dumps(json.loads((FIXTURES / "prerequisites.json").read_bytes())["payload"]),
        }
    output = io.BytesIO()
    monkeypatch.setattr(sys, "argv", ["validate_foundation_contract", mode])
    monkeypatch.setattr(sys, "stdin", Namespace(buffer=io.BytesIO(encode(query))))
    monkeypatch.setattr(sys, "stdout", Namespace(buffer=output))
    assert main() == 0
    assert json.loads(output.getvalue())


def test_main_validates_manifest_and_reports_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from scripts.validate_foundation_contract import main

    directory = FIXTURES.parent / "foundation/dev"
    args = [
        "validate_foundation_contract",
        "validate",
        "--context",
        str(directory / "context.json"),
        "--bootstrap",
        str(directory / "bootstrap.json"),
        "--manifest",
        str(directory / "manifest.json"),
        "--storage-name",
        "kmlsatdevappabc123",
    ]
    for stage in STAGES:
        args.extend(("--artifact", str(directory / f"{stage}.json")))
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["cloud_authorized"] is False
    monkeypatch.setattr(sys, "argv", ["validate_foundation_contract", "validate"])
    assert main() == 2
    assert "--context and --bootstrap" in capsys.readouterr().err
    args.remove("--storage-name")
    args.remove("kmlsatdevappabc123")
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 2
    assert "--storage-name" in capsys.readouterr().err


def test_output_protocol_rejects_future_names_and_non_string_references() -> None:
    query = external_query("prerequisites", 1)
    output_query = {
        **{key: value for key, value in query.items() if key != "writes_enabled"},
        "storage_name": "future-storage",
        "candidate": "{}",
    }
    with pytest.raises(ContractError, match="future storage"):
        external_output(encode(output_query))
    with pytest.raises(ContractError, match="only string"):
        external_output(encode({**output_query, "storage_name": "", "candidate": '{"value":true}'}))


def large_valid_request() -> tuple[dict[str, str], tuple[bytes, ...]]:
    query = external_query("storage", 5)
    context = ExpectedContext.from_bytes(query["context"].encode())
    bootstrap = query["bootstrap"].encode()
    chain: tuple[bytes, ...] = ()
    for stage, source in zip(STAGES, json.loads(query["artifacts"]), strict=True):
        payload = json.loads(source)["payload"] if stage in ("prerequisites", "key") else {}
        artifact = create_artifact(stage, payload, bootstrap, chain, context)
        chain = (*chain, artifact + b" " * (16000 - len(artifact)))
    return {**query, "artifacts": json.dumps([raw.decode() for raw in chain])}, chain


@pytest.mark.parametrize("command", ["external-gate", "external-output"])
def test_foundation_cli_accepts_large_digest_bound_artifact_bundle(command: str) -> None:
    query, chain = large_valid_request()
    assert all(len(raw) <= 65536 for raw in chain)
    if command == "external-output":
        context = ExpectedContext.from_bytes(query["context"].encode())
        query = {
            **{key: value for key, value in query.items() if key != "writes_enabled"},
            "candidate": json.dumps(manifest_values("kmlsatdevappabc123", context, chain)),
            "storage_name": "kmlsatdevappabc123",
        }
    raw = encode(query)
    assert len(raw) > 65536
    result = subprocess.run(
        [sys.executable, "-m", "scripts.validate_foundation_contract", command],
        input=raw,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    produced = json.loads(result.stdout)
    if command == "external-gate":
        assert produced["write_ready"] == "true"
    else:
        assert json.loads(produced["contract"])["encryption_grant_sha256"] == digest(chain[-1])


def test_foundation_cli_still_rejects_individually_oversized_artifact() -> None:
    query, chain = large_valid_request()
    oversized = (*chain[:-1], chain[-1] + b" " * 65536)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.validate_foundation_contract", "external-gate"],
        input=encode({**query, "artifacts": json.dumps([raw.decode() for raw in oversized])}),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert b"artifact must be bounded raw bytes" in result.stderr
    assert b"Traceback" not in result.stderr


def test_external_request_and_bundle_limits_remain_independently_bounded() -> None:
    from scripts.application_contract import MAX_ARTIFACT_BUNDLE_BYTES, MAX_EXTERNAL_REQUEST_BYTES

    with pytest.raises(ContractError, match="external request"):
        external_gate(b" " * (MAX_EXTERNAL_REQUEST_BYTES + 1))
    query = external_query("prerequisites", 1)
    with pytest.raises(ContractError, match="artifact bundle"):
        external_gate(encode({**query, "artifacts": " " * (MAX_ARTIFACT_BUNDLE_BYTES + 1)}))


def alphabetic_uuid_bundle() -> tuple[ExpectedContext, bytes, tuple[bytes, ...]]:
    query = external_query("storage", 5)
    original = "11111111-1111-4111-8111-111111111111"
    replacement = "abcdefab-cdef-4abc-8def-abcdefabcdef"
    bootstrap = query["bootstrap"].replace(original, replacement).encode()
    context = ExpectedContext.from_bytes(
        encode(
            {
                **json.loads(query["context"].replace(original, replacement)),
                "bootstrap_sha256": digest(bootstrap),
            }
        )
    )
    chain: tuple[bytes, ...] = ()
    for stage, source in zip(STAGES, json.loads(query["artifacts"]), strict=True):
        payload = (
            json.loads(source.replace(original, replacement))["payload"] if stage in ("prerequisites", "key") else {}
        )
        chain = (*chain, create_artifact(stage, payload, bootstrap, chain, context))
    return context, bootstrap, chain


def test_manifest_uuid_case_matches_governance_without_rewriting_provenance() -> None:
    from jsonschema import Draft202012Validator

    from scripts.application_contract import UUID_PATTERN

    context, bootstrap, chain = alphabetic_uuid_bundle()
    original_bootstrap, original_chain = bootstrap, chain
    candidate = encode(manifest_values("kmlsatdevappabc123", context, chain))
    uppercase = re.sub(UUID_PATTERN.encode(), lambda match: match[0].upper(), candidate)
    value = validate_manifest(uppercase, "kmlsatdevappabc123", bootstrap, chain, context)
    assert value["bootstrap_sha256"] == digest(bootstrap)
    assert value["encryption_grant_sha256"] == digest(chain[-1])
    assert bootstrap == original_bootstrap and chain == original_chain
    schema = json.loads(
        (FIXTURES.parents[2] / "docs/schemas/foundation-persistent-data-core-v2.schema.json").read_bytes()
    )
    Draft202012Validator(schema).validate(json.loads(uppercase))


def test_manifest_case_folding_does_not_relax_non_uuid_fields() -> None:
    context, bootstrap, chain = alphabetic_uuid_bundle()
    value = manifest_values("kmlsatdevappabc123", context, chain)
    value["namespace"]["name"] = str(value["namespace"]["name"]).upper()
    with pytest.raises(ContractError):
        validate_manifest(encode(value), "kmlsatdevappabc123", bootstrap, chain, context)


def test_foundation_cli_rejects_numeric_overflow_without_traceback() -> None:
    query = external_query("storage", 5)
    request = {
        **{key: value for key, value in query.items() if key != "writes_enabled"},
        "candidate": '{"schema_version":1e999}',
        "storage_name": "kmlsatdevappabc123",
    }
    result = subprocess.run(
        [sys.executable, "-m", "scripts.validate_foundation_contract", "external-output"],
        input=encode(request),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert b"foundation contract error:" in result.stderr
    assert b"Traceback" not in result.stderr
