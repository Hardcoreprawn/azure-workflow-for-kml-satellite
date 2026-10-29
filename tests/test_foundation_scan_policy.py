"""Owner-scoped scanner exceptions must fail closed on stale or broadened metadata."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.application_contract import ContractError, encode
from scripts.foundation_scan_policy import validate_policy

APPROVED = {
    "misconfigurations": [
        {
            "id": identifier,
            "paths": ["main.tf"],
            "expired_at": "2026-11-27T00:00:00Z",
            "statement": (
                "Owner approved 2026-10-29: "
                "https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/1633#issuecomment-6493579386"
            ),
        }
        for identifier in ("AVD-AZU-0010", "AVD-AZU-0057")
    ]
}


def test_expired_foundation_policy_blocks_even_without_scanner_findings() -> None:
    for today in (date(2026, 11, 27), date(2026, 11, 28)):
        with pytest.raises(ContractError, match="expired"):
            validate_policy(encode(APPROVED), today)


def test_exact_approved_policy_is_valid_before_expiry() -> None:
    assert validate_policy(encode(APPROVED), date(2026, 10, 29)) == APPROVED


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "AVD-AZU-0014"),
        ("paths", ["*"]),
        ("paths", ["other.tf"]),
        ("expired_at", "2027-11-27T00:00:00Z"),
        ("expired_at", "2026-11-27"),
        ("expired_at", "invalid"),
        ("statement", "unapproved"),
    ],
)
def test_policy_rejects_broader_or_invalid_metadata(field: str, value: object) -> None:
    first, second = APPROVED["misconfigurations"]
    policy = {"misconfigurations": [{**first, field: value}, second]}
    with pytest.raises(ContractError):
        validate_policy(encode(policy), date(2026, 10, 29))


def test_policy_rejects_missing_expiry_unknown_fields_and_duplicates() -> None:
    first, second = APPROVED["misconfigurations"]
    candidates = [
        {"misconfigurations": [{k: v for k, v in first.items() if k != "expired_at"}, second]},
        {**APPROVED, "vulnerabilities": []},
        {"misconfigurations": [first, first]},
        {"misconfigurations": [{**first, "resources": ["*"]}, second]},
    ]
    for candidate in candidates:
        with pytest.raises(ContractError):
            validate_policy(encode(candidate), date(2026, 10, 29))


def test_checked_in_policy_and_cli_enforce_expiry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from scripts import foundation_scan_policy as policy

    raw = policy.POLICY.read_bytes()
    assert validate_policy(raw, date(2026, 10, 29))["misconfigurations"]
    monkeypatch.setattr(sys, "argv", ["foundation_scan_policy"])
    monkeypatch.setattr(
        policy, "datetime", SimpleNamespace(now=lambda _: SimpleNamespace(date=lambda: date(2026, 10, 29)))
    )
    assert policy.main() == 0
    assert "two foundation-only" in capsys.readouterr().out
    monkeypatch.setattr(
        policy, "datetime", SimpleNamespace(now=lambda _: SimpleNamespace(date=lambda: date(2026, 11, 27)))
    )
    assert policy.main() == 1
    assert "expired" in capsys.readouterr().err


def test_policy_rejects_bad_entry_shapes_and_types() -> None:
    first, second = APPROVED["misconfigurations"]
    for value in (
        [],
        {"misconfigurations": []},
        {"misconfigurations": "no"},
        {"misconfigurations": [{**first, "id": False}, second]},
        {"misconfigurations": [{**first, "expired_at": 20261127}, second]},
    ):
        with pytest.raises(ContractError):
            validate_policy(encode(value), date(2026, 10, 29))


def test_scanner_proof_checks_exact_exit_and_finding_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import test_foundation_scan_policy as proof

    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(proof.subprocess, "run", run)
    monkeypatch.setattr(Path, "write_text", lambda *args: 0)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _: encode(
            {"Results": [{"Misconfigurations": [{"ID": item, "Status": "FAIL"} for item in proof.EXPECTED]}]}
        ),
    )
    proof.scan_case("trivy", "expired", Path("policy.yaml"), proof.EXPECTED, Path("evidence"))
    assert calls[0][2] == ".validation/foundation/plans"
    assert calls[0][calls[0].index("--ignorefile") + 1] == "policy.yaml"
    with pytest.raises(ContractError, match="exit"):
        proof.scan_case("trivy", "approved", Path("policy.yaml"), set(), Path("evidence"))
    with pytest.raises(ContractError, match=r"expected.*found"):
        proof.scan_case("trivy", "extra", Path("policy.yaml"), {"OTHER"}, Path("evidence"))


def test_all_four_real_scanner_cases_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import test_foundation_scan_policy as proof

    calls: list[tuple[str, set[str]]] = []
    writes: dict[str, bytes] = {}
    monkeypatch.setattr(proof, "read_artifact", lambda _: encode(APPROVED))
    monkeypatch.setattr(
        proof, "datetime", SimpleNamespace(now=lambda _: SimpleNamespace(date=lambda: date(2026, 10, 29)))
    )
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "write_bytes", lambda path, raw: writes.setdefault(path.name, raw))
    monkeypatch.setattr(
        proof, "scan_case", lambda trivy, name, policy, findings, directory: calls.append((name, findings))
    )
    monkeypatch.setattr(sys, "argv", ["test_foundation_scan_policy", "--trivy", "trivy"])
    proof.main()
    assert {name for name, _ in calls} == {"unsuppressed", "approved", "expired", "wrong-path"}
    assert {name for name, findings in calls if not findings} == {"approved"}
    assert set(writes) == {"expired.yaml", "wrong-path.yaml"}
    monkeypatch.setattr(proof, "validate_policy", lambda *args: APPROVED)
    with pytest.raises(ContractError, match="metadata gate accepted"):
        proof.prove_mutations("trivy")


def test_scanner_cannot_reuse_matching_old_report_without_new_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from scripts import test_foundation_scan_policy as proof

    directory = Path(".validation/foundation-stale-report-regression")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "expired.json"
    output.write_bytes(
        encode({"Results": [{"Misconfigurations": [{"ID": item, "Status": "FAIL"} for item in proof.EXPECTED]}]})
    )
    monkeypatch.setattr(
        proof.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "", "no new report")
    )
    try:
        with pytest.raises(ContractError, match="fresh valid"):
            proof.scan_case("trivy", "expired", Path("unused.yaml"), proof.EXPECTED, directory)
        assert "PROVED" not in capsys.readouterr().out
    finally:
        output.unlink(missing_ok=True)
        (directory / "expired.log").unlink(missing_ok=True)
        directory.rmdir()


@pytest.mark.parametrize("raw", [b"not-json", b"null", b"{}", b'{"Results":"invalid"}', b'{"Results":[null]}'])
def test_scanner_rejects_new_invalid_report_without_proof(
    raw: bytes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from scripts import test_foundation_scan_policy as proof

    directory = Path(".validation/foundation-invalid-report-regression")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "expired.json"

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        output.write_bytes(raw)
        return subprocess.CompletedProcess([], 1, "", "")

    monkeypatch.setattr(proof.subprocess, "run", run)
    try:
        with pytest.raises(ContractError, match="fresh valid"):
            proof.scan_case("trivy", "expired", Path("unused.yaml"), proof.EXPECTED, directory)
        assert "PROVED" not in capsys.readouterr().out
    finally:
        output.unlink(missing_ok=True)
        (directory / "expired.log").unlink(missing_ok=True)
        directory.rmdir()
