"""AOI regression corpus runner (#1222).

Runs the full fixture corpus through the real offline pipeline and diffs each
run against a recorded baseline, catching correctness regressions for known-
tricky geometries (concave polygons, adjacent polygons, polygons with holes,
huge polygon counts, multi-feature files, etc.).

Prerequisite
------------
Azurite must be running (``make dev-up``, or a sibling ``azurite`` service in CI).
The corpus runner manages its own ``func start`` lifecycle — you do **not** need
a separate running func host.

Usage
-----
    # Run the full corpus and fail on any drift:
    uv run python scripts/corpus_runner.py

    # Run only specific fixtures:
    uv run python scripts/corpus_runner.py tests/fixtures/sample.kml tests/fixtures/concave_polygon.kml

    # Record/update baselines (generates a reviewable diff in git):
    uv run python scripts/corpus_runner.py --update-baseline

    # Update baselines for specific fixtures only:
    uv run python scripts/corpus_runner.py --update-baseline tests/fixtures/concave_polygon.kml

Adding a new AOI fixture to the corpus
---------------------------------------
1. Drop the KML file in ``tests/fixtures/``.
2. Run ``uv run python scripts/corpus_runner.py --update-baseline tests/fixtures/<new>.kml``.
3. Review the new ``tests/fixtures/baselines/<name>.json`` with ``git diff``.
4. Commit **both** the KML and its baseline in the same PR — the baseline is the
   reviewed contract for that fixture; a change to the baseline must always be
   visible as a diff.

Design decision: baseline comparison tolerance
-----------------------------------------------
Integer counts (``aoi_count``, ``downloadsCompleted``, ``rawImageryPathCount``)
use **exact equality** — no tolerance band.  The stub provider is fully
deterministic: pixel values are fixed constants, AOI counts come from
deterministic KML parsing, and download/path counts are a direct function of the
AOI count.  Any numeric drift is a regression, not floating-point noise.

Fields *not* compared (intentionally excluded from baselines): scene IDs, blob
path components that embed UUIDs/timestamps, per-pixel NDVI values.  These vary
across runs by design (UUIDs, acquisition dates) and their correctness is covered
by unit tests in ``tests/test_providers.py`` and ``tests/test_fulfilment.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from _azurite import AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient, ContentSettings
from e2e_local import (
    FUNC_HOST_LOG_PATH,
    assert_pipeline_succeeded,
    poll_orchestration,
    start_func_host,
    stop_func_host,
    wait_for_func_host,
)
from simulate_upload import DEFAULT_CONTAINER, fire_event_grid, upload_kml

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINES_DIR = REPO_ROOT / "tests" / "fixtures" / "baselines"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

# Enterprise tier has aoi_limit=None (unlimited) — lets the corpus runner
# process every fixture regardless of AOI count without tier-gate failures.
_CORPUS_TIER = "enterprise"
_CORPUS_USER_ID = "corpus-runner"


def _upload_ticket(blob_name: str, container: str) -> None:
    """Write a submission ticket so the pipeline uses the corpus tier.

    The ticket is read by the blob_trigger to enrich the orchestrator input
    with tier/user metadata.  Without it the pipeline defaults to free tier
    (aoi_limit=5), which would reject large fixtures like monster_200.kml.
    """
    stem = Path(blob_name).stem
    ticket: dict[str, Any] = {"tier": _CORPUS_TIER, "user_id": _CORPUS_USER_ID}
    ticket_path = f".tickets/{stem}.json"
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container_client = client.get_container_client(container)
    if not container_client.exists():
        container_client.create_container()
    client.get_blob_client(container, ticket_path).upload_blob(
        json.dumps(ticket).encode(),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def _extract_actual(status_payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the deterministic fields the baseline records from a pipeline result."""
    output = status_payload.get("output") or {}
    raw_paths = (output.get("artifacts") or {}).get("rawImageryPaths") or []
    return {
        "aoi_count": output.get("aoiCount", 0),
        "downloadsCompleted": output.get("downloadsCompleted", 0),
        "rawImageryPathCount": len(raw_paths),
    }


def _load_baseline(fixture: Path) -> dict[str, Any] | None:
    """Return the baseline dict for *fixture*, or ``None`` if absent."""
    baseline_path = BASELINES_DIR / f"{fixture.stem}.json"
    if not baseline_path.exists():
        return None
    return json.loads(baseline_path.read_text())


def _save_baseline(fixture: Path, actual: dict[str, Any]) -> None:
    """Write/update the baseline for *fixture* with *actual* values."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = BASELINES_DIR / f"{fixture.stem}.json"
    baseline = {
        "_comment": (
            "Deterministic baseline for offline corpus runner (#1222). "
            "Integer counts are exact-match; no tolerance band needed for stub output. "
            "Regenerate with: uv run python scripts/corpus_runner.py --update-baseline"
        ),
        "fixture": fixture.name,
        "aoi_count": actual["aoi_count"],
        "expected_downloads_completed": actual["downloadsCompleted"],
        "expected_raw_imagery_path_count": actual["rawImageryPathCount"],
    }
    baseline_path.write_text(json.dumps(baseline, indent=2) + "\n")
    try:
        display = baseline_path.relative_to(REPO_ROOT)
    except ValueError:
        display = baseline_path
    print(f"  Baseline saved → {display}")


def _diff_against_baseline(
    fixture: Path,
    actual: dict[str, Any],
    baseline: dict[str, Any],
) -> list[str]:
    """Return a list of human-readable drift lines (empty = no drift)."""
    drifts: list[str] = []
    checks = [
        ("aoi_count", actual["aoi_count"], baseline.get("aoi_count")),
        (
            "downloadsCompleted",
            actual["downloadsCompleted"],
            baseline.get("expected_downloads_completed"),
        ),
        (
            "rawImageryPathCount",
            actual["rawImageryPathCount"],
            baseline.get("expected_raw_imagery_path_count"),
        ),
    ]
    for field, got, expected in checks:
        if expected is None:
            continue
        if got != expected:
            drifts.append(f"    {field}: expected {expected!r}, got {got!r}")
    return drifts


def run_fixture(
    fixture: Path,
    *,
    update_baseline: bool,
) -> bool:
    """Upload *fixture* through the pipeline and compare/update its baseline.

    Returns ``True`` on pass, ``False`` on drift or failure.
    """
    print(f"\n{'─' * 60}")
    print(f"Fixture: {fixture.name}")

    blob_name, blob_url, content_length = upload_kml(fixture, DEFAULT_CONTAINER)
    _upload_ticket(blob_name, DEFAULT_CONTAINER)

    instance_id = fire_event_grid(blob_url, blob_name, content_length, DEFAULT_CONTAINER)

    print("  Polling orchestration ...")
    try:
        status_payload = poll_orchestration(instance_id, timeout=300.0)
    except TimeoutError as exc:
        print(f"  FAIL (timeout): {exc}", file=sys.stderr)
        return False

    try:
        assert_pipeline_succeeded(status_payload)
    except AssertionError as exc:
        print(f"  FAIL (pipeline): {exc}", file=sys.stderr)
        return False

    actual = _extract_actual(status_payload)
    print(f"  actual: {actual}")

    if update_baseline:
        _save_baseline(fixture, actual)
        return True

    baseline = _load_baseline(fixture)
    if baseline is None:
        print(
            f"  WARN: no baseline found at {BASELINES_DIR / f'{fixture.stem}.json'} — "
            "run with --update-baseline to record one.",
            file=sys.stderr,
        )
        # Missing baseline is not itself a failure — flag as warning only.
        return True

    drifts = _diff_against_baseline(fixture, actual, baseline)
    if drifts:
        print("  FAIL (baseline drift):", file=sys.stderr)
        for line in drifts:
            print(line, file=sys.stderr)
        return False

    print("  PASS")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run KML fixtures through the offline pipeline and diff against baselines."
    )
    parser.add_argument(
        "fixtures",
        nargs="*",
        type=Path,
        metavar="KML",
        help="KML fixture paths to run (default: all *.kml in tests/fixtures/)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write/update baselines instead of comparing; always produces a reviewable git diff.",
    )
    args = parser.parse_args()

    fixtures: list[Path] = args.fixtures or sorted(FIXTURES_DIR.glob("*.kml"))
    if not fixtures:
        print("No KML fixtures found.", file=sys.stderr)
        sys.exit(1)

    # Avoid proxy env vars breaking localhost httpx calls in CI/dev shells.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY"):
        os.environ.pop(var, None)
        os.environ.pop(var.lower(), None)

    proc = start_func_host(log_path=FUNC_HOST_LOG_PATH)
    passed = failed = 0
    try:
        print("[1/3] Waiting for func host to become ready...")
        wait_for_func_host(timeout=120.0)

        print(f"[2/3] Running {len(fixtures)} fixture(s) through the pipeline...")
        for fixture in fixtures:
            ok = run_fixture(fixture, update_baseline=args.update_baseline)
            if ok:
                passed += 1
            else:
                failed += 1

        print(f"\n[3/3] Results: {passed} passed, {failed} failed out of {len(fixtures)} fixture(s).")
    except Exception:
        print(f"\nFATAL — see func host log at {FUNC_HOST_LOG_PATH}", file=sys.stderr)
        raise
    finally:
        stop_func_host(proc)

    if failed:
        print(
            "\nFAIL — baseline drift or pipeline errors detected. "
            "Review diffs above. To accept intentional changes, re-run with --update-baseline.",
            file=sys.stderr,
        )
        sys.exit(1)

    action = "updated" if args.update_baseline else "passed"
    print(f"\nPASS — all fixture baselines {action}.")


if __name__ == "__main__":
    main()
