"""Tests for verify_local_stack.py's pure decision logic (#1411).

Live behaviour (hitting real containers, running the real pipeline) is
exercised by running the script itself against `make dev-all` — not
something worth mocking in unit tests, matching the convention in
tests/test_corpus_runner.py / tests/test_validate_blueprint_parity.py.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from verify_local_stack import EXPORT_FORMATS, summarize


@pytest.mark.parametrize("state, expected", [("running|healthy", True), ("running|unhealthy", False)])
def test_container_health_uses_project_service_labels(
    monkeypatch: pytest.MonkeyPatch, state: str, expected: bool
) -> None:
    from verify_local_stack import check_container_running

    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "test-project")
    with patch("verify_local_stack.subprocess.run") as run:
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "container-id\n"),
            subprocess.CompletedProcess([], 0, state),
        ]
        assert check_container_running("func") is expected
    selection = run.call_args_list[0].args[0]
    assert "label=com.docker.compose.project=test-project" in selection
    assert "label=com.docker.compose.service=func" in selection
    assert run.call_args_list[1].args[0][-1] == "container-id"


class TestSummarize:
    def test_all_passed(self):
        failed, passed = summarize([("a", True), ("b", True)])
        assert failed == []
        assert passed is True

    def test_some_failed(self):
        failed, passed = summarize([("a", True), ("b", False), ("c", False)])
        assert failed == ["b", "c"]
        assert passed is False

    def test_empty_results_pass(self):
        failed, passed = summarize([])
        assert failed == []
        assert passed is True


class TestExportFormats:
    def test_covers_the_three_eudr_formats(self):
        assert set(EXPORT_FORMATS) == {"eudr-pdf", "eudr-geojson", "eudr-csv"}
