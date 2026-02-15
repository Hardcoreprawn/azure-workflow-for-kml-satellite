"""Tests for the KML processing orchestrator.

Uses a mock DurableOrchestrationContext to verify the orchestrator's
behaviour without Azure infrastructure.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from kml_satellite.orchestrators.kml_pipeline import orchestrator_function


def _make_context(
    input_data: dict[str, str | int],
    *,
    instance_id: str = "test-instance-001",
    is_replaying: bool = False,
) -> MagicMock:
    """Create a mock DurableOrchestrationContext."""
    context = MagicMock()
    context.get_input.return_value = input_data
    context.instance_id = instance_id
    context.is_replaying = is_replaying
    return context


def _sample_blob_event() -> dict[str, str | int]:
    """Return a sample BlobEvent dict."""
    return {
        "blob_url": "https://stkmlsatdev.blob.core.windows.net/kml-input/orchard.kml",
        "container_name": "kml-input",
        "blob_name": "orchard.kml",
        "content_length": 2048,
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": "2026-02-15T12:00:00",
        "correlation_id": "evt-abc-123",
    }


class TestOrchestratorFunction:
    """Verify the stub orchestrator behaviour."""

    def test_returns_accepted_status(self) -> None:
        """Orchestrator stub returns 'accepted' status."""
        context = _make_context(_sample_blob_event())
        result = orchestrator_function(context)
        assert result["status"] == "accepted"

    def test_includes_instance_id(self) -> None:
        """Result includes the orchestration instance ID."""
        context = _make_context(_sample_blob_event(), instance_id="my-id-42")
        result = orchestrator_function(context)
        assert result["instance_id"] == "my-id-42"

    def test_includes_blob_name(self) -> None:
        """Result includes the blob name from the event."""
        context = _make_context(_sample_blob_event())
        result = orchestrator_function(context)
        assert result["blob_name"] == "orchard.kml"

    def test_includes_blob_url(self) -> None:
        """Result includes the full blob URL."""
        event = _sample_blob_event()
        context = _make_context(event)
        result = orchestrator_function(context)
        assert result["blob_url"] == event["blob_url"]

    def test_reads_input_from_context(self) -> None:
        """Orchestrator calls context.get_input() to retrieve the event."""
        context = _make_context(_sample_blob_event())
        orchestrator_function(context)
        context.get_input.assert_called_once()

    def test_handles_missing_blob_name(self) -> None:
        """Orchestrator handles missing blob_name gracefully."""
        event = _sample_blob_event()
        del event["blob_name"]
        context = _make_context(event)
        result = orchestrator_function(context)
        assert result["blob_name"] == "<unknown>"
        assert result["status"] == "accepted"

    def test_replay_does_not_log(self) -> None:
        """During replay, the orchestrator skips logging (is_replaying=True).

        We can't easily assert no logging without more machinery, but we
        verify no crash and correct result.
        """
        context = _make_context(_sample_blob_event(), is_replaying=True)
        result = orchestrator_function(context)
        assert result["status"] == "accepted"
