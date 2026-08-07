"""Tests for the local/CI pipeline e2e gate (#1215).

Only the pure decision logic is unit-tested here — starting a real `func`
process and polling a real orchestrator is inherently I/O, exercised for
real by ``make test-pipeline-local``, not something worth mocking in unit tests.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from scripts.e2e_local import (
    REPO_ROOT,
    assert_pipeline_succeeded,
    build_func_host_env,
    stop_func_host,
)


class TestBuildFuncHostEnv:
    def test_always_enables_test_mode(self):
        env = build_func_host_env({})
        assert env["CANOPEX_TEST_MODE"] == "1"

    def test_fills_in_dummy_ciam_values_when_missing(self):
        env = build_func_host_env({})
        assert env["CIAM_AUTHORITY"]
        assert env["CIAM_TENANT_ID"]
        assert env["CIAM_API_AUDIENCE"]

    def test_preserves_a_real_ciam_value_if_already_set(self):
        env = build_func_host_env({"CIAM_TENANT_ID": "real-tenant"})
        assert env["CIAM_TENANT_ID"] == "real-tenant"

    def test_always_pins_script_root_to_repo_root(self):
        """Dockerfile.base sets AzureWebJobsScriptRoot=/home/site/wwwroot for
        the production container convention; func start trusts it over the
        actual working directory, so any image inheriting it makes func
        silently look for function_app.py in the wrong place. This must be
        overridden unconditionally, never a setdefault."""
        env = build_func_host_env({"AzureWebJobsScriptRoot": "/home/site/wwwroot"})
        assert env["AzureWebJobsScriptRoot"] == str(REPO_ROOT)

    def test_forces_filesystem_secrets_storage(self):
        """The Functions host's blob-backed secrets repository resolves
        devstoreaccount1 straight to 127.0.0.1, ignoring AzureWebJobsStorage's
        actual endpoint — breaks whenever Azurite isn't on localhost."""
        env = build_func_host_env({})
        assert env["AzureWebJobsSecretStorageType"] == "files"  # pragma: allowlist secret

    def test_fills_in_azure_web_jobs_storage_when_missing(self):
        env = build_func_host_env({})
        assert "AzureWebJobsStorage" in env
        assert env["AzureWebJobsStorage"]

    def test_preserves_existing_azure_web_jobs_storage(self):
        env = build_func_host_env({"AzureWebJobsStorage": "UseDevelopmentStorage=true"})
        assert env["AzureWebJobsStorage"] == "UseDevelopmentStorage=true"


class TestAssertPipelineSucceeded:
    def test_passes_for_a_real_successful_run(self):
        assert_pipeline_succeeded(
            {
                "runtimeStatus": "Completed",
                "output": {
                    "downloadsCompleted": 1,
                    "artifacts": {"rawImageryPaths": ["imagery/raw/x/y/z.tif"]},
                },
            }
        )

    def test_rejects_non_completed_status(self):
        with pytest.raises(AssertionError, match="Failed"):
            assert_pipeline_succeeded({"runtimeStatus": "Failed", "output": {}})

    def test_rejects_zero_completed_downloads(self):
        with pytest.raises(AssertionError, match="completed download"):
            assert_pipeline_succeeded(
                {
                    "runtimeStatus": "Completed",
                    "output": {"downloadsCompleted": 0, "artifacts": {"rawImageryPaths": []}},
                }
            )

    def test_rejects_missing_raw_imagery_paths(self):
        with pytest.raises(AssertionError, match="rawImageryPaths"):
            assert_pipeline_succeeded(
                {
                    "runtimeStatus": "Completed",
                    "output": {"downloadsCompleted": 1, "artifacts": {"rawImageryPaths": []}},
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
