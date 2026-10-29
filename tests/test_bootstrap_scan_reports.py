"""Application-phase scanner findings remain publishable after a failed gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("phase", ("state", "namespace", "custody", "encryption"))
def test_each_existing_bootstrap_report_uploads_after_failure(phase: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text())
    steps = workflow["jobs"]["trivy-iac"]["steps"]
    scan_index = next(index for index, step in enumerate(steps) if step.get("with", {}).get("scan") == "bootstrap")
    base = steps[scan_index]["with"]["output"]
    report = base if phase == "state" else f"{base}.{phase}"
    uploads = [(index, step) for index, step in enumerate(steps) if step.get("with", {}).get("sarif_file") == report]
    assert len(uploads) == 1, f"Missing unique upload for {report}"
    index, upload = uploads[0]
    assert index > scan_index
    assert upload["uses"].startswith("github/codeql-action/upload-sarif@")
    assert upload["if"] == f"always() && hashFiles('{report}') != ''"
    category = "trivy-bootstrap" if phase == "state" else f"trivy-bootstrap-{phase}"
    assert upload["with"]["category"] == category
    assert sum(step.get("with", {}).get("category") == category for step in steps) == 1
    assert steps[scan_index].get("continue-on-error", False) is False


def test_bootstrap_scan_emits_the_phase_report_paths_consumed_by_ci() -> None:
    result = subprocess.run(
        ["make", "--dry-run", "scan-bootstrap", "TRIVY_FORMAT=sarif", "TRIVY_OUTPUT=trivy-bootstrap.sarif"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "for phase in namespace custody encryption;" in result.stdout
    assert '--output "trivy-bootstrap.sarif.$phase"' in result.stdout
    assert "--exit-code 1" in result.stdout
