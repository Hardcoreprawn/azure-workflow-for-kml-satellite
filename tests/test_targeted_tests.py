"""Tests for the structured fast-test command runner."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_targeted_tests import build_pytest_command, parse_test_selectors

ROOT = Path(__file__).resolve().parent.parent


def test_parses_quoted_parameterized_node_id() -> None:
    selectors = parse_test_selectors('"tests/test_example.py::test_case[value with spaces]"')

    assert selectors == ["tests/test_example.py::test_case[value with spaces]"]


def test_rejects_pytest_options_in_selectors() -> None:
    with pytest.raises(ValueError, match="paths and node IDs only"):
        parse_test_selectors("tests/test_example.py --tb=long")


def test_rejects_pytest_argfiles() -> None:
    with pytest.raises(ValueError, match="argfiles"):
        parse_test_selectors("@/tmp/pytest-args")


def test_builds_fixed_quiet_fail_fast_command_without_coverage() -> None:
    command = build_pytest_command(["tests/test_example.py::test_case"])

    assert command == [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_example.py::test_case",
        "-q",
        "-x",
        "--tb=short",
        "--no-cov",
    ]


def test_shell_metacharacters_remain_literal_arguments() -> None:
    selectors = parse_test_selectors('"tests/test_example.py;touch should-not-exist"')

    assert selectors == ["tests/test_example.py;touch should-not-exist"]


def test_make_target_executes_real_selector() -> None:
    selector = "tests/test_rate_limit.py::TestGetClientIp::test_returns_unknown_when_no_headers"
    env = {**os.environ, "PYTEST_ADDOPTS": "--collect-only"}

    completed = subprocess.run(
        ["make", "test-fast", f"TESTS={selector}"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_make_target_executes_parameterized_node_with_spaces(tmp_path: Path) -> None:
    test_file = tmp_path / "test_parameterized.py"
    test_file.write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', ['ok'], ids=['value with spaces'])\n"
        "def test_case(value):\n"
        "    assert value == 'ok'\n"
    )
    selector = f'"{test_file}::test_case[value with spaces]"'
    shell_command = f"make test-fast TESTS={shlex.quote(selector)}"

    completed = subprocess.run(
        ["bash", "-c", shell_command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_make_target_does_not_execute_shell_metacharacters(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    selector = f'"tests/test_example.py;touch {marker}"'

    completed = subprocess.run(
        ["make", "test-fast", f"TESTS={selector}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert not marker.exists()


def test_make_target_does_not_expand_make_functions(tmp_path: Path) -> None:
    marker = tmp_path / "make-should-not-create-this"
    selector = f"$(shell touch {marker}) tests/test_example.py"

    completed = subprocess.run(
        ["make", "test-fast", f"TESTS={selector}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert not marker.exists()


def test_make_target_does_not_expand_environment_make_functions(tmp_path: Path) -> None:
    marker = tmp_path / "environment-should-not-create-this"
    env = {**os.environ, "TESTS": f"$(shell touch {marker}) tests/test_example.py"}

    completed = subprocess.run(
        ["make", "test-fast"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert not marker.exists()


def test_unrelated_make_target_does_not_inherit_tests() -> None:
    completed = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "--eval",
            "print-tests:\n\t@printf '%s' \"$${TESTS+x}\"",
            "print-tests",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout == ""
