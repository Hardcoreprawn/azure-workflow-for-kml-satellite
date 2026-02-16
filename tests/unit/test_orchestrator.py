"""Tests for the KML processing orchestrator.

Uses a mock DurableOrchestrationContext to verify the orchestrator's
behaviour without Azure infrastructure.

The orchestrator is a **generator** function (it ``yield``s durable-task
calls), so our helper ``_run_orchestrator`` drives it via the generator
protocol: ``next()`` to advance to the first yield, then ``send()`` to
supply each activity result.

Current phases:
1. parse_kml — single activity call
2. prepare_aoi — fan-out via task_all
3. write_metadata — fan-out via task_all
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
    metadata_results: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Drive the three-phase generator orchestrator to completion.

    Args:
        context: Mock DurableOrchestrationContext.
        features: Simulated return of ``parse_kml`` activity.
        aois: Simulated return of ``prepare_aoi`` fan-out.
        metadata_results: Simulated return of ``write_metadata`` fan-out.

    Returns:
        The final result dict returned by the orchestrator.
    """
    if features is None:
        features = []
    if aois is None:
        aois = [{"feature_name": f"aoi-{i}"} for i in range(len(features))]
    if metadata_results is None:
        metadata_results = [
            {"metadata_path": f"metadata/2026/02/test/aoi-{i}.json"} for i in range(len(aois))
        ]

    gen = orchestrator_function(context)
    next(gen)  # advance to first yield (parse_kml)
    gen.send(features)  # supply features → second yield (prepare_aoi task_all)
    gen.send(aois)  # supply AOIs → third yield (write_metadata task_all)
    try:
        gen.send(metadata_results)  # supply metadata → orchestrator returns
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]
    msg = "Orchestrator did not return after write_metadata fan-out"
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
    """Verify the orchestrator behaviour across all three phases."""

    def test_returns_metadata_written_status(self) -> None:
        """Orchestrator returns 'metadata_written' status after all phases."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(context)
        assert result["status"] == "metadata_written"

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
        assert result["status"] == "metadata_written"

    def test_replay_does_not_log(self) -> None:
        """During replay (is_replaying=True), orchestrator still works."""
        context = _make_context(_sample_blob_event(), is_replaying=True)
        result = _run_orchestrator(context)
        assert result["status"] == "metadata_written"

    def test_calls_parse_kml_activity(self) -> None:
        """Orchestrator calls parse_kml activity with the blob event."""
        event = _sample_blob_event()
        context = _make_context(event)
        _run_orchestrator(context)
        context.call_activity.assert_any_call("parse_kml", event)

    def test_feature_count_in_result(self) -> None:
        """Result includes counts of features, AOIs, and metadata records."""
        context = _make_context(_sample_blob_event())
        fake_features = [{"name": "f1"}, {"name": "f2"}, {"name": "f3"}]
        fake_aois = [{"feature_name": "a1"}, {"feature_name": "a2"}, {"feature_name": "a3"}]
        fake_meta = [{"metadata_path": "p1"}, {"metadata_path": "p2"}, {"metadata_path": "p3"}]
        result = _run_orchestrator(
            context, features=fake_features, aois=fake_aois, metadata_results=fake_meta
        )
        assert result["feature_count"] == 3
        assert result["aoi_count"] == 3
        assert result["metadata_count"] == 3

    def test_metadata_count_in_result(self) -> None:
        """metadata_count reflects the number of metadata records written."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            metadata_results=[{"metadata_path": "metadata/test.json"}],
        )
        assert result["metadata_count"] == 1

    def test_message_includes_metadata_count(self) -> None:
        """Result message mentions metadata records."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}, {"name": "f2"}],
            aois=[{"feature_name": "a1"}, {"feature_name": "a2"}],
            metadata_results=[{"p": 1}, {"p": 2}],
        )
        assert "2 metadata record(s)" in result["message"]

    def test_write_metadata_called_with_aois(self) -> None:
        """Orchestrator calls write_metadata for each AOI."""
        context = _make_context(_sample_blob_event(), instance_id="inst-99")
        fake_features = [{"name": "f1"}]
        fake_aois = [{"feature_name": "a1"}]
        _run_orchestrator(context, features=fake_features, aois=fake_aois)
        # Verify write_metadata was called with the AOI and processing_id
        calls = [c for c in context.call_activity.call_args_list if c[0][0] == "write_metadata"]
        assert len(calls) == 1
        payload = calls[0][0][1]
        assert payload["aoi"] == {"feature_name": "a1"}
        assert payload["processing_id"] == "inst-99"
