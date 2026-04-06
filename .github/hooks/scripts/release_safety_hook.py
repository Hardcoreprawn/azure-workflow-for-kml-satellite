#!/usr/bin/env python3
"""Require an explicit approval step before release-critical tool actions proceed."""

from __future__ import annotations

import json
import sys
from typing import Any

RELEASE_PATH_MARKERS = [
    ".github/workflows/",
    "infra/tofu/",
    "docs/OPERATIONS_RUNBOOK.md",
    "scripts/reconcile_eventgrid_subscription.py",
    "scripts/validate_dev_infra_gate.py",
]

RELEASE_COMMAND_MARKERS = [
    "tofu apply",
    "gh pr merge",
    "gh workflow run",
    "az functionapp",
    "az staticwebapp",
]


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(flatten_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(flatten_strings(item))
        return strings
    return []


def main() -> int:
    payload = json.load(sys.stdin)
    haystack = "\n".join(flatten_strings(payload)).lower()

    should_gate = any(marker.lower() in haystack for marker in RELEASE_PATH_MARKERS)
    should_gate = should_gate or any(
        marker.lower() in haystack for marker in RELEASE_COMMAND_MARKERS
    )

    if not should_gate:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    "This action touches release-critical workflow, infra, or deployment surfaces. "
                    "Confirm environment scope, validation, and rollback intent before proceeding."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
