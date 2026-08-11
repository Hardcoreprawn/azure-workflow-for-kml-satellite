"""Run targeted pytest selectors with fixed edit-loop safety flags."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys


def parse_test_selectors(raw_value: str) -> list[str]:
    """Parse paths/node IDs while rejecting caller-supplied pytest options."""
    selectors = shlex.split(raw_value)
    if not selectors:
        raise ValueError("TESTS must contain at least one test path or node ID")
    if any(selector.startswith(("-", "@")) for selector in selectors):
        raise ValueError("TESTS accepts test paths and node IDs only, not pytest options or argfiles")
    return selectors


def build_pytest_command(selectors: list[str]) -> list[str]:
    """Build the quiet, fail-fast pytest command used by the edit loop."""
    if not selectors:
        raise ValueError("At least one test selector is required")
    return [sys.executable, "-m", "pytest", *selectors, "-q", "-x", "--tb=short", "--no-cov"]


def main() -> int:
    try:
        selectors = parse_test_selectors(os.environ.get("TESTS", ""))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    pytest_env = os.environ.copy()
    pytest_env.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(build_pytest_command(selectors), check=False, env=pytest_env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
