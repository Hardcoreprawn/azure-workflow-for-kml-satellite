"""Tests for the real-acquisition runner's pure helper logic (#1379).

I/O-bound behaviour (func host lifecycle, real Planetary Computer
acquisition, Azurite uploads) is exercised by running
``scripts/real_acquisition_runner.py`` itself against a live stack — not
something worth mocking in unit tests. Only the deterministic decision
helpers are unit-tested here, matching the pattern established by
``tests/test_corpus_runner.py`` and ``tests/test_e2e_local.py``.
"""

from __future__ import annotations

from real_acquisition_runner import DEFAULT_FORMATS, _build_run_summary


class TestBuildRunSummary:
    def test_extracts_all_fields_from_a_completed_run(self):
        payload = {
            "runtimeStatus": "Completed",
            "output": {
                "aoiCount": 2,
                "downloadsCompleted": 4,
                "artifacts": {"rawImageryPaths": ["a.tif", "b.tif", "c.tif", "d.tif"]},
            },
        }
        summary = _build_run_summary(payload)
        assert summary == {
            "runtimeStatus": "Completed",
            "aoiCount": 2,
            "downloadsCompleted": 4,
            "rawImageryPathCount": 4,
        }

    def test_handles_missing_output(self):
        summary = _build_run_summary({"runtimeStatus": "Failed"})
        assert summary["aoiCount"] == 0
        assert summary["downloadsCompleted"] == 0
        assert summary["rawImageryPathCount"] == 0

    def test_handles_none_artifacts(self):
        payload = {"runtimeStatus": "Completed", "output": {"downloadsCompleted": 1, "artifacts": None}}
        summary = _build_run_summary(payload)
        assert summary["rawImageryPathCount"] == 0

    def test_handles_empty_raw_paths(self):
        payload = {
            "runtimeStatus": "Completed",
            "output": {"downloadsCompleted": 1, "artifacts": {"rawImageryPaths": []}},
        }
        summary = _build_run_summary(payload)
        assert summary["rawImageryPathCount"] == 0


class TestDefaultFormats:
    def test_defaults_cover_all_three_eudr_export_formats(self):
        assert set(DEFAULT_FORMATS) == {"eudr-pdf", "eudr-geojson", "eudr-csv"}
