"""Unattended local/CI pipeline e2e gate (#1215).

Runs the real pipeline — blob upload -> Event Grid trigger -> Durable
orchestration -> acquisition -> fulfilment -> enrichment -> artifact —
against Azurite and a real ``func start`` host process, with
``CANOPEX_TEST_MODE=1`` so imagery never reaches a real third-party
provider (see ``treesight/providers/stub.py``). No live Azure environment
required.

Prerequisite: Azurite must already be up with containers created
(``make dev-init``) — this script only manages the func host lifecycle
and the trigger/poll/assert flow.

Usage:
  make test-e2e-local
  # or directly:
  uv run python scripts/e2e_local.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from simulate_upload import DEFAULT_CONTAINER, fire_event_grid, upload_kml

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNC_BASE = "http://localhost:7071"
DEFAULT_KML = REPO_ROOT / "tests" / "fixtures" / "sample.kml"
FUNC_HOST_LOG_PATH = REPO_ROOT / ".e2e-local-func-host.log"

_TERMINAL_STATUSES = frozenset({"Completed", "Failed", "Canceled", "Terminated"})


def start_func_host(*, log_path: Path) -> subprocess.Popen:
    """Start ``func start --python`` in the background with
    ``CANOPEX_TEST_MODE`` set — the switch that keeps imagery synthetic
    (see #1215 / treesight/config.py::is_test_mode_enabled)."""
    env = dict(os.environ)
    env["CANOPEX_TEST_MODE"] = "1"
    log_file = log_path.open("w")
    return subprocess.Popen(
        ["func", "start", "--python"],
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


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
        except httpx.TransportError:
            pass
        print(f"  ... waiting for func host (attempt {attempt})")
        time.sleep(interval)
    raise TimeoutError(f"func host did not become ready within {timeout}s")


def poll_orchestration(
    instance_id: str, *, timeout: float, interval: float = 3.0
) -> dict[str, Any]:
    """Poll the orchestrator status endpoint to a terminal state.

    Returns the final status payload. Raises TimeoutError if no terminal
    state is reached within *timeout* — never loops unbounded.
    """
    url = f"{FUNC_BASE}/api/orchestrator/{instance_id}"
    deadline = time.monotonic() + timeout
    last_status = ""
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=10.0)
        except httpx.TransportError:
            time.sleep(interval)
            continue
        if resp.status_code == 404:
            time.sleep(interval)
            continue
        data = resp.json()
        status = data.get("runtimeStatus", "Unknown")
        if status != last_status:
            print(f"  status: {status}")
            last_status = status
        if status in _TERMINAL_STATUSES:
            return data
        time.sleep(interval)
    raise TimeoutError(
        f"Orchestration {instance_id} did not reach a terminal state within {timeout}s"
    )


def assert_pipeline_succeeded(status_payload: dict[str, Any]) -> None:
    """Raise ``AssertionError`` with full diagnostics unless the run
    produced real, successful output — not just an empty summary.
    """
    status = status_payload.get("runtimeStatus")
    if status != "Completed":
        raise AssertionError(
            f"Orchestration ended in {status!r}, expected 'Completed'. Payload: {status_payload}"
        )

    output = status_payload.get("output") or {}
    downloads_succeeded = output.get("downloads_succeeded", 0)
    if downloads_succeeded < 1:
        raise AssertionError(
            f"Expected at least 1 successful download, got {downloads_succeeded}. Summary: {output}"
        )

    download_results = output.get("download_results") or []
    if not any(r.get("blob_path") for r in download_results):
        raise AssertionError(f"No download_results with a blob_path. Summary: {output}")


def main() -> None:
    proc = start_func_host(log_path=FUNC_HOST_LOG_PATH)
    try:
        print("[1/4] Waiting for func host to become ready...")
        wait_for_func_host(timeout=120.0)

        print("[2/4] Uploading sample KML and triggering the pipeline...")
        blob_name, blob_url, content_length = upload_kml(DEFAULT_KML, DEFAULT_CONTAINER)
        instance_id = fire_event_grid(blob_url, blob_name, content_length, DEFAULT_CONTAINER)

        print("[3/4] Polling orchestration to a terminal state...")
        result = poll_orchestration(instance_id, timeout=300.0)

        print("[4/4] Verifying the run actually produced output...")
        assert_pipeline_succeeded(result)

        print("\nPASS — local pipeline e2e gate succeeded.")
    except Exception:
        print(f"\nFAIL — see func host log at {FUNC_HOST_LOG_PATH}", file=sys.stderr)
        raise
    finally:
        stop_func_host(proc)


if __name__ == "__main__":
    main()
