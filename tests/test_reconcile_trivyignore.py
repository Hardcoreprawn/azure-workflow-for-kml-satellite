"""Tests for scripts/reconcile_trivyignore.py.

The reconciler decides, from a fresh Trivy image scan, whether each CVE
suppression in .trivyignore should be removed (resolved), renewed (still
present, no installable fix), or left alone (still present, not due).
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from scripts.reconcile_trivyignore import (
    Entry,
    is_cve,
    parse_ignore_file,
    present_ids_from_scans,
    reconcile,
)

TODAY = date(2026, 6, 23)


def _scan(*vuln_ids: str) -> dict:
    """Build a minimal Trivy JSON scan result containing the given CVE IDs."""
    return {
        "Results": [
            {
                "Target": "test",
                "Vulnerabilities": [
                    {"VulnerabilityID": vid, "Severity": "HIGH"} for vid in vuln_ids
                ],
            }
        ]
    }


# ── is_cve ────────────────────────────────────────────────────────────────


def test_is_cve_true_for_cve_ids():
    assert is_cve("CVE-2026-12345")
    assert is_cve("cve-2026-1")


def test_is_cve_false_for_config_findings():
    assert not is_cve("AZU-0012")
    assert not is_cve("AVD-AZU-0061")


# ── parse_ignore_file ─────────────────────────────────────────────────────


def test_parse_skips_comments_and_blanks():
    text = "# header\n\nCVE-2026-1 # exp:2026-07-01 note\n# trailing\n"
    entries = parse_ignore_file(text)
    assert entries == [Entry(3, "CVE-2026-1 # exp:2026-07-01 note", "CVE-2026-1", date(2026, 7, 1))]


def test_parse_records_missing_expiry_as_none():
    entries = parse_ignore_file("CVE-2026-2 no exp here\n")
    assert entries[0].expiry is None


def test_parse_records_invalid_expiry_as_none():
    entries = parse_ignore_file("CVE-2026-3 # exp:not-a-date\n")
    assert entries[0].expiry is None


# ── present_ids_from_scans ────────────────────────────────────────────────


def test_present_ids_unions_multiple_scans_uppercased():
    scans = [_scan("CVE-2026-1"), _scan("cve-2026-2")]
    assert present_ids_from_scans(scans) == {"CVE-2026-1", "CVE-2026-2"}


def test_present_ids_handles_empty_results():
    assert present_ids_from_scans([{"Results": []}, {}]) == set()


# ── reconcile: removal of resolved CVEs ───────────────────────────────────


def test_resolved_cve_is_removed():
    text = "CVE-2026-1 # exp:2026-07-01 waiting on base rebuild\n"
    result = reconcile(text, present_ids=set(), today=TODAY)
    assert result.text == ""
    assert [a.kind for a in result.actions] == ["removed"]


def test_resolved_cve_removed_even_if_not_yet_expired():
    # exp far in the future, but the CVE is gone from the image -> remove.
    text = "CVE-2026-1 # exp:2027-01-01 note\n"
    result = reconcile(text, present_ids=set(), today=TODAY)
    assert result.text == ""
    assert result.actions[0].kind == "removed"


def test_medium_only_cve_is_removed():
    # A HIGH/CRITICAL scan never lists a MEDIUM CVE, so it reads as resolved.
    text = "CVE-2025-8869 # exp:2026-07-01 pip medium\n"
    result = reconcile(text, present_ids=set(), today=TODAY)
    assert result.text == ""


# ── reconcile: renewal of still-present CVEs ──────────────────────────────


def test_still_present_expired_cve_is_renewed():
    text = "CVE-2026-1 # exp:2026-06-16 still in host\n"
    result = reconcile(text, present_ids={"CVE-2026-1"}, today=TODAY, extend_days=30)
    assert "exp:2026-07-23" in result.text
    assert result.actions[0].kind == "renewed"


def test_still_present_soon_to_expire_cve_is_renewed():
    # exp within the renew window (default 14 days) -> renew proactively.
    text = "CVE-2026-1 # exp:2026-06-30 note\n"
    result = reconcile(text, present_ids={"CVE-2026-1"}, today=TODAY, extend_days=30)
    assert "exp:2026-07-23" in result.text
    assert result.actions[0].kind == "renewed"


def test_still_present_comfortably_future_cve_is_kept_unchanged():
    text = "CVE-2026-1 # exp:2026-09-01 note\n"
    result = reconcile(text, present_ids={"CVE-2026-1"}, today=TODAY)
    assert result.text == text
    assert result.actions[0].kind == "kept"
    assert result.changed_actions == ()


def test_still_present_missing_expiry_gets_one_appended():
    text = "CVE-2026-1 no exp token\n"
    result = reconcile(text, present_ids={"CVE-2026-1"}, today=TODAY, extend_days=30)
    assert "exp:2026-07-23" in result.text
    assert result.actions[0].kind == "renewed"


# ── reconcile: config entries and comments untouched ──────────────────────


def test_config_findings_are_never_touched():
    text = "AZU-0012 # exp:2026-01-01 storage acl\nAVD-AZU-0061 # exp:2026-01-01 false positive\n"
    # Even though these dates are long past and they are absent from the scan,
    # config findings must be preserved verbatim.
    result = reconcile(text, present_ids=set(), today=TODAY)
    assert result.text == text
    assert result.changed_actions == ()


def test_comments_and_blank_lines_preserved_verbatim():
    text = "# header line\n\nCVE-2026-1 # exp:2026-09-01 note\n\n# footer\n"
    result = reconcile(text, present_ids={"CVE-2026-1"}, today=TODAY)
    assert result.text == text


def test_never_adds_new_suppression_for_unlisted_finding():
    # A finding present in the scan but absent from the file must not be added.
    text = "CVE-2026-1 # exp:2026-09-01 note\n"
    result = reconcile(text, present_ids={"CVE-2026-1", "CVE-2026-999"}, today=TODAY)
    assert "CVE-2026-999" not in result.text


# ── reconcile: mixed real-world file ──────────────────────────────────────


def test_mixed_file_reconciles_each_entry_independently():
    text = (
        "# config exceptions\n"
        "AZU-0012 # exp:2026-07-09 storage acl\n"
        "\n"
        "# container CVEs\n"
        "CVE-2026-RESOLVED # exp:2026-06-16 gone now\n".replace(
            "CVE-2026-RESOLVED", "CVE-2026-1000"
        )
        + "CVE-2026-2000 # exp:2026-06-16 still present, expired\n"
        + "CVE-2026-3000 # exp:2026-12-01 still present, future\n"
    )
    result = reconcile(
        text,
        present_ids={"CVE-2026-2000", "CVE-2026-3000"},
        today=TODAY,
        extend_days=30,
    )
    # Resolved one dropped.
    assert "CVE-2026-1000" not in result.text
    # Expired-but-present one renewed.
    assert "CVE-2026-2000 # exp:2026-07-23" in result.text
    # Future-and-present one untouched.
    assert "CVE-2026-3000 # exp:2026-12-01" in result.text
    # Config + comments preserved.
    assert "AZU-0012 # exp:2026-07-09 storage acl" in result.text
    assert "# container CVEs" in result.text


def test_trailing_newline_preserved_or_absent():
    with_nl = reconcile("CVE-2026-1 # exp:2026-09-01\n", {"CVE-2026-1"}, today=TODAY)
    assert with_nl.text.endswith("\n")
    without_nl = reconcile("CVE-2026-1 # exp:2026-09-01", {"CVE-2026-1"}, today=TODAY)
    assert not without_nl.text.endswith("\n")


# ── round-trip via JSON-loaded scans ──────────────────────────────────────


def test_present_ids_from_real_trivy_shape(tmp_path):
    scan = {
        "Results": [
            {"Target": "debian", "Vulnerabilities": None},
            {
                "Target": "python",
                "Vulnerabilities": [
                    {"VulnerabilityID": "CVE-2026-1", "Severity": "HIGH", "PkgName": "x"}
                ],
            },
        ]
    }
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(scan))
    loaded = json.loads(path.read_text())
    assert present_ids_from_scans([loaded]) == {"CVE-2026-1"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
