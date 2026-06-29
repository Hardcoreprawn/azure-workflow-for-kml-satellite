"""Tests for blueprints.pipeline._status durable status shaping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from blueprints.pipeline._status import _normalize_runtime_status_payload


def test_stalled_payload_preserves_existing_phase():
    """A stalled run keeps its known phase instead of falling back to queued."""
    stale = datetime.now(UTC) - timedelta(hours=2)
    status = SimpleNamespace(
        runtime_status=SimpleNamespace(value="Running"),
        custom_status={"phase": "enrichment", "step": "per_aoi"},
        last_updated_time=stale,
        history=None,
    )

    runtime, custom = _normalize_runtime_status_payload(status)

    assert runtime == "Stalled"
    assert custom is not None
    assert custom["stalled"] is True
    assert custom["phase"] == "enrichment"  # not overwritten to "queued"
    assert custom["step"] == "per_aoi"


def test_stalled_payload_falls_back_when_phase_unknown():
    """A stalled run with no phase defaults to queued/no_recent_updates."""
    stale = datetime.now(UTC) - timedelta(hours=2)
    status = SimpleNamespace(
        runtime_status=SimpleNamespace(value="Running"),
        custom_status=None,
        last_updated_time=stale,
        history=None,
    )

    runtime, custom = _normalize_runtime_status_payload(status)

    assert runtime == "Stalled"
    assert custom is not None
    assert custom["phase"] == "queued"
    assert custom["step"] == "no_recent_updates"
