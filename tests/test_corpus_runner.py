"""Tests for the AOI regression corpus runner's pure helper logic (#1222).

I/O-bound behaviour (func host lifecycle, Azurite uploads) is exercised by
``make test-pipeline-local`` / ``scripts/corpus_runner.py`` itself.  Only the
deterministic decision helpers are unit-tested here, matching the pattern
established by ``tests/test_e2e_local.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.corpus_runner import _diff_against_baseline, _extract_actual


class TestExtractActual:
    def test_extracts_all_three_fields(self):
        payload = {
            "output": {
                "aoiCount": 3,
                "downloadsCompleted": 3,
                "artifacts": {"rawImageryPaths": ["a.tif", "b.tif", "c.tif"]},
            }
        }
        actual = _extract_actual(payload)
        assert actual == {"aoi_count": 3, "downloadsCompleted": 3, "rawImageryPathCount": 3}

    def test_handles_missing_output(self):
        actual = _extract_actual({})
        assert actual["aoi_count"] == 0
        assert actual["downloadsCompleted"] == 0
        assert actual["rawImageryPathCount"] == 0

    def test_handles_empty_raw_paths(self):
        payload = {
            "output": {
                "downloadsCompleted": 1,
                "artifacts": {"rawImageryPaths": []},
            }
        }
        actual = _extract_actual(payload)
        assert actual["rawImageryPathCount"] == 0

    def test_handles_none_artifacts(self):
        payload = {"output": {"downloadsCompleted": 2, "artifacts": None}}
        actual = _extract_actual(payload)
        assert actual["rawImageryPathCount"] == 0


class TestDiffAgainstBaseline:
    def _baseline(self, aoi_count=2, downloads=2, paths=2) -> dict:
        return {
            "aoi_count": aoi_count,
            "expected_downloads_completed": downloads,
            "expected_raw_imagery_path_count": paths,
        }

    def _actual(self, aoi_count=2, downloads=2, paths=2) -> dict:
        return {
            "aoi_count": aoi_count,
            "downloadsCompleted": downloads,
            "rawImageryPathCount": paths,
        }

    def test_returns_empty_list_when_all_match(self):
        drifts = _diff_against_baseline(Path("sample.kml"), self._actual(), self._baseline())
        assert drifts == []

    def test_detects_aoi_count_drift(self):
        drifts = _diff_against_baseline(Path("sample.kml"), self._actual(aoi_count=3), self._baseline(aoi_count=2))
        assert any("aoi_count" in d for d in drifts)
        assert any("3" in d for d in drifts)

    def test_detects_downloads_completed_drift(self):
        drifts = _diff_against_baseline(Path("sample.kml"), self._actual(downloads=0), self._baseline(downloads=2))
        assert any("downloadsCompleted" in d for d in drifts)

    def test_detects_raw_imagery_path_count_drift(self):
        drifts = _diff_against_baseline(Path("sample.kml"), self._actual(paths=5), self._baseline(paths=2))
        assert any("rawImageryPathCount" in d for d in drifts)

    def test_skips_field_when_baseline_value_is_none(self):
        """Baseline entries without a field should not trigger a false drift."""
        baseline = {"expected_downloads_completed": None}
        drifts = _diff_against_baseline(Path("sample.kml"), self._actual(), baseline)
        # downloads field is None → not compared
        assert not any("downloadsCompleted" in d for d in drifts)

    def test_multiple_drifts_all_reported(self):
        drifts = _diff_against_baseline(
            Path("sample.kml"),
            self._actual(aoi_count=1, downloads=1, paths=1),
            self._baseline(aoi_count=2, downloads=2, paths=2),
        )
        assert len(drifts) == 3


class TestSaveAndLoadBaseline:
    def test_save_creates_valid_json(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("scripts.corpus_runner.BASELINES_DIR", tmp_path)
        from scripts.corpus_runner import _load_baseline, _save_baseline

        fixture = tmp_path.parent / "sample.kml"
        actual = {"aoi_count": 2, "downloadsCompleted": 2, "rawImageryPathCount": 2}
        _save_baseline(fixture, actual)

        saved = _load_baseline(fixture)
        assert saved is not None
        assert saved["aoi_count"] == 2
        assert saved["expected_downloads_completed"] == 2
        assert saved["expected_raw_imagery_path_count"] == 2

    def test_load_returns_none_when_absent(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("scripts.corpus_runner.BASELINES_DIR", tmp_path)
        from scripts.corpus_runner import _load_baseline

        fixture = tmp_path / "nonexistent.kml"
        assert _load_baseline(fixture) is None

    def test_saved_baseline_has_comment_field(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("scripts.corpus_runner.BASELINES_DIR", tmp_path)
        from scripts.corpus_runner import _save_baseline

        fixture = tmp_path.parent / "sample.kml"
        _save_baseline(fixture, {"aoi_count": 1, "downloadsCompleted": 1, "rawImageryPathCount": 1})

        text = (tmp_path / "sample.json").read_text()
        data = json.loads(text)
        assert "_comment" in data
        assert "update-baseline" in data["_comment"]
