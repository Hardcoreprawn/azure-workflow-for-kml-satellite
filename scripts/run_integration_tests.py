"""Run one integration tier and fail if it produces no passing tests."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

import pytest

INTEGRATION_MARKERS = (
    "integration_azurite",
    "integration_live_stack",
    "integration_external",
)


class RequirePassingIntegrationTests:
    """Turn an all-skipped integration run into a failing gate."""

    def __init__(self) -> None:
        self.passed = 0

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when == "call" and report.passed:
            self.passed += 1

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if exitstatus == pytest.ExitCode.OK and self.passed == 0:
            sys.stdout.write("ERROR: no integration tests passed; selected tier was empty or all-skipped\n")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker", choices=INTEGRATION_MARKERS, required=True)
    parser.add_argument("paths", nargs="+", help="Test paths to collect")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plugin = RequirePassingIntegrationTests()
    return int(pytest.main([*args.paths, "-v", "-m", args.marker], plugins=[plugin]))


if __name__ == "__main__":
    raise SystemExit(main())
