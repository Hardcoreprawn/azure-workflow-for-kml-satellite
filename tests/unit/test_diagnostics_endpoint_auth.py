"""Tests for diagnostics endpoint auth levels (Issue #131).

Operational diagnostics endpoints must be callable without a function key,
otherwise deployment smoke checks and remote triage can fail with 401.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from function_app import _build_orchestrator_diagnostics_payload


def _function_app_source() -> str:
    app_path = Path(__file__).parent.parent.parent / "function_app.py"
    return app_path.read_text(encoding="utf-8")


def test_health_route_is_anonymous() -> None:
    source = _function_app_source()
    expected = '@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)'
    assert expected in source


def test_readiness_route_is_anonymous() -> None:
    source = _function_app_source()
    expected = (
        '@app.route(route="readiness", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)'
    )
    assert expected in source


def test_orchestrator_status_route_is_anonymous() -> None:
    source = _function_app_source()
    pattern = re.compile(
        r'@app\.route\(\s*route="orchestrator/\{instance_id\}".*?auth_level=func\.AuthLevel\.ANONYMOUS.*?\)',
        flags=re.DOTALL,
    )
    assert pattern.search(source)


def test_orchestrator_status_returns_direct_diagnostics_payload() -> None:
    status = SimpleNamespace(
        instance_id="orch-123",
        name="kml_processing_orchestrator",
        runtime_status="Completed",
        created_time=datetime(2026, 3, 11, 22, 0, tzinfo=UTC),
        last_updated_time=datetime(2026, 3, 11, 22, 5, tzinfo=UTC),
        custom_status={"phase": "fulfilled"},
        output={
            "status": "completed",
            "message": "Pipeline completed",
            "blob_name": "orchard.kml",
            "feature_count": 2,
            "metadata_count": 2,
            "imagery_ready": 2,
            "imagery_failed": 0,
            "downloads_completed": 2,
            "post_process_completed": 2,
            "metadata_results": [
                {"metadata_path": "metadata/2026/03/orchard/block-a.json"},
                {"metadata_path": "metadata/2026/03/orchard/block-b.json"},
            ],
            "download_results": [
                {"blob_path": "imagery/raw/2026/03/orchard/block-a.tif"},
                {"blob_path": "imagery/raw/2026/03/orchard/block-b.tif"},
            ],
            "post_process_results": [
                {"clipped_blob_path": "imagery/clipped/2026/03/orchard/block-a.tif"},
                {"clipped_blob_path": "imagery/clipped/2026/03/orchard/block-b.tif"},
            ],
        },
    )

    payload = _build_orchestrator_diagnostics_payload(status)

    assert payload["instanceId"] == "orch-123"
    assert payload["runtimeStatus"] == "Completed"
    assert payload["output"]["status"] == "completed"
    assert payload["output"]["artifacts"]["metadataPaths"] == [
        "metadata/2026/03/orchard/block-a.json",
        "metadata/2026/03/orchard/block-b.json",
    ]
    assert payload["output"]["artifacts"]["rawImageryPaths"] == [
        "imagery/raw/2026/03/orchard/block-a.tif",
        "imagery/raw/2026/03/orchard/block-b.tif",
    ]
    assert payload["output"]["artifacts"]["clippedImageryPaths"] == [
        "imagery/clipped/2026/03/orchard/block-a.tif",
        "imagery/clipped/2026/03/orchard/block-b.tif",
    ]
