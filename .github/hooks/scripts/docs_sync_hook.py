#!/usr/bin/env python3
"""Emit advisory docs-sync reminders after relevant tool actions."""

from __future__ import annotations

import json
import sys
from typing import Any

DOC_RULES = {
    "blueprints/": ["docs/API_INTERFACE_REFERENCE.md", "docs/openapi.yaml", "tests/"],
    ".github/workflows/": ["docs/OPERATIONS_RUNBOOK.md", "docs/ROADMAP.md"],
    "infra/tofu/": ["docs/OPERATIONS_RUNBOOK.md", "docs/ROADMAP.md"],
    "scripts/reconcile_eventgrid_subscription.py": ["docs/OPERATIONS_RUNBOOK.md"],
    "scripts/validate_dev_infra_gate.py": ["docs/OPERATIONS_RUNBOOK.md"],
    "website/": ["docs/ROADMAP.md", "README.md"],
}


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

    reminders: list[str] = []
    for marker, docs in DOC_RULES.items():
        if marker.lower() in haystack:
            reminders.extend(docs)

    if not reminders:
        return 0

    ordered = sorted(dict.fromkeys(reminders))
    json.dump(
        {
            "continue": True,
            "systemMessage": (
                "Docs-sync advisory: this change may also require updates in "
                + ", ".join(ordered)
                + ". Check matching tests, roadmap status, API docs, or runbooks before finishing."
            ),
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
