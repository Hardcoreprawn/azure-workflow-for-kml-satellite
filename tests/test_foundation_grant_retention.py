"""False-positive protections for native persisted-mock-state rollback evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import test_foundation_grant_retention as retention
from scripts.application_contract import ContractError

GRANT = "azurerm_role_assignment.application_cosmos_encryption[0]"


def events() -> list[dict]:
    return [
        {"type": "test_run", "@testrun": "establish", "test_run": {"status": "pass"}},
        {"@testrun": "establish", "test_state": {"values": {"root_module": {"resources": [{"address": GRANT}]}}}},
        {
            "type": "diagnostic",
            "@testrun": "rollback",
            "diagnostic": {
                "severity": "error",
                "summary": "Resource instance cannot be destroyed",
                "detail": f"Resource instance {GRANT} has prevent_destroy set",
            },
        },
        {
            "type": "diagnostic",
            "@testrun": "establish",
            "diagnostic": {
                "severity": "error",
                "summary": "Resource instance cannot be destroyed",
                "detail": f"Resource instance {GRANT} has prevent_destroy set",
            },
        },
    ]


def raw(items: list[dict]) -> str:
    return "\n".join(json.dumps(item) for item in items)


def test_native_proof_requires_persisted_state_and_exact_rollback_rejection() -> None:
    messages = events()
    before = deepcopy(messages)
    retention.verify_rejection(raw(messages), GRANT)
    assert messages == before


@pytest.mark.parametrize("index", range(3))
def test_rejects_missing_setup_state_or_rollback_error(index: int) -> None:
    messages = events()
    del messages[index]
    with pytest.raises(ContractError):
        retention.verify_rejection(raw(messages), GRANT)


@pytest.mark.parametrize("mutation", ["wrong-grant", "wrong-error", "wrong-cleanup", "failed-setup"])
def test_rejects_unrelated_or_failed_native_execution(mutation: str) -> None:
    messages = events()
    if mutation == "wrong-grant":
        messages[1]["test_state"]["values"]["root_module"]["resources"] = []
    elif mutation == "wrong-error":
        messages[2]["diagnostic"]["summary"] = "Invalid configuration"
    elif mutation == "wrong-cleanup":
        messages[3]["diagnostic"]["detail"] = "unexpected.provider has prevent_destroy set"
    else:
        messages[0]["test_run"]["status"] = "fail"
    with pytest.raises(ContractError):
        retention.verify_rejection(raw(messages), GRANT)


@pytest.mark.parametrize("missing_mock", [False, True])
def test_materialized_cases_reuse_real_root_and_mock_providers(
    monkeypatch: pytest.MonkeyPatch, missing_mock: bool
) -> None:
    source = (retention.ROOT / "infra/tofu/bootstrap/tests/application_stages.tftest.hcl").read_text()
    if missing_mock:
        source = source.replace('mock_provider "random"', 'provider "random"')
    writes: dict[str, str] = {}
    copies: list[tuple[Path, Path]] = []
    monkeypatch.setattr(Path, "exists", lambda _: False)
    monkeypatch.setattr(Path, "read_text", lambda _: source)
    monkeypatch.setattr(Path, "symlink_to", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "write_text", lambda path, text: writes.setdefault(path.name, text))
    monkeypatch.setattr(retention.shutil, "copytree", lambda source, target, **kwargs: copies.append((source, target)))
    if missing_mock:
        with pytest.raises(ContractError, match="cloud provider mocks"):
            retention.prepare_case("cosmos", "cosmos-encryption", "encryption")
        return
    destination = retention.prepare_case("cosmos", "cosmos-encryption", "encryption")
    assert copies == [(retention.ROOT / "infra/tofu/bootstrap", destination)]
    test = writes["retention.tftest.hcl"]
    assert 'run "establish"' in test and "command = apply" in test
    assert 'run "rollback"' in test and "command = plan" in test
    assert 'mock_provider "azurerm"' in test and 'alias = "application"' in test
    assert "cosmos-key.json" in test


@pytest.mark.parametrize("returncode", [0, 1, 2])
def test_runner_rejects_wrong_exit_and_only_discards_verified_mock_state(
    monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    directory = Path("unused-mock-only-case")
    commands: list[list[str]] = []
    removed: list[Path] = []
    monkeypatch.setattr(retention, "prepare_case", lambda *args: directory)
    monkeypatch.setattr(Path, "write_text", lambda *args: None)
    monkeypatch.setattr(Path, "unlink", lambda path, **kwargs: removed.append(path))

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, returncode, stdout=raw(events()), stderr="")

    monkeypatch.setattr(retention.subprocess, "run", run)
    if returncode != 1:
        with pytest.raises(ContractError, match="expected blocked rollback"):
            retention.run_case("tofu", "cosmos", "cosmos-encryption", "encryption", GRANT)
        assert removed == []
    else:
        retention.run_case("tofu", "cosmos", "cosmos-encryption", "encryption", GRANT)
        assert removed == [directory / "errored_test.tfstate"]
    assert commands == [["tofu", f"-chdir={directory}", "test", "-json", "-verbose"]]


def test_entry_point_proves_both_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(retention, "run_case", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["retention", "--tofu", "/pinned/tofu"])
    retention.main()
    assert [(call[1], call[2], call[3]) for call in calls] == [
        ("cosmos", "cosmos-encryption", "encryption"),
        ("blob", "encryption", "custody"),
    ]
