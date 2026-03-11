"""Tests for diagnostics endpoint auth levels (Issue #131).

Operational diagnostics endpoints must be callable without a function key,
otherwise deployment smoke checks and remote triage can fail with 401.
"""

from __future__ import annotations

from pathlib import Path


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
    assert "@app.route(" in source
    assert 'route="orchestrator/{instance_id}"' in source
    assert "auth_level=func.AuthLevel.ANONYMOUS" in source
