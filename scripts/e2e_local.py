"""Unattended local/CI pipeline e2e gate (#1215).

Runs the real pipeline — blob upload -> Event Grid trigger -> Durable
orchestration -> acquisition -> fulfilment -> enrichment -> artifact —
against Azurite and a real ``func start`` host process, with
``CANOPEX_TEST_MODE=1`` so imagery never reaches a real third-party
provider (see ``treesight/providers/stub.py``). No live Azure environment
required.

Prerequisite: Azurite must already be up and reachable (the canonical
entrypoint is ``make test-pipeline-local``; direct callers can use
``make dev-up`` or a sibling ``azurite`` service in CI). This script manages
the func host lifecycle and trigger/poll/assert flow.

Usage:
  make test-pipeline-local
  # or directly:
  uv run python scripts/e2e_local.py
  uv run python scripts/e2e_local.py --scenario representative
  uv run python scripts/e2e_local.py --scenario representative --dry-run-matrix
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from _azurite import AZURITE_CONN_STR
from simulate_upload import DEFAULT_CONTAINER, fire_event_grid, upload_kml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from treesight.constants import (  # noqa: E402 - support direct execution without an editable install
    E2E_PROGRESS_INTERVAL_SECONDS,
)

FUNC_BASE = "http://localhost:7071"
DEFAULT_KML = REPO_ROOT / "tests" / "fixtures" / "sample.kml"
FUNC_HOST_LOG_PATH = REPO_ROOT / ".e2e-local-func-host.log"
E2E_RESULT_PATH = REPO_ROOT / ".e2e-local-result.json"

_TERMINAL_STATUSES = frozenset({"Completed", "Failed", "Canceled", "Terminated"})
_REPRESENTATIVE_SCENARIO = "representative"
_DEFAULT_SCENARIO = "single"
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_ORCH_TIMEOUT_SECONDS = 600.0

# Dummy CIAM values so treesight.config.validate_config() doesn't fail
# function indexing — REQUIRE_AUTH stays unset, so nothing ever verifies
# these against a real token. Never overrides a real value the caller
# already set (e.g. a developer's own local.settings.json/env).
_DUMMY_CIAM_DEFAULTS = {
    "CIAM_AUTHORITY": "https://ciam.example.com",
    "CIAM_TENANT_ID": "test-tenant",
    "CIAM_API_AUDIENCE": "api://test-audience",
}


def build_func_host_env(base_env: dict[str, str], *, test_mode: bool = True) -> dict[str, str]:
    """Return the environment for the ``func start`` subprocess.

    Self-contained by design: ``local.settings.json`` is git-ignored, so a
    fresh CI checkout won't have one — every setting the host needs to pass
    startup validation and reach the right Azurite must be set here, not
    assumed to come from a developer's local file.

    ``test_mode=False`` (used by ``scripts/real_acquisition_runner.py``,
    #1379) exercises the real imagery provider instead of the synthetic
    stub — any inherited ``CANOPEX_TEST_MODE`` from a developer's shell is
    stripped rather than left to leak into a real-acquisition run.
    """
    env = dict(base_env)
    if test_mode:
        env["CANOPEX_TEST_MODE"] = "1"
    else:
        env.pop("CANOPEX_TEST_MODE", None)
        # Real imagery, but the caller (e.g. real_acquisition_runner.py) still
        # needs to authenticate its own export-fetch requests without a real
        # CIAM bearer token — decoupled from CANOPEX_TEST_MODE so it doesn't
        # also switch imagery back to the synthetic stub (#1379).
        env["CANOPEX_ALLOW_TEST_PRINCIPAL"] = "1"
    # Dockerfile.base sets this for the *production* container convention
    # (/home/site/wwwroot). func start trusts it over the actual working
    # directory, so in any image that inherits it, func silently looks for
    # function_app.py in the wrong place. Always pin it to the real repo
    # root for this gate — never a setdefault, this ambient value is never
    # correct here.
    env["AzureWebJobsScriptRoot"] = str(REPO_ROOT)
    for key, value in _DUMMY_CIAM_DEFAULTS.items():
        env.setdefault(key, value)
    env["AzureWebJobsStorage"] = AZURITE_CONN_STR
    env.setdefault("FUNCTIONS_WORKER_RUNTIME", "python")
    env.setdefault("AzureWebJobsFeatureFlags", "EnableWorkerIndexing")
    # The Functions HOST (not the Python worker) manages its host-key
    # "secrets" via a separate blob-storage-backed repository by default,
    # which resolves the well-known devstoreaccount1 name straight to
    # 127.0.0.1 regardless of what AzureWebJobsStorage's actual endpoints
    # say — breaking whenever Azurite isn't reachable at localhost (e.g. a
    # sibling container reached by service name/host.docker.internal).
    # Filesystem-backed secrets need no storage account at all and are
    # fine for this throwaway local/CI host.
    env.setdefault("AzureWebJobsSecretStorageType", "files")
    return env


def start_func_host(*, log_path: Path, test_mode: bool = True) -> subprocess.Popen:
    """Start ``func start --python`` in the background with an env built
    by ``build_func_host_env`` — see that function for why."""
    env = build_func_host_env(dict(os.environ), test_mode=test_mode)
    log_file = log_path.open("w")
    try:
        return subprocess.Popen(
            ["func", "start", "--python"],
            cwd=REPO_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    finally:
        # The child keeps its own copy of the FD; avoid leaking it in the parent.
        log_file.close()


def stop_func_host(proc: subprocess.Popen, *, grace_seconds: float = 10.0) -> None:
    """Terminate the func host, escalating to SIGKILL if it won't stop."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5.0)


def write_e2e_result(status_payload: dict[str, Any], path: Path = E2E_RESULT_PATH) -> None:
    """Persist the validated run summary as durable proof of a local pass."""
    result = {
        "fixture": str(DEFAULT_KML.relative_to(REPO_ROOT)),
        "runtimeStatus": status_payload.get("runtimeStatus"),
        "instanceId": status_payload.get("instanceId"),
        "output": status_payload.get("output") or {},
    }
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def wait_for_func_host(*, timeout: float, interval: float = 2.0) -> None:
    """Block until the func host answers /api/health, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            resp = httpx.get(f"{FUNC_BASE}/api/health", timeout=5.0)
            if resp.status_code == 200:
                return
        except httpx.TransportError as exc:
            print(f"  ... health check transport error on attempt {attempt}: {exc}", flush=True)
        print(f"  ... waiting for func host (attempt {attempt})", flush=True)
        time.sleep(interval)
    raise TimeoutError(f"func host did not become ready within {timeout}s")


def poll_orchestration(
    instance_id: str,
    *,
    timeout: float,
    interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    base: str = FUNC_BASE,
) -> dict[str, Any]:
    """Poll the orchestrator status endpoint to a terminal state.

    *base* defaults to this module's own func host (FUNC_BASE) — callers
    polling a different host (e.g. scripts/verify_local_stack.py checking
    the orchestrator role too) must pass it explicitly, or every poll
    silently targets compute regardless of which host actually started
    the run.

    Returns the final status payload. Raises TimeoutError if no terminal
    state is reached within *timeout* — never loops unbounded.
    """
    url = f"{base}/api/orchestrator/{instance_id}"
    started_at = time.monotonic()
    deadline = started_at + timeout
    last_reported_at = started_at
    last_status = ""
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now - last_reported_at >= E2E_PROGRESS_INTERVAL_SECONDS:
            print(
                f"  [{instance_id}] status={last_status or 'Awaiting status'} "
                f"elapsed={now - started_at:.0f}s timeout={timeout:.0f}s",
                flush=True,
            )
            last_reported_at = now
        try:
            resp = httpx.get(url, timeout=10.0)
        except httpx.TransportError:
            time.sleep(interval)
            continue
        if resp.status_code == 404:
            time.sleep(interval)
            continue
        data = resp.json()
        last_payload = data
        status = data.get("runtimeStatus", "Unknown")
        if status != last_status:
            now = time.monotonic()
            print(
                f"  [{instance_id}] status={status} elapsed={now - started_at:.0f}s timeout={timeout:.0f}s",
                flush=True,
            )
            last_reported_at = now
            last_status = status
        if status in _TERMINAL_STATUSES:
            return data
        time.sleep(interval)
    custom = (last_payload or {}).get("customStatus")
    raise TimeoutError(
        "Orchestration "
        f"{instance_id} did not reach a terminal state within {timeout}s "
        f"(last_status={last_status or 'unknown'}, custom_status={custom!r})"
    )


def assert_pipeline_succeeded(status_payload: dict[str, Any]) -> None:
    """Raise ``AssertionError`` with full diagnostics unless the run
    produced real, successful output — not just an empty summary.
    """
    status = status_payload.get("runtimeStatus")
    if status != "Completed":
        raise AssertionError(f"Orchestration ended in {status!r}, expected 'Completed'. Payload: {status_payload}")

    output = status_payload.get("output") or {}
    downloads_completed = output.get("downloadsCompleted", 0)
    if downloads_completed < 1:
        raise AssertionError(f"Expected at least 1 completed download, got {downloads_completed}. Summary: {output}")

    raw_imagery_paths = (output.get("artifacts") or {}).get("rawImageryPaths") or []
    if not raw_imagery_paths:
        raise AssertionError(f"No rawImageryPaths in artifacts. Summary: {output}")


def build_representative_case_matrix() -> list[dict[str, str]]:
    """Return the deterministic representative case matrix."""
    sample_path = str(DEFAULT_KML)
    return [
        {"caseId": "rep-001-single-upload", "inputPath": sample_path, "container": DEFAULT_CONTAINER},
        {"caseId": "rep-002-repeat-upload", "inputPath": sample_path, "container": DEFAULT_CONTAINER},
        {"caseId": "rep-003-alt-container", "inputPath": sample_path, "container": f"rep-alt-{DEFAULT_CONTAINER}"},
    ]


def _build_case_matrix(scenario: str) -> list[dict[str, str]]:
    if scenario == _DEFAULT_SCENARIO:
        return [{"caseId": "single-001-default-upload", "inputPath": str(DEFAULT_KML), "container": DEFAULT_CONTAINER}]
    if scenario == _REPRESENTATIVE_SCENARIO:
        return build_representative_case_matrix()
    raise ValueError(f"Unknown scenario {scenario!r}. Expected one of: {_DEFAULT_SCENARIO}, {_REPRESENTATIVE_SCENARIO}")


def _run_single_case(
    case: dict[str, str], *, timeout: float, interval: float = DEFAULT_POLL_INTERVAL_SECONDS
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "caseId": case["caseId"],
        "container": case["container"],
        "inputPath": case["inputPath"],
        "status": "Failed",
        "instanceId": None,
        "runtimeStatus": None,
        "error": None,
    }
    try:
        blob_name, blob_url, content_length = upload_kml(Path(case["inputPath"]), case["container"])
        result["instanceId"] = fire_event_grid(blob_url, blob_name, content_length, case["container"], strict=True)
        payload = poll_orchestration(result["instanceId"], timeout=timeout, interval=interval)
        result["runtimeStatus"] = payload.get("runtimeStatus")
        result["output"] = payload.get("output") or {}
        assert_pipeline_succeeded(payload)
        result["status"] = "Succeeded"
    except Exception as exc:
        result["error"] = str(exc)
    return result


def run_scenario(
    scenario: str,
    *,
    dry_run_matrix: bool,
    timeout: float = DEFAULT_ORCH_TIMEOUT_SECONDS,
    interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Run one scenario and return a structured summary."""
    cases = _build_case_matrix(scenario)
    results: list[dict[str, Any]] = []
    totals = {"succeeded": 0, "failed": 0, "dryRun": 0}

    if dry_run_matrix:
        for case in cases:
            results.append(
                {
                    "caseId": case["caseId"],
                    "container": case["container"],
                    "inputPath": case["inputPath"],
                    "status": "DryRun",
                    "instanceId": None,
                    "runtimeStatus": None,
                    "error": None,
                }
            )
        totals["dryRun"] = len(results)
        return {"scenario": scenario, "totalCases": len(cases), "cases": results, "totals": totals}

    proc = start_func_host(log_path=FUNC_HOST_LOG_PATH)
    try:
        print("[1/2] Waiting for func host to become ready...", flush=True)
        wait_for_func_host(timeout=120.0)
        print("[2/2] Executing scenario matrix...", flush=True)
        for index, case in enumerate(cases, start=1):
            print(f"  [{index}/{len(cases)}] Running case {case['caseId']} ({case['container']})", flush=True)
            result = _run_single_case(case, timeout=timeout, interval=interval)
            if result["status"] == "Succeeded":
                totals["succeeded"] += 1
            else:
                totals["failed"] += 1
            results.append(result)
            print(
                f"  [{index}/{len(cases)}] {case['caseId']}: {result['status']} "
                f"(passed={totals['succeeded']} failed={totals['failed']} remaining={len(cases) - index})",
                flush=True,
            )
        return {"scenario": scenario, "totalCases": len(cases), "cases": results, "totals": totals}
    except Exception:
        print(f"\nHost execution failed; see {FUNC_HOST_LOG_PATH}", file=sys.stderr)
        raise
    finally:
        stop_func_host(proc)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local pipeline e2e scenarios")
    parser.add_argument(
        "--scenario",
        default=_DEFAULT_SCENARIO,
        choices=[_DEFAULT_SCENARIO, _REPRESENTATIVE_SCENARIO],
        help=f"Scenario to execute (default: {_DEFAULT_SCENARIO})",
    )
    parser.add_argument(
        "--dry-run-matrix",
        action="store_true",
        help="Print deterministic case matrix and summary without starting func host or uploads",
    )
    parser.add_argument(
        "--orchestration-timeout-seconds",
        type=float,
        default=float(os.getenv("E2E_LOCAL_ORCHESTRATION_TIMEOUT_SECONDS", DEFAULT_ORCH_TIMEOUT_SECONDS)),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=float(os.getenv("E2E_LOCAL_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    # Avoid proxy env vars breaking localhost httpx calls in CI/dev shells.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY"):
        os.environ.pop(var, None)
        os.environ.pop(var.lower(), None)

    if not args.dry_run_matrix:
        E2E_RESULT_PATH.unlink(missing_ok=True)
    try:
        summary = run_scenario(
            args.scenario,
            dry_run_matrix=args.dry_run_matrix,
            timeout=args.orchestration_timeout_seconds,
            interval=args.poll_interval_seconds,
        )
        print("\nScenario summary:")
        print(json.dumps(summary, indent=2))
        if not args.dry_run_matrix:
            if args.scenario == _DEFAULT_SCENARIO and not summary["totals"]["failed"]:
                write_e2e_result(summary["cases"][0])
            else:
                E2E_RESULT_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        if summary["totals"]["failed"] > 0:
            raise AssertionError(f"Scenario {args.scenario!r} had {summary['totals']['failed']} failing case(s).")
        if not args.dry_run_matrix:
            print("\nPASS — local pipeline e2e gate succeeded.")
    except Exception:
        print("\nFAIL — local scenario did not complete.", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
