"""Offline shared bootstrap/application contract boundary tests."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import application_contract
from scripts.application_contract import (
    MAX_BYTES,
    ContractError,
    ExpectedContext,
    create_artifact,
    encode,
    main,
    parse_bootstrap,
    parse_chain,
)
from scripts.generate_application_contract_fixtures import build_fixtures, production_bootstrap, scan_fixtures

FIXTURES = Path(__file__).parent / "fixtures" / "application_governance"
STAGES = ("namespace", "prerequisites", "custody", "key", "encryption")


class ApplicationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ExpectedContext.from_bytes((FIXTURES / "context.json").read_bytes())
        self.bootstrap = (FIXTURES / "bootstrap.json").read_bytes()
        self.chain = tuple((FIXTURES / f"{stage}.json").read_bytes() for stage in STAGES)

    def test_all_stages_are_valid_immutable_and_not_readiness(self) -> None:
        bootstrap = parse_bootstrap(self.bootstrap, self.context)
        self.assertEqual(bootstrap.foundation.principal_id, self.context.foundation.principal_id)
        contracts = parse_chain(self.bootstrap, self.chain, self.context, "encryption")
        self.assertEqual(tuple(contract.stage for contract in contracts), STAGES)
        self.assertEqual(contracts[-1].status, "declared-not-activated")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            contracts[-1].status = "ready"  # type: ignore[misc] # Exercise runtime immutability.

    def test_namespace_requires_no_future_resources(self) -> None:
        result = create_artifact("namespace", {}, self.bootstrap, (), self.context)
        self.assertEqual(json.loads(result)["payload"]["vault_id"], self.context.vault_id)
        self.assertNotIn("encryption_identity_id", json.loads(result)["payload"])

    def test_fixtures_are_reproducible_from_shared_producer(self) -> None:
        for name, raw in (*build_fixtures(self.bootstrap), *scan_fixtures(self.bootstrap)):
            self.assertEqual(raw, (FIXTURES / name).read_bytes())
        self.assertEqual(production_bootstrap(self.bootstrap), (FIXTURES / "production-bootstrap.json").read_bytes())

    def test_external_adapter_builds_validated_encryption_without_azure(self) -> None:
        query = {
            "context": (FIXTURES / "context.json").read_text(),
            "bootstrap": self.bootstrap.decode(),
            "artifacts": json.dumps([raw.decode() for raw in self.chain[:4]]),
            "phase": "encryption",
        }
        stdin = io.TextIOWrapper(io.BytesIO(encode(query)))
        stdout = io.TextIOWrapper(io.BytesIO())
        with (
            patch("sys.argv", ["application_contract", "external"]),
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(main(), 0)
        result = json.loads(stdout.buffer.getvalue())
        self.assertEqual(result["contract"].encode(), self.chain[4])
        self.assertEqual(result["principal_id"], "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    def _external_result(self, raw: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "scripts/application_contract.py", "external"],
            input=raw,
            capture_output=True,
            check=False,
        )

    def test_external_accepts_large_digest_bound_bundle_of_bounded_artifacts(self) -> None:
        bootstrap = self.bootstrap.ljust(MAX_BYTES, b" ")
        context = dataclasses.replace(self.context, bootstrap_sha256=hashlib.sha256(bootstrap).hexdigest())
        parse_bootstrap(bootstrap, context)
        previous: tuple[bytes, ...] = ()
        for index, stage in enumerate(application_contract.STAGES[:4]):
            payload = json.loads(self.chain[index])["payload"] if stage in ("prerequisites", "key") else {}
            artifact = create_artifact(stage, payload, bootstrap, previous, context)
            previous = (*previous, artifact.ljust(MAX_BYTES, b"\t"))
        parse_chain(bootstrap, previous, context, "key")
        bundle = json.dumps([raw.decode() for raw in previous])
        self.assertGreater(len(bundle.encode()), MAX_BYTES)
        request = encode(
            {
                "context": encode(dataclasses.asdict(context)).decode(),
                "bootstrap": bootstrap.decode(),
                "artifacts": bundle,
                "phase": "encryption",
            }
        )
        self.assertGreater(len(request), MAX_BYTES)
        result = self._external_result(request)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        artifact = json.loads(result.stdout)["contract"].encode()
        self.assertEqual(parse_chain(bootstrap, (*previous, artifact), context, "encryption")[-1].stage, "encryption")

    def test_external_rejects_individual_oversize_artifacts(self) -> None:
        query = {
            "context": (FIXTURES / "context.json").read_text(),
            "bootstrap": self.bootstrap.decode(),
            "artifacts": json.dumps([raw.decode() for raw in self.chain[:4]]),
            "phase": "encryption",
        }
        for field in ("context", "bootstrap", "artifacts"):
            with self.subTest(field=field):
                oversize = self.chain[0].ljust(MAX_BYTES + 1, b" ").decode()
                value = json.dumps([oversize, *(raw.decode() for raw in self.chain[1:4])])
                if field != "artifacts":
                    value = str(query[field]).ljust(MAX_BYTES + 1)
                changed = {**query, field: value}
                if field == "bootstrap":
                    context = dataclasses.replace(
                        self.context, bootstrap_sha256=hashlib.sha256(value.encode()).hexdigest()
                    )
                    changed["context"] = encode(dataclasses.asdict(context)).decode()
                result = self._external_result(encode(changed))
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"artifact must be bounded raw bytes", result.stderr)
                self.assertEqual(result.stdout, b"")

    def test_external_rejects_oversize_bundle_and_request_with_explicit_errors(self) -> None:
        query = {
            "context": (FIXTURES / "context.json").read_text(),
            "bootstrap": self.bootstrap.decode(),
            "artifacts": "[]".ljust(application_contract.MAX_ARTIFACT_BUNDLE_BYTES + 1),
            "phase": "namespace",
        }
        result = self._external_result(encode(query))
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"artifact bundle must be bounded raw bytes", result.stderr)
        result = self._external_result(b"{}".ljust(application_contract.MAX_EXTERNAL_REQUEST_BYTES + 1))
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"external request must be bounded raw bytes", result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_shared_transport_decoders_preserve_strict_json_validation(self) -> None:
        for decoder in (application_contract.decode_external_request, application_contract.decode_artifact_bundle):
            with self.subTest(decoder=decoder.__name__):
                self.assertEqual(decoder(b"{}".ljust(MAX_BYTES + 1)), {})
                for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"):
                    with self.assertRaises(ContractError):
                        decoder(raw)

    def _lettered_uuid_inputs(self) -> tuple[bytes, dict[str, object]]:
        replacements = {
            str(index) * 8
            + "-"
            + str(index) * 4
            + "-4"
            + str(index) * 3
            + "-8"
            + str(index) * 3
            + "-"
            + str(index) * 12: f"a{str(index) * 7}-abcd-4{str(index) * 3}-8{str(index) * 3}-{str(index) * 12}"
            for index in range(1, 10)
        }
        bootstrap = self.bootstrap.decode()
        context = (FIXTURES / "context.json").read_text()
        for original, replacement in replacements.items():
            bootstrap = bootstrap.replace(original, replacement)
            context = context.replace(original, replacement)
        return bootstrap.encode(), json.loads(context)

    def test_external_uuid_case_variants_preserve_raw_hashes_across_all_stages(self) -> None:
        bootstrap, approved = self._lettered_uuid_inputs()
        bootstrap = re.sub(
            application_contract.UUID_PATTERN, lambda match: match[0].upper(), bootstrap.decode()
        ).encode()
        bootstrap += b" \n"
        approved["bootstrap_sha256"] = hashlib.sha256(bootstrap).hexdigest()
        role_uuid = ExpectedContext.from_bytes(encode(approved)).role_definition_id.rsplit("/", 1)[-1]
        for spelling in (str.lower, str.upper, str.title):
            with self.subTest(spelling=spelling.__name__):
                context_raw = re.sub(
                    application_contract.UUID_PATTERN,
                    lambda match, spelling=spelling: spelling(match[0]),
                    encode(approved).decode(),
                )
                context = ExpectedContext.from_bytes(context_raw.encode())
                query = {
                    "context": context_raw,
                    "bootstrap": bootstrap.decode(),
                    "artifacts": "[]",
                    "phase": "namespace",
                }
                result = self._external_result(encode(query))
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(parse_bootstrap(bootstrap, context).raw_sha256, approved["bootstrap_sha256"])
                namespace = json.loads(result.stdout)["contract"].encode()
                self.assertEqual(
                    json.loads(namespace)["payload"]["foundation_role_definition_id"].rsplit("/", 1)[-1], role_uuid
                )
                previous = (namespace,)
                for index, stage in enumerate(application_contract.STAGES[1:4], 1):
                    payload = json.loads(self.chain[index])["payload"] if stage in ("prerequisites", "key") else {}
                    payload_raw = (
                        encode(payload).decode().replace(self.context.subscription_id, context.subscription_id)
                    )
                    payload = json.loads(
                        re.sub(application_contract.UUID_PATTERN, lambda match: match[0].swapcase(), payload_raw)
                    )
                    artifact = create_artifact(stage, payload, bootstrap, previous, context)
                    artifact = re.sub(
                        application_contract.UUID_PATTERN, lambda match: match[0].swapcase(), artifact.decode()
                    ).encode()
                    previous = (*previous, artifact)
                query = {**query, "phase": "encryption", "artifacts": json.dumps([raw.decode() for raw in previous])}
                result = self._external_result(encode(query))
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                final = json.loads(result.stdout)["contract"].encode()
                self.assertEqual(json.loads(final)["prior_sha256"], hashlib.sha256(previous[-1]).hexdigest())
                self.assertEqual(json.loads(final)["bootstrap_sha256"], hashlib.sha256(bootstrap).hexdigest())
                self.assertEqual(
                    parse_chain(bootstrap, (*previous, final), context, "encryption")[-1].raw_sha256,
                    hashlib.sha256(final).hexdigest(),
                )
                with self.assertRaisesRegex(ContractError, "SHA256"):
                    parse_bootstrap(bootstrap + b" ", context)

    def test_uuid_case_cannot_bypass_identity_separation(self) -> None:
        bootstrap, approved = self._lettered_uuid_inputs()
        for field in ("principal_id", "client_id"):
            with self.subTest(field=field):
                document = json.loads(bootstrap)
                document["identities"]["workload"][field] = document["identities"]["foundation"][field].upper()
                raw = encode(document)
                context = ExpectedContext.from_bytes(
                    encode({**approved, "bootstrap_sha256": hashlib.sha256(raw).hexdigest()})
                )
                with self.assertRaisesRegex(ContractError, "must be distinct"):
                    parse_bootstrap(raw, context)
        context = ExpectedContext.from_bytes(
            encode({**approved, "bootstrap_sha256": hashlib.sha256(bootstrap).hexdigest()})
        )
        namespace = create_artifact("namespace", {}, bootstrap, (), context)
        payload = json.loads(self.chain[1])["payload"]
        payload = json.loads(encode(payload).decode().replace(self.context.subscription_id, context.subscription_id))
        for principal in (
            context.foundation.principal_id,
            context.bootstrap_operator_principal_id,
            context.bootstrap_encryption_principal_id,
        ):
            with self.subTest(principal=principal), self.assertRaisesRegex(ContractError, "must differ"):
                create_artifact(
                    "prerequisites",
                    {**payload, "encryption_principal_id": principal.upper()},
                    bootstrap,
                    (namespace,),
                    context,
                )
        excluded = dataclasses.replace(context, bootstrap_operator_principal_id=context.foundation.principal_id.upper())
        with self.assertRaisesRegex(ContractError, "distinct from deployment"):
            parse_bootstrap(bootstrap, excluded)

    def test_huge_json_integer_is_a_bounded_contract_error_in_decoders_and_cli(self) -> None:
        raw = b'{"value":' + b"9" * 5000 + b"}"
        self.assertLess(len(raw), MAX_BYTES)
        for decoder in (
            application_contract.decode,
            application_contract.decode_artifact_bundle,
            application_contract.decode_external_request,
        ):
            with self.subTest(decoder=decoder.__name__), self.assertRaisesRegex(ContractError, "invalid JSON"):
                decoder(raw)
        result = self._external_result(raw)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"contract error: invalid JSON", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertLess(len(result.stderr), 1024)

    def test_specific_json_contract_errors_are_not_wrapped_as_conversion_errors(self) -> None:
        for raw, message in (
            (b'{"x":1,"x":2}', "duplicate JSON fields are forbidden"),
            (b'{"x":NaN}', "non-finite JSON number: NaN"),
        ):
            with self.subTest(message=message), self.assertRaises(ContractError) as caught:
                application_contract.decode_external_request(raw)
            self.assertEqual(str(caught.exception), message)

    def test_all_decoders_reject_numeric_overflow_but_preserve_finite_floats(self) -> None:
        for decoder in (
            application_contract.decode,
            application_contract.decode_artifact_bundle,
            application_contract.decode_external_request,
        ):
            self.assertEqual(decoder(b"[1.25,1e308,-1e308,1e-999]"), [1.25, 1e308, -1e308, 0.0])
            for number in ("1e999", "-1e999", "NaN", "Infinity", "-Infinity"):
                with self.subTest(decoder=decoder.__name__, number=number):
                    with self.assertRaisesRegex(ContractError, "^non-finite JSON number"):
                        decoder(f'{{"value":{number}}}'.encode())

    def test_external_numeric_overflow_in_envelope_has_no_traceback(self) -> None:
        for number in ("1e999", "-1e999"):
            with self.subTest(number=number):
                namespace = encode({**json.loads(self.chain[0]), "status": "OVERFLOW"})
                namespace = namespace.replace(b'"OVERFLOW"', number.encode())
                query = {
                    "context": (FIXTURES / "context.json").read_text(),
                    "bootstrap": self.bootstrap.decode(),
                    "artifacts": json.dumps([namespace.decode(), self.chain[1].decode()]),
                    "phase": "custody",
                }
                result = self._external_result(encode(query))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"contract error: non-finite JSON number", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertLess(len(result.stderr), 1024)

    def test_cli_validate_create_and_explicit_missing_file_error(self) -> None:
        common = [
            "--context",
            str(FIXTURES / "context.json"),
            "--bootstrap",
            str(FIXTURES / "bootstrap.json"),
            "--stage",
            "namespace",
        ]
        for command, extra in (("validate", ["--artifact", str(FIXTURES / "namespace.json")]), ("create", [])):
            stdout = io.TextIOWrapper(io.BytesIO())
            with patch("sys.argv", ["application_contract", command, *common, *extra]), patch("sys.stdout", stdout):
                self.assertEqual(main(), 0)
            self.assertIn("namespace", stdout.buffer.getvalue().decode())
        with patch("sys.argv", ["application_contract", "create"]), patch("sys.stderr", io.StringIO()) as stderr:
            self.assertEqual(main(), 2)
        self.assertIn("required", stderr.getvalue())

    def test_bootstrap_unknown_fields_are_rejected_before_coercion(self) -> None:
        for section in ((), ("identities", "foundation"), ("backends", "foundation"), ("encryption",)):
            with self.subTest(section=section):
                value = json.loads(self.bootstrap)
                target = value
                for key in section:
                    target = target[key]
                target["unexpected_field"] = "unexpected"
                raw = json.dumps(value).encode()
                context = dataclasses.replace(self.context, bootstrap_sha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaisesRegex(ContractError, "fields"):
                    parse_bootstrap(raw, context)

    def test_bootstrap_raw_byte_provenance_includes_whitespace(self) -> None:
        with self.assertRaisesRegex(ContractError, "SHA256"):
            parse_bootstrap(self.bootstrap + b"\n", self.context)

    def test_wrong_backend_and_principal_context_rejected(self) -> None:
        wrong = dataclasses.replace(self.context.backend, client_id="66666666-6666-4666-8666-666666666666")
        with self.assertRaisesRegex(ContractError, "backend"):
            parse_bootstrap(self.bootstrap, dataclasses.replace(self.context, backend=wrong))
        identity = dataclasses.replace(self.context.foundation, principal_id="66666666-6666-4666-8666-666666666666")
        with self.assertRaisesRegex(ContractError, "foundation"):
            parse_bootstrap(self.bootstrap, dataclasses.replace(self.context, foundation=identity))

    def test_context_mutations_rejected(self) -> None:
        mutations = {
            "environment": "prd",
            "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "subscription_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "location": "eastus",
            "vault_name": "different-vault",
            "governance_revision": "a" * 40,
            "foundation_revision": "b" * 40,
            "policy_revision": "c" * 40,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), self.assertRaises(ContractError):
                parse_chain(
                    self.bootstrap, self.chain, dataclasses.replace(self.context, **{field: value}), "encryption"
                )

    def test_each_stage_rejects_unknown_fields_revision_and_phase_skips(self) -> None:
        for index, stage in enumerate(STAGES):
            for field, value in (
                ("unknown", "secret"),
                ("schema_version", 99),
                ("producer_revision", "f" * 40),
                ("prior_sha256", "0" * 64),
                ("status", "ready"),
                ("stage", "storage"),
            ):
                with self.subTest(stage=stage, field=field), self.assertRaises(ContractError):
                    changed = {**json.loads(self.chain[index]), field: value}
                    parse_chain(
                        self.bootstrap, (*self.chain[:index], json.dumps(changed).encode()), self.context, stage
                    )
        with self.assertRaises(ContractError):
            parse_chain(self.bootstrap, (self.chain[0], self.chain[2]), self.context, "custody")

    def test_wrong_vault_key_ancestry_version_and_grants_rejected(self) -> None:
        changes = (
            (1, "vault_id", self.context.namespace_id + "/providers/Microsoft.KeyVault/vaults/foreign"),
            (1, "encryption_identity_id", self.context.foundation.resource_id),
            (1, "encryption_principal_id", self.context.foundation.principal_id),
            (1, "encryption_principal_id", self.context.bootstrap_operator_principal_id),
            (1, "encryption_principal_id", self.context.bootstrap_encryption_principal_id),
            (
                1,
                "audit_workspace_id",
                self.context.namespace_id.replace("-application", "-bootstrap")
                + "/providers/Microsoft.OperationalInsights/workspaces/audit",
            ),
            (2, "principal_id", "66666666-6666-4666-8666-666666666666"),
            (2, "scope", self.context.namespace_id),
            (
                2,
                "role_definition_id",
                "/subscriptions/"
                + self.context.subscription_id
                + "/providers/Microsoft.Authorization/roleDefinitions/"
                + "0" * 36,
            ),
            (3, "key_id", self.context.vault_id + "/keys/application-cmk/version"),
            (3, "key_id", self.context.vault_id.replace(self.context.vault_name, "foreign") + "/keys/application-cmk"),
            (3, "key_uri", "https://foreign.vault.azure.net/keys/application-cmk"),
            (4, "scope", self.context.vault_id),
            (4, "principal_id", self.context.foundation.principal_id),
        )
        for index, field, value in changes:
            with self.subTest(index=index, field=field), self.assertRaises(ContractError):
                changed = json.loads(self.chain[index])
                changed["payload"][field] = value
                parse_chain(
                    self.bootstrap, (*self.chain[:index], json.dumps(changed).encode()), self.context, STAGES[index]
                )

    def test_duplicate_keys_and_non_json_inputs_have_explicit_errors(self) -> None:
        for value in (b'{"schema_version":1,"schema_version":2}', b"[]", b"\xff", b"{"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                ExpectedContext.from_bytes(value)

    def test_cli_reports_error_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/application_contract.py", "external"],
            input='{"unexpected":"value"}',
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contract error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
