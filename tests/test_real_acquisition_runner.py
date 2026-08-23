"""Tests for the real-acquisition runner's pure helper logic (#1379).

I/O-bound behaviour (func host lifecycle, real Planetary Computer
acquisition, Azurite uploads) is exercised by running
``scripts/real_acquisition_runner.py`` itself against a live stack — not
something worth mocking in unit tests. Only the deterministic decision
helpers are unit-tested here, matching the pattern established by
``tests/test_corpus_runner.py`` and ``tests/test_e2e_local.py``.
"""

from __future__ import annotations

import base64
import json
import os

from real_acquisition_runner import (
    DEFAULT_FORMATS,
    _build_run_summary,
    _configure_real_acquisition_environment,
    _test_principal_header,
    _wdpa_configuration_warning,
)


class TestTestPrincipalHeader:
    def test_round_trips_the_given_user_id(self):
        """_fetch_export authenticates its own export-fetch calls as the same
        identity the ticket was uploaded under (CANOPEX_ALLOW_TEST_PRINCIPAL,
        #1379) — must decode back to exactly that user_id."""
        header = _test_principal_header("real-acquisition-runner")
        principal = json.loads(base64.b64decode(header))
        assert principal["userId"] == "real-acquisition-runner"

    def test_produces_valid_base64(self):
        header = _test_principal_header("some-user")
        # Raises if not valid base64 — validate=True matches the server-side decoder.
        base64.b64decode(header, validate=True)


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


class TestWdpaConfiguration:
    def test_warns_when_token_is_missing(self, monkeypatch):
        monkeypatch.delenv("WDPA_API_TOKEN", raising=False)
        warning = _wdpa_configuration_warning()
        assert warning is not None
        assert "WDPA_API_TOKEN" in warning

    def test_does_not_warn_when_token_is_configured(self, monkeypatch):
        monkeypatch.setenv("WDPA_API_TOKEN", "configured")
        assert _wdpa_configuration_warning() is None

    def test_sets_conservative_frame_concurrency_by_default(self, monkeypatch):
        monkeypatch.delenv("ENRICHMENT_FRAME_CONCURRENCY", raising=False)
        _configure_real_acquisition_environment()
        assert os.environ["ENRICHMENT_FRAME_CONCURRENCY"] == "1"

    def test_preserves_explicit_frame_concurrency(self, monkeypatch):
        monkeypatch.setenv("ENRICHMENT_FRAME_CONCURRENCY", "2")
        _configure_real_acquisition_environment()
        assert os.environ["ENRICHMENT_FRAME_CONCURRENCY"] == "2"
