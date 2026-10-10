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
6. Website           — static site serves and its /api/* proxy reaches func.
7. Event Grid relay  — the dev_event_grid_relay.py container is running
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
    VERIFY_BEARER_TOKEN=... VERIFY_WRONG_USER_BEARER_TOKEN=... \\
        VERIFY_WRONG_ORG_BEARER_TOKEN=... uv run python scripts/verify_local_stack.py --api-only

The API-only journey accepts only bearer tokens verified by the local API's
configured CIAM issuer. It proves the local runtime and selected provider path;
it does not prove deployed CIAM configuration, cloud identity, or production
provider behavior. Keep token values in the environment, never in command args.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from _azurite import AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient
from dev_event_grid_relay import _extract_eventgrid_key
from e2e_local import assert_pipeline_succeeded, poll_orchestration
from e2e_smoke_gate import (
    bearer_headers as _bearer_headers,
)
from e2e_smoke_gate import (
    collect_artifact_paths as _collect_artifact_paths,
)
from e2e_smoke_gate import (
    mint_upload_token,
    poll_orchestrator,
    verify_completed_output_shape,
)
from e2e_smoke_gate import (
    upload_kml as _upload_api_kml,
)
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

_REQUIRED_CONTAINERS = ("azurite", "cosmos", "func", "orch", "web")
_LIVENESS_ONLY_CONTAINERS = ("event-grid-relay",)

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
    """True if *name* is Up and, when it defines a Docker HEALTHCHECK,
    reports healthy — a merely "running" container can still be mid-startup
    or explicitly unhealthy, which a bare Status check would miss."""
    try:
        selection = subprocess.run(
            [
                "docker",
                "ps",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={os.environ.get('COMPOSE_PROJECT_NAME', 'canopex-dev')}",
                "--filter",
                f"label=com.docker.compose.service={name}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        containers = selection.stdout.split()
        if selection.returncode != 0 or len(containers) != 1:
            return False
        out = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                containers[0],
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    if out.returncode != 0:
        return False
    status, _, health = out.stdout.strip().partition("|")
    # No HEALTHCHECK defined (health == "") -> running is all we can check.
    return status == "running" and health in ("", "healthy")


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
    # Mirrors dev_event_grid_relay.py's own container name (that constant is
    # private/underscored there, so duplicated here rather than imported).
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container = client.get_container_client("azure-webjobs-secrets")
    keys: list[str] = []
    try:
        blobs = list(container.list_blobs())
    except Exception as exc:
        print(f"  ... could not list Event Grid secrets container: {exc}")
        return keys
    for blob in blobs:
        try:
            text = container.get_blob_client(blob.name).download_blob().readall().decode()
        except Exception as exc:
            print(f"  ... could not read secrets blob {blob.name!r}: {exc}")
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
        status_payload = poll_orchestration(instance_id, timeout=PIPELINE_TIMEOUT_SECONDS, base=base)
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


def check_exports(
    instance_id: str | None,
    *,
    token: str | None = None,
    api_base: str = ORCH_BASE,
) -> list[Result]:
    print("\n[6/9] EUDR artifact downloads")
    if not instance_id:
        for fmt in EXPORT_FORMATS:
            _print_result(f"{fmt} (missing owned run)", False)
        return [(f"export:{fmt}", False) for fmt in EXPORT_FORMATS]

    if not token or not token.strip():
        print("  ... authenticated export check requires VERIFY_BEARER_TOKEN")
        for fmt in EXPORT_FORMATS:
            _print_result(f"{fmt} (missing bearer token)", False)
        return [(f"export:{fmt}", False) for fmt in EXPORT_FORMATS]

    results: list[Result] = []
    with httpx.Client(trust_env=False) as client:
        for fmt in EXPORT_FORMATS:
            try:
                resp = client.get(
                    f"{api_base.rstrip('/')}/api/export/{instance_id}/{fmt}",
                    headers=_bearer_headers(token),
                    timeout=30.0,
                )
                ok = _valid_export_response(fmt, instance_id, resp)
            except httpx.TransportError as exc:
                print(f"  ... export {fmt!r} failed: {exc}")
                ok = False
            _print_result(fmt, ok)
            results.append((f"export:{fmt}", ok))
    return results


def _valid_export_response(fmt: str, instance_id: str, response: httpx.Response) -> bool:
    if response.status_code != 200 or instance_id not in response.headers.get("content-disposition", ""):
        return False

    content_type = response.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if fmt == "eudr-pdf":
        return content_type == "application/pdf" and response.content.startswith(b"%PDF-")
    if fmt == "eudr-csv":
        if content_type != "text/csv":
            return False
        try:
            rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        except (UnicodeDecodeError, csv.Error):
            return False
        return len(rows) > 1 and bool(rows[0]) and any(any(cell.strip() for cell in row) for row in rows[1:])
    if fmt == "eudr-geojson":
        if content_type != "application/geo+json":
            return False
        try:
            payload = json.loads(response.content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        features = payload.get("features") if isinstance(payload, dict) else None
        return (
            isinstance(payload, dict)
            and payload.get("type") == "FeatureCollection"
            and isinstance(features, list)
            and bool(features)
            and all(
                isinstance(feature, dict)
                and feature.get("type") == "Feature"
                and isinstance(feature.get("geometry"), dict)
                for feature in features
            )
        )
    return False


def _history_contains_run(payload: dict[str, object], instance_id: str) -> bool:
    runs = payload.get("runs")
    return isinstance(runs, list) and any(
        isinstance(run, dict) and run.get("instanceId") == instance_id and run.get("runtimeStatus") == "Completed"
        for run in runs
    )


def _get_history(client: httpx.Client, api_base: str, token: str) -> dict[str, object]:
    response = client.get(
        f"{api_base.rstrip('/')}/api/analysis/history?scope=user&limit=20",
        headers=_bearer_headers(token),
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("orgId"), str) or not payload["orgId"]:
        raise ValueError("Authenticated history response is missing its organisation identity")
    return payload


def _export_access_denied(
    client: httpx.Client,
    api_base: str,
    instance_id: str,
    token: str | None = None,
) -> int:
    headers = _bearer_headers(token) if token else {}
    response = client.get(
        f"{api_base.rstrip('/')}/api/export/{instance_id}/eudr-pdf",
        headers=headers,
        timeout=30.0,
    )
    return response.status_code


def check_api_only_journey() -> list[Result]:
    """Prove owned submission and evidence access through public API routes only.

    Tokens must be API access tokens accepted by the local API's configured
    CIAM verifier. This proves local behavior, not deployed CIAM configuration.
    """
    print("\n[6/9] Authenticated API-only journey (website-independent)")
    owner_token = os.environ.get("VERIFY_BEARER_TOKEN", "").strip()
    wrong_user_token = os.environ.get("VERIFY_WRONG_USER_BEARER_TOKEN", "").strip()
    wrong_org_token = os.environ.get("VERIFY_WRONG_ORG_BEARER_TOKEN", "").strip()
    missing = [
        name
        for name, value in (
            ("VERIFY_BEARER_TOKEN", owner_token),
            ("VERIFY_WRONG_USER_BEARER_TOKEN", wrong_user_token),
            ("VERIFY_WRONG_ORG_BEARER_TOKEN", wrong_org_token),
        )
        if not value
    ]
    if missing:
        print(f"  ... missing required identity inputs: {', '.join(missing)}")
        _print_result("owned API submission, access controls, and evidence", False)
        return [("api-only:journey", False)]

    api_base = ORCH_BASE.rstrip("/")
    results: list[Result] = []
    stage = "fixture validation"
    try:
        kml_bytes = DEFAULT_KML.read_bytes()
        if not kml_bytes:
            raise ValueError("KML fixture is empty")

        with httpx.Client(trust_env=False) as client:
            stage = "owner identity validation"
            owner_identity = _get_history(client, api_base, owner_token)
            results.append(("api-only:owner-identity", True))

            stage = "wrong-user identity validation"
            wrong_user_identity = _get_history(client, api_base, wrong_user_token)
            if wrong_user_identity["orgId"] == owner_identity["orgId"]:
                raise ValueError("VERIFY_WRONG_USER_BEARER_TOKEN belongs to the run's originating organisation")
            results.append(("api-only:wrong-user-identity", True))

            stage = "wrong-org identity validation"
            wrong_org_identity = _get_history(client, api_base, wrong_org_token)
            if wrong_org_identity["orgId"] == owner_identity["orgId"]:
                raise ValueError("VERIFY_WRONG_ORG_BEARER_TOKEN belongs to the run's originating organisation")
            results.append(("api-only:wrong-org-identity", True))

            stage = "API submission and authorized status"
            upload = mint_upload_token(
                client,
                api_base=api_base,
                token=owner_token,
                eudr_mode=True,
                submission_context={"provider_name": "planetary_computer", "source": "local_api_verifier"},
            )
            _upload_api_kml(client, sas_url=upload["sasUrl"], kml_bytes=kml_bytes)
            status_payload = poll_orchestrator(
                client,
                api_base=api_base,
                token=owner_token,
                instance_id=upload["submissionId"],
                max_attempts=max(1, int(PIPELINE_TIMEOUT_SECONDS / 5)),
                poll_interval_seconds=5,
            )
            output = verify_completed_output_shape(status_payload)
            if not _collect_artifact_paths(output):
                raise ValueError("Completed API run contains no artifact references")

            stage = "owner history verification"
            owner_history = _get_history(client, api_base, owner_token)
            if not _history_contains_run(owner_history, upload["submissionId"]):
                raise ValueError("Authenticated analysis history does not contain the completed submitted run")
            results.append(("api-only:submission-status-history", True))

            stage = "negative access controls"
            anonymous_status = _export_access_denied(client, api_base, upload["submissionId"])
            wrong_user_status = _export_access_denied(client, api_base, upload["submissionId"], wrong_user_token)
            wrong_org_status = _export_access_denied(client, api_base, upload["submissionId"], wrong_org_token)

        api_results = [
            ("api-only:anonymous-denied", anonymous_status == 401),
            ("api-only:wrong-user-denied", wrong_user_status in {403, 404}),
            ("api-only:wrong-org-denied", wrong_org_status in {403, 404}),
        ]
        _print_result("anonymous export denied (401)", api_results[0][1])
        _print_result("wrong-user export denied", api_results[1][1])
        _print_result("wrong-org export denied", api_results[2][1])
        results.extend(api_results)

        stage = "EUDR artifact downloads"
        results.extend(check_exports(upload["submissionId"], token=owner_token, api_base=api_base))
        results.append(("api-only:journey", all(ok for _, ok in results)))
        return results
    except Exception as exc:
        detail = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
        print(f"  ... authenticated API-only journey failed during {stage}: {detail}")
        _print_result(stage, False)
        results.append((f"api-only:{stage.replace(' ', '-')}", False))
        results.append(("api-only:journey", False))
        return results


def check_website() -> list[Result]:
    print("\n[7/9] Website")
    results: list[Result] = []
    with httpx.Client() as client:
        try:
            resp = client.get(WEB_BASE, timeout=10.0)
            site_ok = resp.status_code == 200 and "Canopex" in resp.text
        except httpx.TransportError as exc:
            print(f"  ... static site check failed: {exc}")
            site_ok = False
        try:
            proxy_resp = client.get(f"{WEB_BASE}/api/health", timeout=10.0)
            proxy_ok = proxy_resp.status_code == 200
        except httpx.TransportError as exc:
            print(f"  ... /api/* proxy check failed: {exc}")
            proxy_ok = False
    _print_result("static site serves", site_ok)
    _print_result("/api/* proxy reaches func", proxy_ok)
    results.append(("website:static", site_ok))
    results.append(("website:proxy", proxy_ok))
    return results


def check_event_grid_relay() -> list[Result]:
    print("\n[8/9] Event Grid relay (liveness only — see module docstring)")
    ok = check_container_running("event-grid-relay")
    _print_result("event-grid-relay running", ok, warn_only=True)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the local Canopex stack.")
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Run only the authenticated API journey; the website and other services are not checked.",
    )
    args = parser.parse_args(argv)

    all_results: list[Result] = []
    if args.api_only:
        all_results += check_api_only_journey()
    else:
        all_results += check_service_health()
        all_results += check_parity()
        all_results += check_storage()
        all_results += check_cosmos()
        pipeline_results, _ = check_pipeline()
        all_results += pipeline_results
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
