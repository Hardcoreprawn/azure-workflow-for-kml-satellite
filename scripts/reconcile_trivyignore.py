#!/usr/bin/env python3
"""Reconcile ``.trivyignore`` against a fresh Trivy image scan.

The ``.trivyignore`` file accumulates temporary CVE suppressions that wait on an
upstream base-image fix. They carry an ``exp:YYYY-MM-DD`` date so a stale
suppression eventually fails the hygiene check. A pure date check, however,
cannot tell whether the CVE is *actually* still in the image — so it can break a
perfectly clean, working image just because a calendar date passed.

This module reconciles the suppression list against ground truth: the Trivy scan
of the freshly built/published image (scanned with ``--severity HIGH,CRITICAL
--ignore-unfixed`` and **without** the ignore file, so every still-fixable
HIGH/CRITICAL finding is visible).

Because the base image is rebuilt (``apt-get upgrade``) immediately before the
scan, the two outcomes are unambiguous:

* **Resolved** — the CVE is no longer in the scan. The rebuild picked up the
  fix, so the suppression is dead weight and is removed.
* **Still present** — the CVE survived a fresh rebuild, so no installable fix
  exists yet (mirror not propagated, or upstream base image not refreshed).
  Nothing more can be done now, so the expiry is renewed if it is expired or
  about to expire. A comfortably-future expiry is left untouched to avoid churn.

Non-CVE config findings (``AZU-*`` / ``AVD-*`` Trivy misconfiguration IDs) are
never touched — they are infrastructure policy decisions, not image CVEs, and
cannot be judged from an image scan.

The reconciler never *adds* a suppression: a new HIGH/CRITICAL finding that is
not already ignored is a real exposure that the build's blocking Trivy gate must
fail on, not something to auto-hide.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

EXP_RE = re.compile(r"\bexp:(\d{4}-\d{2}-\d{2})\b")
CVE_RE = re.compile(r"^CVE-\d{4}-\d+$", re.IGNORECASE)

DEFAULT_EXTEND_DAYS = 30
DEFAULT_RENEW_WINDOW_DAYS = 14


@dataclass(frozen=True)
class Entry:
    """A single non-comment suppression line in ``.trivyignore``."""

    line_no: int
    raw: str
    vuln_id: str
    expiry: date | None


@dataclass(frozen=True)
class Action:
    """A reconciliation decision for one CVE entry."""

    vuln_id: str
    kind: str  # "removed" | "renewed" | "kept"
    detail: str


@dataclass(frozen=True)
class Reconciliation:
    """The result of reconciling a file against a scan."""

    text: str
    actions: tuple[Action, ...]

    @property
    def changed_actions(self) -> tuple[Action, ...]:
        return tuple(a for a in self.actions if a.kind != "kept")


def is_cve(vuln_id: str) -> bool:
    """Return True for image CVE IDs, False for config findings (AZU/AVD/...)."""
    return bool(CVE_RE.match(vuln_id))


def parse_ignore_file(text: str) -> list[Entry]:
    """Parse non-comment suppression lines, preserving 1-based line numbers."""
    entries: list[Entry] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        vuln_id = stripped.split()[0]
        match = EXP_RE.search(raw)
        expiry: date | None = None
        if match:
            try:
                expiry = date.fromisoformat(match.group(1))
            except ValueError:
                expiry = None
        entries.append(Entry(line_no, raw, vuln_id, expiry))
    return entries


def present_ids_from_scans(scans: list[dict]) -> set[str]:
    """Collect every VulnerabilityID reported across one or more Trivy JSON scans."""
    present: set[str] = set()
    for scan in scans:
        for result in scan.get("Results", []) or []:
            for vuln in result.get("Vulnerabilities", []) or []:
                vid = vuln.get("VulnerabilityID")
                if vid:
                    present.add(vid.upper())
    return present


def suppressed_ids(ignore_text: str) -> set[str]:
    """All vuln IDs currently suppressed by the ignore file (upper-cased)."""
    return {e.vuln_id.upper() for e in parse_ignore_file(ignore_text)}


def unsuppressed_findings(scans: list[dict], ignore_text: str) -> list[str]:
    """Present vuln IDs that are NOT suppressed by the ignore file (sorted).

    The image security gate fails when this is non-empty: a present finding with
    no matching suppression is a real, un-triaged exposure.
    """
    return sorted(present_ids_from_scans(scans) - suppressed_ids(ignore_text))


def filter_scan(scan: dict, suppressed: set[str]) -> dict:
    """Return a copy of ``scan`` with suppressed vulnerabilities removed.

    Used to produce a clean SARIF that matches the gate, so suppressed CVEs do
    not reappear in Code Scanning.
    """
    suppressed_upper = {s.upper() for s in suppressed}
    out = dict(scan)
    new_results: list[dict] = []
    for result in scan.get("Results", []) or []:
        new_result = dict(result)
        vulns = result.get("Vulnerabilities") or []
        new_result["Vulnerabilities"] = [
            v for v in vulns if (v.get("VulnerabilityID") or "").upper() not in suppressed_upper
        ]
        new_results.append(new_result)
    out["Results"] = new_results
    return out


def _renew_expiry(raw: str, new_expiry: date) -> str:
    """Return ``raw`` with its exp date set to ``new_expiry``."""
    replaced = EXP_RE.sub(f"exp:{new_expiry.isoformat()}", raw)
    if replaced != raw:
        return replaced
    # No exp token present — append one so the entry stays hygiene-valid.
    return f"{raw.rstrip()}  # exp:{new_expiry.isoformat()}"


def reconcile(
    text: str,
    present_ids: set[str],
    *,
    today: date,
    extend_days: int = DEFAULT_EXTEND_DAYS,
    renew_window_days: int = DEFAULT_RENEW_WINDOW_DAYS,
) -> Reconciliation:
    """Reconcile ``.trivyignore`` text against the set of present CVE IDs.

    * CVE not in ``present_ids`` -> removed.
    * CVE in ``present_ids`` and expired / within the renew window -> renewed to
      ``today + extend_days``.
    * CVE in ``present_ids`` with a comfortably-future expiry -> kept unchanged.
    * Non-CVE (config) entries and comments/blank lines -> kept verbatim.
    """
    present_upper = {vid.upper() for vid in present_ids}
    renew_before = today + timedelta(days=renew_window_days)
    new_expiry = today + timedelta(days=extend_days)

    out_lines: list[str] = []
    actions: list[Action] = []

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(raw)
            continue

        vuln_id = stripped.split()[0]
        if not is_cve(vuln_id):
            out_lines.append(raw)
            continue

        if vuln_id.upper() not in present_upper:
            actions.append(Action(vuln_id, "removed", "resolved — not in fresh image scan"))
            continue  # drop the line

        match = EXP_RE.search(raw)
        current = None
        if match:
            try:
                current = date.fromisoformat(match.group(1))
            except ValueError:
                current = None

        needs_renew = current is None or current <= renew_before
        if needs_renew:
            out_lines.append(_renew_expiry(raw, new_expiry))
            actions.append(
                Action(
                    vuln_id,
                    "renewed",
                    f"still present, no installable fix — exp -> {new_expiry.isoformat()}",
                )
            )
        else:
            out_lines.append(raw)
            exp_text = current.isoformat() if current else "none"
            actions.append(Action(vuln_id, "kept", f"still present, exp {exp_text} not due"))

    if not out_lines:
        new_text = ""
    else:
        new_text = "\n".join(out_lines)
        if text.endswith("\n"):
            new_text += "\n"
    return Reconciliation(new_text, tuple(actions))


def _load_scans(paths: list[Path]) -> list[dict]:
    scans: list[dict] = []
    for path in paths:
        scans.append(json.loads(path.read_text()))
    return scans


def _format_summary(actions: tuple[Action, ...]) -> str:
    removed = [a for a in actions if a.kind == "removed"]
    renewed = [a for a in actions if a.kind == "renewed"]
    lines: list[str] = []
    if removed:
        lines.append(f"Removed {len(removed)} resolved suppression(s):")
        lines.extend(f"  - {a.vuln_id}: {a.detail}" for a in removed)
    if renewed:
        lines.append(f"Renewed {len(renewed)} still-present suppression(s):")
        lines.extend(f"  - {a.vuln_id}: {a.detail}" for a in renewed)
    if not lines:
        lines.append("No changes — .trivyignore is in sync with the scan.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ignore-file",
        type=Path,
        default=Path(".trivyignore"),
        help="Path to the .trivyignore file (default: .trivyignore).",
    )
    parser.add_argument(
        "--scan",
        type=Path,
        action="append",
        required=True,
        help="Trivy JSON scan result (repeatable). Scan without the ignore file, "
        "--severity HIGH,CRITICAL --ignore-unfixed.",
    )
    parser.add_argument(
        "--extend-days",
        type=int,
        default=DEFAULT_EXTEND_DAYS,
        help=f"Days to renew a still-present entry (default: {DEFAULT_EXTEND_DAYS}).",
    )
    parser.add_argument(
        "--renew-window-days",
        type=int,
        default=DEFAULT_RENEW_WINDOW_DAYS,
        help="Renew still-present entries expiring within this many days "
        f"(default: {DEFAULT_RENEW_WINDOW_DAYS}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Rewrite the ignore file in place with the reconciled content.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the file would change (drift); do not write.",
    )
    mode.add_argument(
        "--gate",
        action="store_true",
        help="Exit 1 if any present finding is not suppressed by the ignore file "
        "(the base-image security gate).",
    )
    parser.add_argument(
        "--write-filtered",
        type=Path,
        help="Write the scan with suppressed findings removed (for a clean SARIF "
        "that matches the gate). Requires exactly one --scan.",
    )
    args = parser.parse_args(argv)

    text = args.ignore_file.read_text()
    scans = _load_scans(args.scan)

    # Optional: emit a suppression-filtered scan so the SARIF matches the gate.
    if args.write_filtered:
        if len(scans) != 1:
            parser.error("--write-filtered requires exactly one --scan")
        args.write_filtered.write_text(json.dumps(filter_scan(scans[0], suppressed_ids(text))))
        print(f"Wrote suppression-filtered scan to {args.write_filtered}")

    # Gate mode: block on present findings that are not suppressed.
    if args.gate:
        unsuppressed = unsuppressed_findings(scans, text)
        if unsuppressed:
            print("::error::Unsuppressed HIGH/CRITICAL findings in image scan:")
            for vid in unsuppressed:
                print(f"  - {vid}")
            return 1
        print("Gate passed: no unsuppressed HIGH/CRITICAL findings.")
        return 0

    present = present_ids_from_scans(scans)
    today = datetime.now(UTC).date()
    result = reconcile(
        text,
        present,
        today=today,
        extend_days=args.extend_days,
        renew_window_days=args.renew_window_days,
    )

    print(_format_summary(result.actions))

    changed = result.text != text
    if args.write and changed:
        args.ignore_file.write_text(result.text)
        print(f"Wrote reconciled {args.ignore_file}")
    if args.check and changed:
        print("::error::.trivyignore is out of sync with the image scan (drift).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
