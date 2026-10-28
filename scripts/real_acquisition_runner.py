"""Real-acquisition local runner for EUDR proof-of-value scenarios (#1379).

Sibling to ``scripts/corpus_runner.py``, but exercises the REAL Planetary
Computer imagery provider (``CANOPEX_TEST_MODE`` unset) against real-world
EUDR commodity fixtures in ``tests/fixtures/eudr_scenarios/``, then downloads
the ``eudr-pdf``/``eudr-geojson``/``eudr-csv`` exports so a human can review
them for plausibility.

This is a manual, on-demand tool — deliberately NOT wired into CI. Real STAC
results are non-deterministic (cloud cover, scene availability vary run to
run), and issue #1379 requires a human-reviewed sign-off, not a CI gate.

Prerequisite
------------
Azurite and a disposable Cosmos emulator must already be running, with
``orgs``, ``users`` and ``runs`` containers from ``scripts/cosmos_init``.
Set ``COSMOS_ENDPOINT`` to HTTP localhost/loopback or the Docker alias
``cosmos``, ``COSMOS_KEY`` to the emulator key and ``COSMOS_DATABASE_NAME``
to its database. Never point this synthetic runner at live data.
This script manages its
own ``func start`` lifecycle, same as ``corpus_runner.py`` — you do **not**
need a separate running func host, and it must NOT be run against a
docker-compose ``func`` container already listening on the same port.

Usage
-----
    # Run every fixture in tests/fixtures/eudr_scenarios/:
    uv run python scripts/real_acquisition_runner.py

    # Run a specific scenario:
    uv run python scripts/real_acquisition_runner.py \\
        tests/fixtures/eudr_scenarios/cattle_para_brazil.kml

    # Only fetch specific export formats:
    uv run python scripts/real_acquisition_runner.py --formats eudr-pdf eudr-geojson

Exports are written to ``.real-acquisition-output/<fixture-stem>/<instance-id>/`` for
manual review. See issue #1379's acceptance checklist for what to look for
(NDVI/land-cover plausibility, EUDR post-2020 date framing, AI narrative
coherence) — none of that is checked automatically here.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import orjson
from corpus_runner import _upload_ticket
from e2e_local import (
    FUNC_BASE,
    REPO_ROOT,
    assert_pipeline_succeeded,
    poll_orchestration,
    start_func_host,
    stop_func_host,
    wait_for_func_host,
)
from simulate_upload import DEFAULT_CONTAINER, fire_event_grid, upload_kml

from treesight.constants import LOCAL_AUDIT_MAX_ARTIFACT_BYTES

SCENARIOS_DIR = REPO_ROOT / "tests" / "fixtures" / "eudr_scenarios"
OUTPUT_DIR = REPO_ROOT / ".real-acquisition-output"
FUNC_HOST_LOG_PATH = REPO_ROOT / ".real-acquisition-func-host.log"

# Mirrors corpus_runner.py's synthetic-tier pattern (#1222) so a real
# acquisition run never consumes a live org's trial/paid quota.
_RUNNER_TIER = "enterprise"
_RUNNER_USER_ID = "real-acquisition-runner"
_RUNNER_FRAME_CONCURRENCY = "1"

DEFAULT_FORMATS = ("eudr-pdf", "eudr-geojson", "eudr-csv")

# Issue #1379's acceptance checklist items that require a human to look at
# the actual output — printed at the end as a reminder, never auto-checked.
_REVIEW_CHECKLIST = (
    "Plausible NDVI/land-cover signal for the scenario's real geography",
    "Correct EUDR post-2020 (2020-12-31 cutoff) date framing in output",
    "AI narrative is coherent and non-contradictory",
    "eudr-pdf, eudr-geojson, eudr-csv exports open cleanly",
)


def _build_run_summary(status_payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the deterministic fields worth printing for a human reviewer.

    Pure function — no I/O — so it's unit-testable without a live host.
    """
    output = status_payload.get("output") or {}
    raw_paths = (output.get("artifacts") or {}).get("rawImageryPaths") or []
    return {
        "runtimeStatus": status_payload.get("runtimeStatus"),
        "aoiCount": output.get("aoiCount", 0),
        "downloadsCompleted": output.get("downloadsCompleted", 0),
        "rawImageryPathCount": len(raw_paths),
    }


def _prepare_local_ownership() -> str:
    """Check local storage before acquisition and provision the runner's membership."""
    from azure.core.exceptions import AzureError

    from treesight import config
    from treesight.pipeline.run_access import assert_run_write_access
    from treesight.security.orgs import create_org, get_user_org_strict
    from treesight.storage.cosmos import get_container

    endpoint = urlsplit(config.COSMOS_ENDPOINT)
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"localhost", "127.0.0.1", "::1", "cosmos"}
        or not config.COSMOS_KEY
    ):
        raise RuntimeError(
            "Configure a local Cosmos emulator using COSMOS_ENDPOINT (HTTP loopback or cosmos), "
            "COSMOS_KEY and COSMOS_DATABASE_NAME; live Cosmos is not supported by this runner."
        )
    try:
        for name in ("orgs", "users", "runs"):
            get_container(name).read()
        org = get_user_org_strict(_RUNNER_USER_ID)
        if org is None:
            org = create_org(_RUNNER_USER_ID, name="Local real-acquisition proof")
    except AzureError as exc:
        raise RuntimeError("Local Cosmos unavailable: initialise orgs, users and runs before acquisition.") from exc
    org_id = org.get("org_id")
    if not isinstance(org_id, str) or not org_id.strip():
        raise RuntimeError("Local runner organisation has no valid org_id.")
    assert_run_write_access({"org_id": org_id}, _RUNNER_USER_ID, active_org=org)
    return org_id


def _persist_pending_run(blob_name: str, content_length: int, org_id: str) -> str:
    """Create genuine pending ownership before publishing this run's Event Grid event."""
    from treesight.models.records import RunRecord
    from treesight.storage.cosmos import get_container

    if not org_id.strip():
        raise ValueError("Local runner organisation is required")
    instance_id = str(uuid.uuid4())
    record = RunRecord(
        submission_id=instance_id,
        instance_id=instance_id,
        user_id=_RUNNER_USER_ID,
        org_id=org_id,
        submitted_at=datetime.now(UTC).isoformat(),
        kml_blob_name=blob_name,
        kml_size_bytes=content_length,
        submission_prefix="",
        status="Pending",
        eudr_mode=True,
    )
    get_container("runs").create_item(body={"id": instance_id, **record.model_dump(exclude_none=True)})
    return instance_id


def _test_principal_header(user_id: str) -> str:
    """Build a Base64-encoded X-MS-CLIENT-PRINCIPAL value for *user_id*.

    Authenticates export-fetch requests as the same synthetic-quota runner
    identity the ticket was uploaded under (CANOPEX_ALLOW_TEST_PRINCIPAL,
    set by ``build_func_host_env(test_mode=False)``), since there is no real
    CIAM bearer token available for a local script (#1379).
    """
    import base64
    import json as _json

    principal = {
        "identityProvider": "aad",
        "userId": user_id,
        "userDetails": f"{user_id}@example.com",
        "userRoles": ["anonymous", "authenticated"],
    }
    return base64.b64encode(_json.dumps(principal).encode()).decode()


def _wdpa_configuration_warning() -> str | None:
    """Return a warning when real EUDR runs cannot perform the WDPA check."""
    if os.environ.get("WDPA_API_TOKEN"):
        return None
    return (
        "WARNING: WDPA_API_TOKEN is not configured; EUDR exports will have "
        "blank protected-area status because the check is unknown."
    )


def _configure_real_acquisition_environment() -> None:
    """Apply conservative local settings without overriding explicit values."""
    os.environ.setdefault("ENRICHMENT_FRAME_CONCURRENCY", _RUNNER_FRAME_CONCURRENCY)


@dataclass(frozen=True)
class ExportResult:
    format: str
    status: str
    http_status: int | None = None
    bytes_received: int = 0
    path: str | None = None


@dataclass(frozen=True)
class RunResult:
    fixture: str
    instance_id: str
    success: bool
    status: str
    exports: tuple[ExportResult, ...]
    schema_version: int = 1


def _write_result(dest_dir: Path, result: RunResult) -> bool:
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "result.json").write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    except OSError:
        print(f"  FAIL (result_write_error): {result.instance_id}", file=sys.stderr)
        return False
    return result.success


def _validate_csv(content: bytes) -> None:
    rows = csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True)
    header = next(rows, [])
    if not {"parcel_name", "determination_status"}.issubset(header) or len(set(header)) != len(header):
        raise ValueError("Invalid CSV header")
    row_count = 0
    for row in rows:
        if len(row) != len(header):
            raise ValueError("Invalid CSV row")
        row_count += 1
    if not row_count:
        raise ValueError("Empty CSV")


def _validate_geojson(content: bytes) -> None:
    from shapely.geometry import shape

    document = orjson.loads(content)
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ValueError("Invalid GeoJSON collection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Empty GeoJSON collection")
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("Invalid GeoJSON feature")
        if not isinstance(feature.get("properties"), dict) or "geometry" not in feature:
            raise ValueError("Invalid GeoJSON feature members")
        if feature["geometry"] is not None:
            shape(feature["geometry"])


def _validate_pdf(content: bytes) -> None:
    from pypdf import PdfReader

    logger = logging.getLogger("pypdf")
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not reader.pages:
            raise ValueError("Unreadable PDF")
        for page in reader.pages:
            page.extract_text()
    finally:
        logger.setLevel(previous_level)


def _fetch_export(instance_id: str, fmt: str, dest_dir: Path) -> ExportResult:
    """Fetch and parse a bounded export, returning only body-free diagnostics."""
    validators = {"eudr-csv": _validate_csv, "eudr-geojson": _validate_geojson, "eudr-pdf": _validate_pdf}
    if fmt not in validators:
        return ExportResult(fmt, "unsupported_format")
    url = f"{FUNC_BASE}/api/export/{instance_id}/{fmt}"
    headers = {"X-MS-CLIENT-PRINCIPAL": _test_principal_header(_RUNNER_USER_ID)}
    http_status = None
    content = bytearray()
    try:
        with httpx.stream("GET", url, headers=headers, timeout=60.0) as response:
            http_status = response.status_code
            if http_status != 200:
                return ExportResult(fmt, "http_error", http_status)
            for chunk in response.iter_bytes(chunk_size=LOCAL_AUDIT_MAX_ARTIFACT_BYTES + 1):
                if len(content) + len(chunk) > LOCAL_AUDIT_MAX_ARTIFACT_BYTES:
                    return ExportResult(fmt, "too_large", http_status, len(content) + len(chunk))
                content.extend(chunk)
    except httpx.HTTPError:
        return ExportResult(fmt, "transport_error", http_status, len(content))
    if not content:
        return ExportResult(fmt, "missing", http_status)
    try:
        validators[fmt](bytes(content))
    except Exception:
        return ExportResult(fmt, "invalid_content", http_status, len(content))
    ext = fmt.split("-", 1)[-1] if "-" in fmt else fmt
    dest = dest_dir / f"{fmt}.{ext}"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    except OSError:
        return ExportResult(fmt, "write_error", http_status, len(content))
    return ExportResult(fmt, "passed", http_status, len(content), str(dest))


def run_fixture(fixture: Path, *, formats: tuple[str, ...], org_id: str) -> bool:
    """Upload *fixture* through the real pipeline and fetch review exports.

    Returns ``True`` if the run completed with real output, ``False`` on
    failure. Expected polling and export failures are reported so the caller
    can move on to the next fixture. Unexpected setup errors propagate.
    """
    print(f"\n{'─' * 60}")
    print(f"Fixture: {fixture.name}")

    blob_name, blob_url, content_length = upload_kml(fixture, DEFAULT_CONTAINER)
    instance_id = _persist_pending_run(blob_name, content_length, org_id)
    # eudr_mode=True: these are EUDR commodity scenarios (#1379) — without it,
    # blob_trigger never sets eudr_mode on the orchestrator input, so the
    # WorldCover/WDPA enrichment phase (the actual EUDR evidence) is skipped
    # entirely and every parcel comes back "insufficient_evidence".
    _upload_ticket(
        blob_name, DEFAULT_CONTAINER, tier=_RUNNER_TIER, user_id=_RUNNER_USER_ID, eudr_mode=True, org_id=org_id
    )

    fire_event_grid(blob_url, blob_name, content_length, DEFAULT_CONTAINER, event_id=instance_id)
    print(f"  instance_id: {instance_id}")
    dest_dir = OUTPUT_DIR / fixture.stem / instance_id

    print("  Polling orchestration against the REAL imagery provider (this can take a while)...")
    try:
        status_payload = poll_orchestration(instance_id, timeout=900.0)
        assert_pipeline_succeeded(status_payload)
    except (TimeoutError, AssertionError) as exc:
        status = "timeout" if isinstance(exc, TimeoutError) else "pipeline_failure"
        print(f"  FAIL ({status}): {instance_id}", file=sys.stderr)
        exports = tuple(ExportResult(fmt, "not_attempted") for fmt in formats)
        return _write_result(dest_dir, RunResult(str(fixture), instance_id, False, status, exports))

    summary = _build_run_summary(status_payload)
    print(f"  summary: {summary}")

    exports = tuple(_fetch_export(instance_id, fmt, dest_dir) for fmt in formats)
    for export in exports:
        if export.status != "passed":
            print(f"  FAIL (export): {export.format} for {instance_id}: {export.status}", file=sys.stderr)
        else:
            print(f"  saved {export.format} -> {export.path}")
    success = bool(exports) and all(export.status == "passed" for export in exports)
    result = RunResult(str(fixture), instance_id, success, "passed" if success else "export_failure", exports)
    if not _write_result(dest_dir, result):
        return False

    print("  PASS (mechanical) — human review still required, see checklist below.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run real-world EUDR fixtures through the REAL Planetary Computer pipeline for human review."
    )
    parser.add_argument(
        "fixtures",
        nargs="*",
        type=Path,
        metavar="KML",
        help="KML fixture paths to run (default: all *.kml in tests/fixtures/eudr_scenarios/)",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=list(DEFAULT_FORMATS),
        help=f"Export formats to fetch after each run (default: {' '.join(DEFAULT_FORMATS)})",
    )
    args = parser.parse_args()

    warning = _wdpa_configuration_warning()
    if warning:
        print(warning, file=sys.stderr)

    _configure_real_acquisition_environment()

    fixtures: list[Path] = args.fixtures or sorted(SCENARIOS_DIR.glob("*.kml"))
    if not fixtures:
        print(f"No KML fixtures found in {SCENARIOS_DIR}.", file=sys.stderr)
        sys.exit(1)

    org_id = _prepare_local_ownership()
    proc = start_func_host(log_path=FUNC_HOST_LOG_PATH, test_mode=False)
    passed = failed = 0
    try:
        print("[1/2] Waiting for func host to become ready (real imagery provider)...")
        wait_for_func_host(timeout=120.0)

        print(f"[2/2] Running {len(fixtures)} real-world fixture(s) through the pipeline...")
        for fixture in fixtures:
            ok = run_fixture(fixture, formats=tuple(args.formats), org_id=org_id)
            if ok:
                passed += 1
            else:
                failed += 1

        print(f"\nResults: {passed} passed, {failed} failed out of {len(fixtures)} fixture(s).")
    except Exception:
        print(f"\nFATAL — see func host log at {FUNC_HOST_LOG_PATH}", file=sys.stderr)
        raise
    finally:
        stop_func_host(proc)

    print(f"\nRun results under {OUTPUT_DIR.relative_to(REPO_ROOT)}/<fixture-name>/<instance-id>/result.json")
    print("\nManual review still required before signing off #1379 (human decision gate):")
    for item in _REVIEW_CHECKLIST:
        print(f"  [ ] {item}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
