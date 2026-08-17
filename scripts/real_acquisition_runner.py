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
Azurite must already be running (``make dev-up``). This script manages its
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

Exports are written to ``.real-acquisition-output/<fixture-stem>/`` for
manual review. See issue #1379's acceptance checklist for what to look for
(NDVI/land-cover plausibility, EUDR post-2020 date framing, AI narrative
coherence) — none of that is checked automatically here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx
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

SCENARIOS_DIR = REPO_ROOT / "tests" / "fixtures" / "eudr_scenarios"
OUTPUT_DIR = REPO_ROOT / ".real-acquisition-output"
FUNC_HOST_LOG_PATH = REPO_ROOT / ".real-acquisition-func-host.log"

# Mirrors corpus_runner.py's synthetic-tier pattern (#1222) so a real
# acquisition run never consumes a live org's trial/paid quota.
_RUNNER_TIER = "enterprise"
_RUNNER_USER_ID = "real-acquisition-runner"

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


def _fetch_export(instance_id: str, fmt: str, dest_dir: Path) -> Path | None:
    """Download one export format for *instance_id*, or return None on failure."""
    url = f"{FUNC_BASE}/api/export/{instance_id}/{fmt}"
    try:
        resp = httpx.get(url, timeout=60.0)
    except httpx.TransportError as exc:
        print(f"  WARN: export {fmt!r} request failed: {exc}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        print(f"  WARN: export {fmt!r} returned HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = fmt.split("-", 1)[-1] if "-" in fmt else fmt
    dest = dest_dir / f"{fmt}.{ext}"
    dest.write_bytes(resp.content)
    return dest


def run_fixture(fixture: Path, *, formats: tuple[str, ...]) -> bool:
    """Upload *fixture* through the real pipeline and fetch review exports.

    Returns ``True`` if the run completed with real output, ``False`` on
    failure. Never raises — failures are reported and the caller moves on
    to the next fixture, matching ``corpus_runner.py``'s behaviour.
    """
    print(f"\n{'─' * 60}")
    print(f"Fixture: {fixture.name}")

    blob_name, blob_url, content_length = upload_kml(fixture, DEFAULT_CONTAINER)
    _upload_ticket(blob_name, DEFAULT_CONTAINER, tier=_RUNNER_TIER, user_id=_RUNNER_USER_ID)

    instance_id = fire_event_grid(blob_url, blob_name, content_length, DEFAULT_CONTAINER)

    print("  Polling orchestration against the REAL imagery provider (this can take a while)...")
    try:
        status_payload = poll_orchestration(instance_id, timeout=900.0)
    except TimeoutError as exc:
        print(f"  FAIL (timeout): {exc}", file=sys.stderr)
        return False

    try:
        assert_pipeline_succeeded(status_payload)
    except AssertionError as exc:
        print(f"  FAIL (pipeline): {exc}", file=sys.stderr)
        return False

    summary = _build_run_summary(status_payload)
    print(f"  summary: {summary}")

    dest_dir = OUTPUT_DIR / fixture.stem
    for fmt in formats:
        dest = _fetch_export(instance_id, fmt, dest_dir)
        if dest is not None:
            print(f"  saved {fmt} -> {dest.relative_to(REPO_ROOT)}")

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

    fixtures: list[Path] = args.fixtures or sorted(SCENARIOS_DIR.glob("*.kml"))
    if not fixtures:
        print(f"No KML fixtures found in {SCENARIOS_DIR}.", file=sys.stderr)
        sys.exit(1)

    proc = start_func_host(log_path=FUNC_HOST_LOG_PATH, test_mode=False)
    passed = failed = 0
    try:
        print("[1/2] Waiting for func host to become ready (real imagery provider)...")
        wait_for_func_host(timeout=120.0)

        print(f"[2/2] Running {len(fixtures)} real-world fixture(s) through the pipeline...")
        for fixture in fixtures:
            ok = run_fixture(fixture, formats=tuple(args.formats))
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

    print(f"\nExports saved under {OUTPUT_DIR.relative_to(REPO_ROOT)}/<fixture-name>/")
    print("\nManual review still required before signing off #1379 (human decision gate):")
    for item in _REVIEW_CHECKLIST:
        print(f"  [ ] {item}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
