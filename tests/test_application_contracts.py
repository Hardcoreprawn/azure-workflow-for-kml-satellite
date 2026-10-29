"""Offline shared bootstrap/application contract boundary tests."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.application_contract import (
    ContractError,
    ExpectedContext,
    create_artifact,
    encode,
    main,
    parse_bootstrap,
    parse_chain,
)
from scripts.generate_application_contract_fixtures import build_fixtures

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
        for name, raw in build_fixtures(self.bootstrap):
            self.assertEqual(raw, (FIXTURES / name).read_bytes())

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
