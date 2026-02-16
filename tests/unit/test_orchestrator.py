"""Tests for the KML processing orchestrator.

Uses a mock DurableOrchestrationContext to verify the orchestrator's
behaviour without Azure infrastructure.

The orchestrator is a **generator** function (it ``yield``s durable-task
calls), so our helper ``_run_orchestrator`` drives it via the generator
protocol: ``next()`` to advance to the first yield, then ``send()`` to
supply the activity result and collect the final ``return`` value.
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


def _run_orchestrator(
    context: MagicMock,
    *,
    features: list[dict[str, object]] | None = None,
    aois: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Drive the generator orchestrator to completion.

    Args:
        context: Mock DurableOrchestrationContext.
        features: Simulated return value of the ``parse_kml`` activity.
            Defaults to an empty list.
        aois: Simulated return value of the ``prepare_aoi`` fan-out.
            Defaults to a list the same length as *features*.

    Returns:
        The final result dict returned by the orchestrator.
    """
    if features is None:
        features = []
    if aois is None:
        aois = [{"feature_name": f"aoi-{i}"} for i in range(len(features))]
    gen = orchestrator_function(context)
    next(gen)  # advance to the first yield (parse_kml call)
    gen.send(features)  # supply features, advance to second yield (task_all)
    try:
        gen.send(aois)  # supply AOIs, orchestrator returns
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]
    msg = "Orchestrator did not return after prepare_aoi fan-out"
    raise RuntimeError(msg)


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
    """Verify the orchestrator behaviour with the parse_kml activity wired."""

    def test_returns_aois_prepared_status(self) -> None:
        """Orchestrator returns 'aois_prepared' status after both phases."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(context)
        assert result["status"] == "aois_prepared"

    def test_includes_instance_id(self) -> None:
        """Result includes the orchestration instance ID."""
        context = _make_context(_sample_blob_event(), instance_id="my-id-42")
        result = _run_orchestrator(context)
        assert result["instance_id"] == "my-id-42"

    def test_includes_blob_name(self) -> None:
        """Result includes the blob name from the event."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(context)
        assert result["blob_name"] == "orchard.kml"

    def test_includes_blob_url(self) -> None:
        """Result includes the full blob URL."""
        event = _sample_blob_event()
        context = _make_context(event)
        result = _run_orchestrator(context)
        assert result["blob_url"] == event["blob_url"]

    def test_reads_input_from_context(self) -> None:
        """Orchestrator calls context.get_input() to retrieve the event."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(context)
        context.get_input.assert_called_once()

    def test_handles_missing_blob_name(self) -> None:
        """Orchestrator handles missing blob_name gracefully."""
        event = _sample_blob_event()
        del event["blob_name"]
        context = _make_context(event)
        result = _run_orchestrator(context)
        assert result["blob_name"] == "<unknown>"
        assert result["status"] == "aois_prepared"

    def test_replay_does_not_log(self) -> None:
        """During replay, the orchestrator skips logging (is_replaying=True).

        We can't easily assert no logging without more machinery, but we
        verify no crash and correct result.
        """
        context = _make_context(_sample_blob_event(), is_replaying=True)
        result = _run_orchestrator(context)
        assert result["status"] == "aois_prepared"

    def test_calls_parse_kml_activity(self) -> None:
        """Orchestrator calls parse_kml activity with the blob event."""
        event = _sample_blob_event()
        context = _make_context(event)
        _run_orchestrator(context)
        context.call_activity.assert_any_call("parse_kml", event)

    def test_feature_count_in_result(self) -> None:
        """Result includes the count of features returned by parse_kml."""
        context = _make_context(_sample_blob_event())
        fake_features = [{"name": "f1"}, {"name": "f2"}, {"name": "f3"}]
        fake_aois = [{"feature_name": "a1"}, {"feature_name": "a2"}, {"feature_name": "a3"}]
        result = _run_orchestrator(context, features=fake_features, aois=fake_aois)
        assert result["feature_count"] == 3
        assert result["aoi_count"] == 3
