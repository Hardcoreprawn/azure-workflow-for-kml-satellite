"""Contracts for integration-suite partitioning and execution evidence."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
PYPROJECT = ROOT / "pyproject.toml"
TIER_MARKERS = frozenset({"integration_azurite", "integration_live_stack", "integration_external"})


def _marker_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return _marker_name(node.func)
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    ):
        return node.attr
    return None


def _integration_marker_groups(source: str, *, filename: str) -> list[set[str]]:
    tree = ast.parse(source, filename=filename)
    marker_groups: list[set[str]] = []

    for node in ast.walk(tree):
        value: ast.expr | None = None
        is_plain_pytestmark = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        )
        is_annotated_pytestmark = (
            isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "pytestmark"
        )
        if is_plain_pytestmark or is_annotated_pytestmark:
            value = node.value

        if value is not None:
            values = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
            names = {name for marker in values if (name := _marker_name(marker))}
            if names & ({"integration"} | TIER_MARKERS):
                marker_groups.append(names)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {name for decorator in node.decorator_list if (name := _marker_name(decorator))}
            if names & ({"integration"} | TIER_MARKERS):
                marker_groups.append(names)

    return marker_groups


def _assert_valid_integration_groups(filename: str, marker_groups: list[set[str]]) -> None:
    for markers in marker_groups:
        assigned_tiers = markers & TIER_MARKERS
        assert "integration" in markers, f"{filename} tier marker must also declare the broad integration marker"
        assert len(assigned_tiers) == 1, (
            f"{filename} integration marker must declare exactly one tier; got {sorted(assigned_tiers)}"
        )


def _target_runner_commands(makefile: str, target: str) -> list[str]:
    match = re.search(rf"^{target}:.*?(?=^\S)", makefile, re.MULTILINE | re.DOTALL)
    assert match is not None, f"Missing Make target: {target}"
    return [line.strip() for line in match.group(0).splitlines() if "run_integration_tests.py" in line]


def test_makefile_exposes_each_integration_tier() -> None:
    makefile = MAKEFILE.read_text()

    assert _target_runner_commands(makefile, "test-int") == [
        "uv run python scripts/run_integration_tests.py --marker integration_azurite tests/test_integration.py"
    ]
    assert _target_runner_commands(makefile, "test-int-live") == [
        "uv run python scripts/run_integration_tests.py --marker integration_live_stack "
        "tests/test_pipeline_smoke_e2e.py tests/test_monster_aoi_scale.py"
    ]
    assert _target_runner_commands(makefile, "test-int-stripe") == [
        "uv run python scripts/run_integration_tests.py --marker integration_external tests/test_integration_billing.py"
    ]


def test_pytest_declares_specific_integration_markers() -> None:
    pyproject = PYPROJECT.read_text()

    assert "integration_azurite:" in pyproject
    assert "integration_live_stack:" in pyproject
    assert "integration_external:" in pyproject


def test_every_integration_module_has_exactly_one_tier() -> None:
    integration_modules = []

    test_root = ROOT / "tests"
    candidate_paths = set(test_root.rglob("test_*.py")) | set(test_root.rglob("*_test.py"))
    for path in sorted(candidate_paths):
        marker_groups = _integration_marker_groups(path.read_text(), filename=str(path))
        if not marker_groups:
            continue
        relative_path = path.relative_to(test_root).as_posix()
        integration_modules.append(relative_path)
        _assert_valid_integration_groups(relative_path, marker_groups)

    assert integration_modules == [
        "test_integration.py",
        "test_integration_billing.py",
        "test_monster_aoi_scale.py",
        "test_pipeline_smoke_e2e.py",
    ]


def test_marker_audit_supports_call_form_and_annotated_pytestmark() -> None:
    call_form = "@pytest.mark.integration()\n@pytest.mark.integration_azurite()\ndef test_case(): pass\n"
    annotated = (
        "pytestmark: list[object] = [pytest.mark.integration, pytest.mark.integration_external]\n"
        "def test_case(): pass\n"
    )

    _assert_valid_integration_groups("call_form.py", _integration_marker_groups(call_form, filename="call_form.py"))
    _assert_valid_integration_groups("annotated.py", _integration_marker_groups(annotated, filename="annotated.py"))


@pytest.mark.parametrize(
    "source",
    [
        "@pytest.mark.integration\ndef test_one(): pass\n@pytest.mark.integration_azurite\ndef test_two(): pass\n",
        "pytestmark = [pytest.mark.integration, pytest.mark.integration_azurite, pytest.mark.integration_external]\n",
    ],
)
def test_marker_audit_rejects_split_or_multiple_tiers(source: str) -> None:
    with pytest.raises(AssertionError):
        _assert_valid_integration_groups("invalid.py", _integration_marker_groups(source, filename="invalid.py"))


def test_runner_fails_when_selected_tier_is_all_skipped(tmp_path: Path) -> None:
    test_file = tmp_path / "test_skipped.py"
    test_file.write_text(
        "import pytest\n\n@pytest.mark.integration_azurite\ndef test_skipped():\n    pytest.skip('dependency absent')\n"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_integration_tests.py"),
            "--marker",
            "integration_azurite",
            str(test_file),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == int(pytest.ExitCode.TESTS_FAILED)
    assert "no integration tests passed" in completed.stdout.lower()


def test_runner_succeeds_when_selected_tier_executes(tmp_path: Path) -> None:
    test_file = tmp_path / "test_passed.py"
    test_file.write_text("import pytest\n\n@pytest.mark.integration_azurite\ndef test_passed():\n    assert True\n")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_integration_tests.py"),
            "--marker",
            "integration_azurite",
            str(test_file),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_runner_preserves_no_tests_collected_exit_code(tmp_path: Path) -> None:
    test_file = tmp_path / "test_other_tier.py"
    test_file.write_text(
        "import pytest\n\n@pytest.mark.integration_external\ndef test_other_tier():\n    assert True\n"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_integration_tests.py"),
            "--marker",
            "integration_azurite",
            str(test_file),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == int(pytest.ExitCode.NO_TESTS_COLLECTED)
