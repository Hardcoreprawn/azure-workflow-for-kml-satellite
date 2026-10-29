"""Prove mutation evidence fails closed instead of accepting tool/fixture errors."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import test_foundation_mutations as mutations
from scripts.application_contract import ContractError


def fake_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    writes: dict[str, str] = {}
    monkeypatch.setattr(Path, "exists", lambda _: True)
    monkeypatch.setattr(mutations.shutil, "rmtree", lambda _: None)
    monkeypatch.setattr(mutations.shutil, "copytree", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "symlink_to", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "read_text", lambda _: "secure")
    monkeypatch.setattr(Path, "write_text", lambda path, text: writes.setdefault(path.name, text))
    return writes


@pytest.mark.parametrize(
    "diagnostic", ["Test assertion failed", "Resource postcondition failed", "Resource precondition failed"]
)
def test_mutation_requires_an_executed_security_rejection(monkeypatch: pytest.MonkeyPatch, diagnostic: str) -> None:
    writes = fake_files(monkeypatch)
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout=diagnostic, stderr="")

    monkeypatch.setattr(mutations.subprocess, "run", run)
    mutations.run_mutation("/pinned/tofu", "unit-regression", "secure", "insecure")
    assert writes["main.tf"] == "insecure"
    assert writes["events.jsonl"] == diagnostic
    assert calls[0][-3:] == ["test", "-json", "-verbose"]
    assert "apply" not in calls[0]


def test_mutation_does_not_count_syntax_or_setup_failure_as_red(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_files(monkeypatch)
    monkeypatch.setattr(
        mutations.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, stdout="syntax error", stderr=""),
    )
    with pytest.raises(ContractError, match="unexpected reason"):
        mutations.run_mutation("tofu", "unit-regression", "secure", "insecure")
    with pytest.raises(ContractError, match="anchor missing"):
        mutations.run_mutation("tofu", "unit-regression", "missing", "insecure")


def test_mutation_rejects_success_shaped_gates_and_accepts_inventory_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_files(monkeypatch)
    monkeypatch.setattr(
        mutations.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    )
    monkeypatch.setattr(mutations, "export_plans", lambda *args: None)
    with pytest.raises(ContractError, match="incorrectly accepted"):
        mutations.run_mutation("tofu", "unit-regression", "secure", "insecure")

    def rejected(*args: object) -> None:
        raise ContractError("inventory mismatch")

    monkeypatch.setattr(mutations, "export_plans", rejected)
    mutations.run_mutation("tofu", "unit-regression", "secure", "insecure")


def test_all_ten_mutations_are_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mutations, "run_mutation", lambda tofu, name, before, after, **kwargs: calls.append(name))
    monkeypatch.setattr(sys, "argv", ["test_foundation_mutations", "--tofu", "/pinned/tofu"])
    mutations.main()
    assert len(calls) == 10
    assert calls[-1] == "child-module-resource"


def test_local_module_mutation_initializes_offline_before_native_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_files(monkeypatch)
    monkeypatch.setattr(Path, "mkdir", lambda *args: None)
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(mutations.subprocess, "run", run)

    def rejected(*args: object) -> None:
        raise ContractError("module-free")

    monkeypatch.setattr(mutations, "export_plans", rejected)
    mutations.run_mutation("tofu", "module", "secure", "insecure", with_module=True)
    assert calls[0][-4:] == ["init", "-backend=false", "-input=false", "-lockfile=readonly"]
    assert calls[1][-3:] == ["test", "-json", "-verbose"]
    monkeypatch.setattr(
        mutations.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "", "init failed")
    )
    with pytest.raises(ContractError, match="initialization failed"):
        mutations.run_mutation("tofu", "module", "secure", "insecure", with_module=True)
