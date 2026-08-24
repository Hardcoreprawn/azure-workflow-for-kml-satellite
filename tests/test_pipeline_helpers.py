"""Tests for blueprints.pipeline._status durable status shaping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import blueprints.pipeline._status as status_module
from treesight import config


def test_stalled_payload_preserves_existing_phase():
    """A stalled run keeps its known phase instead of falling back to queued."""
    stale = datetime.now(UTC) - timedelta(hours=2)
    status = SimpleNamespace(
        runtime_status=SimpleNamespace(value="Running"),
        custom_status={"phase": "enrichment", "step": "per_aoi"},
        last_updated_time=stale,
        history=None,
    )

    runtime, custom = status_module._normalize_runtime_status_payload(status)

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

    runtime, custom = status_module._normalize_runtime_status_payload(status)

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

    runtime, custom = status_module._normalize_runtime_status_payload(
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

    assert status_module._needs_telemetry_recovery(status) is True


def test_fetch_instance_telemetry_hint_does_not_fail_on_trace_error(monkeypatch):
    monkeypatch.setattr(config, "LOG_ANALYTICS_WORKSPACE_ID", "workspace-id")
    monkeypatch.setattr(config, "STATUS_RECOVERY_LOOKBACK_MINUTES", 120)
    monkeypatch.setattr(
        status_module,
        "_query_logs_workspace",
        lambda *_args, **_kwargs: [
            {
                "timestamp": datetime.now(UTC),
                "phase": "acquisition",
                "step": "searching",
                "error": "provider timeout",
                "source": "trace",
            }
        ],
    )

    hint = status_module._fetch_instance_telemetry_hint("inst-1")

    assert hint is not None
    assert hint["outcome"] == "active"


def test_fetch_instance_telemetry_hint_marks_exception_as_failed(monkeypatch):
    monkeypatch.setattr(config, "LOG_ANALYTICS_WORKSPACE_ID", "workspace-id")
    monkeypatch.setattr(config, "STATUS_RECOVERY_LOOKBACK_MINUTES", 120)
    monkeypatch.setattr(
        status_module,
        "_query_logs_workspace",
        lambda *_args, **_kwargs: [
            {
                "timestamp": datetime.now(UTC),
                "phase": "fulfilment",
                "step": "downloading",
                "error": "fatal error",
                "source": "exception",
            }
        ],
    )

    hint = status_module._fetch_instance_telemetry_hint("inst-2")

    assert hint is not None
    assert hint["outcome"] == "failed"


def test_fetch_instance_telemetry_hint_clamps_lookback_minutes(monkeypatch):
    monkeypatch.setattr(config, "LOG_ANALYTICS_WORKSPACE_ID", "workspace-id")
    monkeypatch.setattr(config, "STATUS_RECOVERY_LOOKBACK_MINUTES", -10)
    captured_query: dict[str, str] = {}

    def _fake_query(_workspace_id: str, query: str):
        captured_query["value"] = query
        return []

    monkeypatch.setattr(status_module, "_query_logs_workspace", _fake_query)

    status_module._fetch_instance_telemetry_hint("inst-3")

    assert "ago(1m)" in captured_query["value"]
