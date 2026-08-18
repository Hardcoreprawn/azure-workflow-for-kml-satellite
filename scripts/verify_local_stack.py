"""Full local verification gate — every surface and integration point, one command.

Prerequisite: `make dev-all` running (azurite, cosmos, func, orch, web,
event-grid-relay, ollama).

Checks, in order:
1. Service health   — every compose service is up and its own healthcheck passes.
2. Blueprint parity — compute and orchestrator serve the identical HTTP
   surface (#1407/#1408) — delegates to validate_blueprint_parity.py.
3. Storage (Azurite) — blob container list/create round-trip.
4. Cosmos            — billing/status (Cosmos-backed) responds on both hosts.
5. Full pipeline     — upload -> blob trigger -> orchestration -> Completed,
   run against BOTH compute and orchestrator (the same fixture, twice),
   proving blob_trigger genuinely works on either host post-#1407.
6. Exports           — eudr-pdf/eudr-geojson/eudr-csv non-empty for the
   completed run.
7. Website           — static site serves and its /api/* proxy reaches func.
8. Event Grid relay  — the dev_event_grid_relay.py container is running
   (liveness only; the pipeline check above exercises the same code path
   deterministically rather than depending on the relay's own poll timing).
9. Ollama            — best-effort; failure here is a WARNING, not a FAILURE,
   since a GPU/pulled model is not required for the rest of the app to work.

KNOWN FLAKY CHECK — pipeline (#1414): compute and orchestrator share one
Durable Task Hub, and both register the orchestrator-trigger function.
Whichever app's worker wins a given instance's partition lease runs its
replay — if that's the orchestrator (which has no activities registered,
by design), the run can hang forever at "parsing_kml" with zero errors.
This is a real, pre-existing production reliability bug (see #1414), not
a flake in this script — a failure here may mean you hit it. Re-running
usually succeeds (it's a race, not a hard failure), but each occurrence
is worth a comment on #1414 with the stuck instance ID and which host's
logs show the stall, until it's fixed.

Usage:
    make dev-all
    uv run python scripts/verify_local_stack.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
from _azurite import AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient
from dev_event_grid_relay import _extract_eventgrid_key
from e2e_local import assert_pipeline_succeeded, poll_orchestration
from simulate_upload import DEFAULT_CONTAINER, fire_event_grid, upload_kml
from validate_blueprint_parity import ROUTES, check_host

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KML = REPO_ROOT / "tests" / "fixtures" / "sample.kml"

# Overridable via env var for non-default setups (e.g. running this script
# itself from inside a container on the compose network) — same pattern as
# scripts/_azurite.py's AZURITE_BLOB_HOST.
COMPUTE_BASE = os.environ.get("VERIFY_COMPUTE_BASE", "http://localhost:7071")
ORCH_BASE = os.environ.get("VERIFY_ORCH_BASE", "http://localhost:7072")
WEB_BASE = os.environ.get("VERIFY_WEB_BASE", "http://localhost:4280")
OLLAMA_BASE = os.environ.get("VERIFY_OLLAMA_BASE", "http://localhost:11434")

# docker-compose's func/orch set IMAGERY_PROVIDER=planetary_computer with no
# CANOPEX_TEST_MODE -- this hits the REAL Planetary Computer STAC API and
# downloads real imagery, which is much slower and less predictable than the
# synthetic-stub gates (e2e_local.py, corpus_runner.py) use. Matches the
# generous timeout scripts/real_acquisition_runner.py already uses for the
# same reason.
PIPELINE_TIMEOUT_SECONDS = float(os.environ.get("VERIFY_PIPELINE_TIMEOUT_S", "600"))

_REQUIRED_CONTAINERS = ("canopex-azurite", "canopex-cosmos", "canopex-func", "canopex-orch", "canopex-web")
_LIVENESS_ONLY_CONTAINERS = ("canopex-event-grid-relay",)

EXPORT_FORMATS = ("eudr-pdf", "eudr-geojson", "eudr-csv")

# (name, passed) — printed as a final summary table; WARN entries never fail the gate.
Result = tuple[str, bool]


def _print_result(name: str, ok: bool, *, warn_only: bool = False) -> None:
    if ok:
        print(f"  PASS  {name}")
    elif warn_only:
        print(f"  WARN  {name}")
    else:
        print(f"  FAIL  {name}")


def check_container_running(name: str) -> bool:
    """True if *name* is Up (docker's own healthcheck, if any, is not required here —
    callers that need a passed healthcheck use an HTTP probe instead)."""
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "running"


def check_service_health() -> list[Result]:
    print("\n[1/9] Service health")
    results: list[Result] = []
    for name in _REQUIRED_CONTAINERS:
        ok = check_container_running(name)
        _print_result(name, ok)
        results.append((f"container:{name}", ok))
    for name in _LIVENESS_ONLY_CONTAINERS:
        ok = check_container_running(name)
        _print_result(f"{name} (liveness only)", ok, warn_only=True)
        results.append((f"container:{name}", True))  # never blocks the gate
    return results


def check_parity() -> list[Result]:
    print("\n[2/9] Blueprint parity (compute vs orchestrator, #1407)")
    with httpx.Client() as client:
        compute_results = check_host(client, COMPUTE_BASE, ROUTES)
        orch_results = check_host(client, ORCH_BASE, ROUTES)
    results: list[Result] = []
    for route in ROUTES:
        bp = route.blueprint
        ok = compute_results.get(bp, False) and orch_results.get(bp, False)
        _print_result(bp, ok)
        results.append((f"parity:{bp}", ok))
    return results


def check_storage() -> list[Result]:
    print("\n[3/9] Storage (Azurite)")
    try:
        client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
        container = client.get_container_client(DEFAULT_CONTAINER)
        if not container.exists():
            container.create_container()
        list(container.list_blobs(results_per_page=1))
        ok = True
    except Exception as exc:  # report any storage failure, not just specific types
        print(f"  ... Azurite blob round-trip failed: {exc}")
        ok = False
    _print_result(f"blob round-trip ({DEFAULT_CONTAINER})", ok)
    return [("storage:blob", ok)]


def check_cosmos() -> list[Result]:
    print("\n[4/9] Cosmos (via billing/status)")
    results: list[Result] = []
    with httpx.Client() as client:
        for label, base in (("compute", COMPUTE_BASE), ("orchestrator", ORCH_BASE)):
            try:
                resp = client.get(f"{base}/api/billing/status", timeout=10.0)
                ok = resp.status_code == 200 and "tier" in resp.json()
            except (httpx.TransportError, ValueError) as exc:
                print(f"  ... {label} billing/status failed: {exc}")
                ok = False
            _print_result(f"billing/status via {label}", ok)
            results.append((f"cosmos:{label}", ok))
    return results


def _all_eventgrid_keys() -> list[str]:
    """Return every Event Grid system key currently stored in Azurite.

    Each running host (func, orch) writes its own secrets blob, named by
    container hostname -- there is no reliable way to tell which blob
    belongs to which host from the blob name alone once more than one
    host shares the same Azurite secrets store (#1407 added the second
    host). Rather than guess, callers try every key in turn.
    """
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container = client.get_container_client("azure-webjobs-secrets")
    keys: list[str] = []
    try:
        blobs = list(container.list_blobs())
    except Exception:
        return keys
    for blob in blobs:
        try:
            text = container.get_blob_client(blob.name).download_blob().readall().decode()
        except Exception:
            continue
        key = _extract_eventgrid_key(text)
        if key:
            keys.append(key)
    return keys


def _run_pipeline(host_label: str, base: str) -> tuple[bool, str | None]:
    """Upload the sample fixture through *base* and poll to a terminal state.

    Returns (succeeded, instance_id) — instance_id is None if the upload/fire
    step itself failed before an orchestration could even start.
    """
    try:
        blob_name, blob_url, content_length = upload_kml(DEFAULT_KML, DEFAULT_CONTAINER)
    except Exception as exc:  # any failure here is a real gate failure
        print(f"  ... {host_label} upload failed: {exc}")
        return False, None

    instance_id: str | None = None
    last_error: Exception | None = None
    # No key first (works when host-key auth is disabled), then every known
    # key in turn (see _all_eventgrid_keys for why there's more than one).
    for function_key in (None, *_all_eventgrid_keys()):
        try:
            instance_id = fire_event_grid(
                blob_url, blob_name, content_length, DEFAULT_CONTAINER, func_base=base, function_key=function_key
            )
            last_error = None
            break
        except RuntimeError as exc:
            last_error = exc
            continue

    if last_error is not None or instance_id is None:
        print(f"  ... {host_label} upload/fire failed: {last_error}")
        return False, None

    try:
        status_payload = poll_orchestration(instance_id, timeout=PIPELINE_TIMEOUT_SECONDS)
        assert_pipeline_succeeded(status_payload)
        return True, instance_id
    except (TimeoutError, AssertionError) as exc:
        print(f"  ... {host_label} pipeline did not complete: {exc}")
        return False, instance_id


def check_pipeline() -> tuple[list[Result], str | None]:
    print("\n[5/9] Full pipeline (upload -> blob trigger -> orchestration -> Completed)")
    results: list[Result] = []
    last_instance_id: str | None = None
    for host_label, base in (("compute", COMPUTE_BASE), ("orchestrator", ORCH_BASE)):
        ok, instance_id = _run_pipeline(host_label, base)
        _print_result(f"pipeline via {host_label}", ok)
        results.append((f"pipeline:{host_label}", ok))
        if ok:
            last_instance_id = instance_id
    return results, last_instance_id


def check_exports(instance_id: str | None) -> list[Result]:
    print("\n[6/9] Exports")
    if not instance_id:
        print("  ... no completed pipeline run available, skipping")
        return [(f"export:{fmt}", False) for fmt in EXPORT_FORMATS]

    results: list[Result] = []
    with httpx.Client() as client:
        for fmt in EXPORT_FORMATS:
            try:
                resp = client.get(f"{ORCH_BASE}/api/export/{instance_id}/{fmt}", timeout=30.0)
                ok = resp.status_code == 200 and len(resp.content) > 0
            except httpx.TransportError as exc:
                print(f"  ... export {fmt!r} failed: {exc}")
                ok = False
            _print_result(fmt, ok)
            results.append((f"export:{fmt}", ok))
    return results


def check_website() -> list[Result]:
    print("\n[7/9] Website")
    results: list[Result] = []
    try:
        with httpx.Client() as client:
            resp = client.get(WEB_BASE, timeout=10.0)
            site_ok = resp.status_code == 200 and "Canopex" in resp.text
            proxy_resp = client.get(f"{WEB_BASE}/api/health", timeout=10.0)
            proxy_ok = proxy_resp.status_code == 200
    except httpx.TransportError as exc:
        print(f"  ... website check failed: {exc}")
        site_ok = proxy_ok = False
    _print_result("static site serves", site_ok)
    _print_result("/api/* proxy reaches func", proxy_ok)
    results.append(("website:static", site_ok))
    results.append(("website:proxy", proxy_ok))
    return results


def check_event_grid_relay() -> list[Result]:
    print("\n[8/9] Event Grid relay (liveness only — see module docstring)")
    ok = check_container_running("canopex-event-grid-relay")
    _print_result("canopex-event-grid-relay running", ok, warn_only=True)
    return [("event-grid-relay", True)]  # never blocks the gate


def check_ollama() -> list[Result]:
    print("\n[9/9] Ollama (best-effort)")
    try:
        with httpx.Client() as client:
            resp = client.get(f"{OLLAMA_BASE}/api/tags", timeout=5.0)
            ok = resp.status_code == 200
    except httpx.TransportError:
        ok = False
    _print_result("ollama reachable", ok, warn_only=True)
    return [("ollama", True)]  # never blocks the gate; AI narrative is best-effort locally


def summarize(results: list[Result]) -> tuple[list[str], bool]:
    """Return (failed_check_names, passed) for the collected results."""
    failed = [name for name, ok in results if not ok]
    return failed, not failed


def main() -> int:
    all_results: list[Result] = []
    all_results += check_service_health()
    all_results += check_parity()
    all_results += check_storage()
    all_results += check_cosmos()
    pipeline_results, instance_id = check_pipeline()
    all_results += pipeline_results
    all_results += check_exports(instance_id)
    all_results += check_website()
    all_results += check_event_grid_relay()
    all_results += check_ollama()

    failed, passed = summarize(all_results)

    print("\n" + "=" * 60)
    if not passed:
        print(f"FAIL — {len(failed)} check(s) failed:")
        for name in failed:
            print(f"  - {name}")
        return 1

    print(f"PASS — all {len(all_results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
