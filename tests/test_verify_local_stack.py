"""Tests for verify_local_stack.py's pure decision logic (#1411).

Live behaviour (hitting real containers, running the real pipeline) is
exercised by running the script itself against `make dev-all` — not
something worth mocking in unit tests, matching the convention in
tests/test_corpus_runner.py / tests/test_validate_blueprint_parity.py.
"""

from __future__ import annotations

from verify_local_stack import EXPORT_FORMATS, summarize


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
