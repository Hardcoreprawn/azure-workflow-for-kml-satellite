"""Tests for blueprints.pipeline._status durable status shaping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from blueprints.pipeline._status import (
    _needs_telemetry_recovery,
    _normalize_runtime_status_payload,
)


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


def test_telemetry_hint_prevents_false_stalled_classification():
    """Recent telemetry activity keeps long-running runs active."""
    stale = datetime.now(UTC) - timedelta(hours=2)
    status = SimpleNamespace(
        runtime_status=SimpleNamespace(value="Running"),
        custom_status={"phase": "ingestion", "step": "preparing_aois"},
        last_updated_time=stale,
        history=None,
    )

    runtime, custom = _normalize_runtime_status_payload(
        status,
        telemetry_hint={
            "phase": "acquisition",
            "step": "searching",
            "outcome": "active",
            "observed_at": datetime.now(UTC),
        },
    )

    assert runtime == "Running"
    assert custom is not None
    assert custom["phase"] == "acquisition"
    assert custom["step"] == "searching"


def test_needs_telemetry_recovery_for_stale_ingestion_run():
    stale = datetime.now(UTC) - timedelta(hours=2)
    status = SimpleNamespace(
        runtime_status=SimpleNamespace(value="Running"),
        custom_status={"phase": "ingestion", "step": "preparing_aois"},
        last_updated_time=stale,
        history=None,
    )

    assert _needs_telemetry_recovery(status) is True
