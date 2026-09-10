"""Tests for the local/CI pipeline e2e gate (#1215).

Only the pure decision logic is unit-tested here — starting a real `func`
process and polling a real orchestrator is inherently I/O, exercised for
real by ``make test-pipeline-local``, not something worth mocking in unit tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.e2e_local import (
    DEFAULT_CONTAINER,
    REPO_ROOT,
    assert_pipeline_succeeded,
    build_func_host_env,
    build_representative_case_matrix,
    run_scenario,
    stop_func_host,
    write_e2e_result,
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

    def test_overrides_inherited_storage_with_selected_azurite(self):
        from scripts.e2e_local import AZURITE_CONN_STR

        env = build_func_host_env({"AzureWebJobsStorage": "UseDevelopmentStorage=true"})
        assert env["AzureWebJobsStorage"] == AZURITE_CONN_STR

    def test_test_mode_false_omits_canopex_test_mode(self):
        """scripts/real_acquisition_runner.py (#1379) needs the real imagery
        provider, not the synthetic stub CANOPEX_TEST_MODE selects."""
        env = build_func_host_env({}, test_mode=False)
        assert "CANOPEX_TEST_MODE" not in env

    def test_test_mode_false_strips_an_inherited_value(self):
        """A developer's shell may already export CANOPEX_TEST_MODE from a
        previous test-mode run — it must never leak into a real-acquisition
        run just because the parent process happened to have it set."""
        env = build_func_host_env({"CANOPEX_TEST_MODE": "1"}, test_mode=False)
        assert "CANOPEX_TEST_MODE" not in env

    def test_test_mode_false_still_allows_test_principal_auth(self):
        """real_acquisition_runner.py (#1379) needs real imagery (CANOPEX_TEST_MODE
        unset) but must still be able to authenticate its own export-fetch calls
        via a test X-MS-CLIENT-PRINCIPAL header — CANOPEX_ALLOW_TEST_PRINCIPAL is
        the decoupled flag for exactly that."""
        env = build_func_host_env({}, test_mode=False)
        assert env["CANOPEX_ALLOW_TEST_PRINCIPAL"] == "1"

    def test_test_mode_true_does_not_need_allow_test_principal(self):
        """Stub-imagery runs already get test-principal auth via CANOPEX_TEST_MODE
        itself — no need to also set the decoupled flag."""
        env = build_func_host_env({})
        assert "CANOPEX_ALLOW_TEST_PRINCIPAL" not in env


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


class TestRepresentativeScenario:
    def test_rejected_event_fails_without_polling(self, monkeypatch):
        from scripts import e2e_local as runner

        monkeypatch.setattr(runner, "upload_kml", lambda *_: ("sample.kml", "url", 1))
        submit = MagicMock(side_effect=RuntimeError("Webhook rejected with HTTP 500"))
        poll = MagicMock()
        monkeypatch.setattr(runner, "fire_event_grid", submit)
        monkeypatch.setattr(runner, "poll_orchestration", poll)

        result = runner._run_single_case(build_representative_case_matrix()[0], timeout=1)

        assert submit.call_args.kwargs == {"strict": True}
        poll.assert_not_called()
        assert result["status"] == "Failed"
        assert result["instanceId"] is None
        assert "HTTP 500" in result["error"]

    def test_matrix_containers_match_trigger_contract(self):
        from blueprints.pipeline._blob_url import _validate_blob_event

        for case in build_representative_case_matrix():
            _validate_blob_event("sample.kml", case["container"], {"contentLength": 1})

    def test_timed_out_case_retains_instance_id(self, monkeypatch):
        from scripts import e2e_local as runner

        monkeypatch.setattr(runner, "upload_kml", lambda *_: ("sample.kml", "url", 1))
        monkeypatch.setattr(runner, "fire_event_grid", lambda *args, **kwargs: "pending-instance")

        def timeout(*args, **kwargs):
            raise TimeoutError("last_status=Running")

        monkeypatch.setattr(runner, "poll_orchestration", timeout)
        result = runner._run_single_case(build_representative_case_matrix()[0], timeout=1)
        assert result["instanceId"] == "pending-instance"
        assert result["status"] == "Failed"
        assert "Running" in result["error"]

    def test_scenario_continues_after_failure_and_stops_host(self, monkeypatch):
        from scripts import e2e_local as runner

        host = MagicMock()
        stop = MagicMock()
        monkeypatch.setattr(runner, "start_func_host", lambda **kwargs: host)
        monkeypatch.setattr(runner, "stop_func_host", stop)
        monkeypatch.setattr(runner, "wait_for_func_host", lambda **kwargs: None)
        run_case = MagicMock(
            side_effect=[
                {"status": "Failed", "instanceId": "failed"},
                {"status": "Succeeded", "instanceId": "ok-1"},
                {"status": "Succeeded", "instanceId": "ok-2"},
            ]
        )
        monkeypatch.setattr(runner, "_run_single_case", run_case)
        summary = run_scenario("representative", dry_run_matrix=False, timeout=17, interval=0.1)
        assert summary["totals"] == {"succeeded": 2, "failed": 1, "dryRun": 0}
        assert run_case.call_count == 3
        assert run_case.call_args.kwargs == {"timeout": 17, "interval": 0.1}
        stop.assert_called_once_with(host)

    def test_dry_run_never_starts_host(self, monkeypatch):
        from scripts import e2e_local as runner

        host = MagicMock(side_effect=AssertionError("dry run started host"))
        monkeypatch.setattr(runner, "start_func_host", host)
        run_scenario("representative", dry_run_matrix=True)
        host.assert_not_called()

    def test_failed_case_retains_orchestration_evidence(self, monkeypatch):
        from scripts import e2e_local as runner

        monkeypatch.setattr(runner, "upload_kml", lambda *_: ("sample.kml", "url", 1))
        monkeypatch.setattr(runner, "fire_event_grid", lambda *args, **kwargs: "failed-instance")
        monkeypatch.setattr(
            runner,
            "poll_orchestration",
            lambda *args, **kwargs: {"runtimeStatus": "Failed", "output": {"message": "failure"}},
        )
        result = runner._run_single_case(build_representative_case_matrix()[0], timeout=1)
        assert result["status"] == "Failed"
        assert result["instanceId"] == "failed-instance"
        assert result["runtimeStatus"] == "Failed"

    def test_representative_case_matrix_uses_stable_case_ids(self):
        matrix = build_representative_case_matrix()
        assert [case["caseId"] for case in matrix] == [
            "rep-001-single-upload",
            "rep-002-repeat-upload",
            "rep-003-alt-container",
        ]

    def test_run_scenario_dry_run_tracks_each_case_and_totals(self):
        summary = run_scenario("representative", dry_run_matrix=True)
        assert summary["scenario"] == "representative"
        assert summary["totalCases"] == 3
        assert summary["cases"] == [
            {
                "caseId": "rep-001-single-upload",
                "container": DEFAULT_CONTAINER,
                "inputPath": str(REPO_ROOT / "tests" / "fixtures" / "sample.kml"),
                "status": "DryRun",
                "instanceId": None,
                "runtimeStatus": None,
                "error": None,
            },
            {
                "caseId": "rep-002-repeat-upload",
                "container": DEFAULT_CONTAINER,
                "inputPath": str(REPO_ROOT / "tests" / "fixtures" / "sample.kml"),
                "status": "DryRun",
                "instanceId": None,
                "runtimeStatus": None,
                "error": None,
            },
            {
                "caseId": "rep-003-alt-container",
                "container": f"rep-alt-{DEFAULT_CONTAINER}",
                "inputPath": str(REPO_ROOT / "tests" / "fixtures" / "sample.kml"),
                "status": "DryRun",
                "instanceId": None,
                "runtimeStatus": None,
                "error": None,
            },
        ]
        assert summary["totals"] == {"succeeded": 0, "failed": 0, "dryRun": 3}

    def test_run_scenario_raises_for_unknown_scenario(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            run_scenario("unknown-scenario", dry_run_matrix=True)


class TestWriteE2eResult:
    def test_writes_validated_run_summary(self, tmp_path: Path):
        result_path = tmp_path / "result.json"

        write_e2e_result(
            {
                "runtimeStatus": "Completed",
                "instanceId": "instance-1",
                "output": {"downloadsCompleted": 1},
            },
            result_path,
        )

        assert '"fixture": "tests/fixtures/sample.kml"' in result_path.read_text()
        assert '"instanceId": "instance-1"' in result_path.read_text()
        assert '"runtimeStatus": "Completed"' in result_path.read_text()

    def test_overwrites_previous_result(self, tmp_path: Path):
        result_path = tmp_path / "result.json"
        result_path.write_text("old")

        write_e2e_result({"runtimeStatus": "Completed", "output": {}}, result_path)

        assert result_path.read_text().startswith("{")
