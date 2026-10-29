"""Execute unsuppressed, approved, expired and wrong-path scans of actual native plans."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.application_contract import ContractError, encode, read_artifact
from scripts.foundation_scan_policy import POLICY, validate_policy

EXPECTED = {"AZU-0010", "AZU-0057"}


def scan_case(trivy: str, name: str, policy: Path, findings: set[str], directory: Path) -> None:
    output = directory / f"{name}.json"
    output.unlink(missing_ok=True)
    result = subprocess.run(
        [
            trivy,
            "config",
            ".validation/foundation/plans",
            "--misconfig-scanners",
            "terraformplan-json",
            "--ignorefile",
            str(policy),
            "--severity",
            "CRITICAL,HIGH,MEDIUM",
            "--exit-code",
            "1",
            "--format",
            "json",
            "--output",
            str(output),
            "--skip-version-check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    (directory / f"{name}.log").write_text(result.stderr)
    if result.returncode != (1 if findings else 0):
        raise ContractError(f"{name}: scanner exit {result.returncode}, expected an actual finding-based result")
    try:
        report = json.loads(output.read_bytes())
        if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
            raise ValueError("scanner report must contain a Results array")
        actual = {
            finding["ID"]
            for target in report["Results"]
            for finding in target.get("Misconfigurations", [])
            if finding.get("Status") == "FAIL"
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ContractError(f"{name}: scanner did not produce a fresh valid JSON report") from exc
    if actual != findings:
        raise ContractError(f"{name}: expected {sorted(findings)}, found {sorted(actual)}")
    print(f"PROVED {name}: exit={result.returncode}, findings={sorted(actual)}")


def prove_mutations(trivy: str) -> None:
    policy = validate_policy(read_artifact(POLICY), datetime.now(UTC).date())
    directory = Path(".validation/foundation/exception-proofs")
    directory.mkdir(parents=True, exist_ok=True)
    for name, change in (
        ("expired", {"expired_at": "2000-01-01T00:00:00Z"}),
        ("wrong-path", {"paths": ["unrelated.tf"]}),
    ):
        candidate = {"misconfigurations": [{**entry, **change} for entry in policy["misconfigurations"]]}
        raw = encode(candidate)
        path = directory / f"{name}.yaml"
        path.write_bytes(raw)
        try:
            validate_policy(raw, datetime.now(UTC).date())
        except ContractError:
            pass
        else:
            raise ContractError(f"{name}: metadata gate accepted an invalid exception")
        scan_case(trivy, name, path, EXPECTED, directory)
    scan_case(trivy, "unsuppressed", Path("/dev/null"), EXPECTED, directory)
    scan_case(trivy, "approved", POLICY, set(), directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trivy", default="trivy")
    args = parser.parse_args()
    prove_mutations(args.trivy)


if __name__ == "__main__":
    main()
