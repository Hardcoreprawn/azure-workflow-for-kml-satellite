"""Tests for the local/CI pipeline e2e gate (#1215).

Only the pure decision logic is unit-tested here — starting a real `func`
process and polling a real orchestrator is inherently I/O, exercised for
real by ``make test-e2e-local``, not something worth mocking in unit tests.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from scripts.e2e_local import assert_pipeline_succeeded, stop_func_host


class TestAssertPipelineSucceeded:
    def test_passes_for_a_real_successful_run(self):
        assert_pipeline_succeeded(
            {
                "runtimeStatus": "Completed",
                "output": {
                    "downloads_succeeded": 1,
                    "download_results": [{"blob_path": "imagery/raw/x/y/z.tif"}],
                },
            }
        )

    def test_rejects_non_completed_status(self):
        with pytest.raises(AssertionError, match="Failed"):
            assert_pipeline_succeeded({"runtimeStatus": "Failed", "output": {}})

    def test_rejects_zero_successful_downloads(self):
        with pytest.raises(AssertionError, match="downloads_succeeded"):
            assert_pipeline_succeeded(
                {
                    "runtimeStatus": "Completed",
                    "output": {"downloads_succeeded": 0, "download_results": []},
                }
            )

    def test_rejects_missing_blob_paths(self):
        with pytest.raises(AssertionError, match="blob_path"):
            assert_pipeline_succeeded(
                {
                    "runtimeStatus": "Completed",
                    "output": {
                        "downloads_succeeded": 1,
                        "download_results": [{"blob_path": ""}],
                    },
                }
            )


class TestStopFuncHost:
    def test_returns_immediately_if_already_exited(self):
        proc = MagicMock()
        proc.poll.return_value = 0
        stop_func_host(proc)
        proc.terminate.assert_not_called()

    def test_terminates_cleanly_when_process_responds(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.return_value = 0
        stop_func_host(proc)
        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()

    def test_escalates_to_kill_when_terminate_times_out(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="func", timeout=10.0), 0]
        stop_func_host(proc)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
