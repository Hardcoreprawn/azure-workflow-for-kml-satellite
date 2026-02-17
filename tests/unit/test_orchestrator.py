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
4. acquire_imagery — fan-out via task_all
5. poll_order — timer-based polling loop per order

References:
    PID FR-3.9  (poll until completion with timeout)
    PID FR-5.3  (Durable Functions for long-running workflows)
    PID FR-6.4  (exponential backoff)
    PID Section 7.2 (Fan-Out / Fan-In pattern)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from kml_satellite.orchestrators.kml_pipeline import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_RETRY_BASE_SECONDS,
    _poll_until_ready,
    orchestrator_function,
)


def _make_context(
    input_data: dict[str, str | int],
    *,
    instance_id: str = "test-instance-001",
    is_replaying: bool = False,
    current_utc: datetime | None = None,
) -> MagicMock:
    """Create a mock DurableOrchestrationContext."""
    context = MagicMock()
    context.get_input.return_value = input_data
    context.instance_id = instance_id
    context.is_replaying = is_replaying
    context.current_utc_datetime = current_utc or datetime(2026, 2, 17, 12, 0, 0, tzinfo=UTC)
    return context


def _run_orchestrator(
    context: MagicMock,
    *,
    features: list[dict[str, object]] | None = None,
    aois: list[dict[str, object]] | None = None,
    metadata_results: list[dict[str, object]] | None = None,
    acquisition_results: list[dict[str, object]] | None = None,
    poll_results: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Drive the five-phase generator orchestrator to completion.

    Args:
        context: Mock DurableOrchestrationContext.
        features: Simulated return of ``parse_kml`` activity.
        aois: Simulated return of ``prepare_aoi`` fan-out.
        metadata_results: Simulated return of ``write_metadata`` fan-out.
        acquisition_results: Simulated return of ``acquire_imagery`` fan-out.
        poll_results: Simulated returns of ``poll_order`` activity calls
            (one per acquisition).  Each should have ``is_terminal: True``
            so the loop exits after one poll.

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
    if acquisition_results is None:
        acquisition_results = [
            {
                "order_id": f"pc-scene-{i}",
                "scene_id": f"scene-{i}",
                "provider": "planetary_computer",
                "aoi_feature_name": f"aoi-{i}",
            }
            for i in range(len(aois))
        ]
    if poll_results is None:
        poll_results = [
            {
                "state": "ready",
                "is_terminal": True,
                "order_id": a["order_id"],
                "message": "",
                "progress_pct": 100.0,
            }
            for a in acquisition_results
        ]

    gen = orchestrator_function(context)
    next(gen)  # → yield parse_kml
    gen.send(features)  # → yield task_all(prepare_aoi)
    gen.send(aois)  # → yield task_all(write_metadata)
    gen.send(metadata_results)  # → yield task_all(acquire_imagery)

    # Now we enter the polling loop for each acquisition.
    # For each acquisition the orchestrator yields:
    #   1. call_activity("poll_order", ...) — send poll result
    #   2. If terminal → moves to next acquisition
    #   3. If not terminal → create_timer → then poll again
    # With default poll_results (all terminal), each result → next acq.
    # When acquisition_results is empty, no polling happens and the
    # generator returns immediately (StopIteration).
    try:
        gen.send(acquisition_results)  # → first poll_order yield
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]

    poll_idx = 0
    while True:
        try:
            if poll_idx < len(poll_results):
                gen.send(poll_results[poll_idx])
                poll_idx += 1
            else:
                gen.send(None)
        except StopIteration as exc:
            return exc.value  # type: ignore[return-value]

    msg = "Orchestrator did not return"  # pragma: no cover
    raise RuntimeError(msg)  # pragma: no cover


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


# ===========================================================================
# Orchestrator integration tests
# ===========================================================================


class TestOrchestratorFunction:
    """Verify the orchestrator across all five phases."""

    def test_returns_imagery_acquired_status(self) -> None:
        """Orchestrator returns 'imagery_acquired' when all polls ready."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        assert result["status"] == "imagery_acquired"

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

    def test_replay_mode_works(self) -> None:
        """During replay (is_replaying=True), orchestrator still works."""
        context = _make_context(_sample_blob_event(), is_replaying=True)
        result = _run_orchestrator(context)
        assert result["status"] == "imagery_acquired"

    def test_calls_parse_kml_activity(self) -> None:
        """Orchestrator calls parse_kml activity with the blob event."""
        event = _sample_blob_event()
        context = _make_context(event)
        _run_orchestrator(context)
        context.call_activity.assert_any_call("parse_kml", event)

    def test_feature_count_in_result(self) -> None:
        """Result includes counts of features, AOIs, and metadata records."""
        context = _make_context(_sample_blob_event())
        feats = [{"name": "f1"}, {"name": "f2"}, {"name": "f3"}]
        aois = [{"feature_name": "a1"}, {"feature_name": "a2"}, {"feature_name": "a3"}]
        meta = [{"metadata_path": "p1"}, {"metadata_path": "p2"}, {"metadata_path": "p3"}]
        result = _run_orchestrator(context, features=feats, aois=aois, metadata_results=meta)
        assert result["feature_count"] == 3
        assert result["aoi_count"] == 3
        assert result["metadata_count"] == 3

    def test_imagery_ready_count(self) -> None:
        """Result tracks how many orders completed as ready."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}, {"name": "f2"}],
            aois=[{"feature_name": "a1"}, {"feature_name": "a2"}],
        )
        assert result["imagery_ready"] == 2
        assert result["imagery_failed"] == 0

    def test_message_includes_imagery_counts(self) -> None:
        """Result message mentions imagery ready/failed counts."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        assert "imagery ready=1" in result["message"]
        assert "failed=0" in result["message"]

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

    def test_calls_acquire_imagery_per_aoi(self) -> None:
        """Orchestrator calls acquire_imagery for each AOI."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        acq_calls = [
            c for c in context.call_activity.call_args_list if c[0][0] == "acquire_imagery"
        ]
        assert len(acq_calls) == 1
        assert acq_calls[0][0][1]["aoi"] == {"feature_name": "a1"}

    def test_calls_poll_order_per_acquisition(self) -> None:
        """Orchestrator calls poll_order at least once per acquisition."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        poll_calls = [c for c in context.call_activity.call_args_list if c[0][0] == "poll_order"]
        assert len(poll_calls) == 1

    def test_write_metadata_called_with_aois(self) -> None:
        """Orchestrator calls write_metadata for each AOI."""
        context = _make_context(_sample_blob_event(), instance_id="inst-99")
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        calls = [c for c in context.call_activity.call_args_list if c[0][0] == "write_metadata"]
        assert len(calls) == 1
        payload = calls[0][0][1]
        assert payload["aoi"] == {"feature_name": "a1"}
        assert payload["processing_id"] == "inst-99"

    def test_partial_imagery_status_on_failure(self) -> None:
        """If any poll returns failed, status is partial_imagery."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            poll_results=[
                {
                    "state": "failed",
                    "is_terminal": True,
                    "order_id": "pc-scene-0",
                    "message": "Rejected",
                    "progress_pct": 0.0,
                }
            ],
        )
        assert result["status"] == "partial_imagery"
        assert result["imagery_failed"] == 1
        assert result["imagery_ready"] == 0

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


# ===========================================================================
# _poll_until_ready sub-orchestrator tests
# ===========================================================================


class TestPollUntilReady:
    """Test the timer-based polling sub-orchestration."""

    def _run_poll(
        self,
        context: MagicMock,
        acquisition: dict[str, object],
        poll_responses: list[dict[str, object] | Exception | None],
        **kwargs: int,
    ) -> dict[str, object]:
        """Drive ``_poll_until_ready`` with a sequence of poll responses.

        Entries in *poll_responses*:
        - ``dict`` → sent as the result of ``poll_order`` activity
        - ``Exception`` → thrown into the generator (simulated activity failure)
        - ``None`` → sent as ``None`` (timer acknowledgement)
        """
        gen = _poll_until_ready(context, acquisition, **kwargs)  # type: ignore[arg-type]
        next(gen)

        resp_idx = 0
        while True:
            try:
                if resp_idx < len(poll_responses):
                    resp = poll_responses[resp_idx]
                    resp_idx += 1
                    if isinstance(resp, Exception):
                        gen.throw(resp)
                    else:
                        gen.send(resp)
                else:
                    gen.send(None)
            except StopIteration as exc:
                return exc.value  # type: ignore[return-value]

    def _make_acq(self, order_id: str = "pc-SCENE") -> dict[str, str]:
        return {
            "order_id": order_id,
            "scene_id": "SCENE",
            "provider": "planetary_computer",
            "aoi_feature_name": "Block A",
        }

    def test_immediate_ready(self) -> None:
        """Poll returns READY on first call → no timer needed."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq(),
            [
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                }
            ],
        )
        assert result["state"] == "ready"
        assert result["poll_count"] == 1
        assert result["error"] == ""

    def test_pending_then_ready(self) -> None:
        """Poll returns PENDING → timer → READY."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq(),
            [
                {
                    "state": "pending",
                    "is_terminal": False,
                    "message": "Processing",
                    "progress_pct": 50.0,
                },
                None,  # timer yield — send None
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                },
            ],
        )
        assert result["state"] == "ready"
        assert result["poll_count"] == 2

    def test_failed_order(self) -> None:
        """Provider returns FAILED → terminal, error recorded."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq(),
            [
                {
                    "state": "failed",
                    "is_terminal": True,
                    "message": "Rejected",
                    "progress_pct": 0.0,
                }
            ],
        )
        assert result["state"] == "failed"
        assert result["error"] == "Rejected"

    def test_retry_on_transient_error(self) -> None:
        """Transient error → backoff timer → retry → READY."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq(),
            [
                RuntimeError("API timeout"),  # error → retry 1
                None,  # backoff timer
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                },
            ],
            max_retries=3,
            retry_base=5,
        )
        assert result["state"] == "ready"
        assert result["poll_count"] == 2

    def test_retries_exhausted(self) -> None:
        """All retries exhausted → failed state."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq(),
            [
                RuntimeError("err1"),  # retry 1
                None,  # backoff timer
                RuntimeError("err2"),  # retry 2
                None,  # backoff timer
                RuntimeError("err3"),  # retry 3
                None,  # backoff timer
                RuntimeError("err4"),  # retry 4 → exceeds max_retries=3
            ],
            max_retries=3,
            retry_base=5,
        )
        assert result["state"] == "failed"
        assert "retries exhausted" in result["error"]

    def test_timeout(self) -> None:
        """Polling past deadline → acquisition_timeout."""
        base_time = datetime(2026, 2, 17, 12, 0, 0, tzinfo=UTC)
        context = _make_context({}, current_utc=base_time)

        # After the first pending poll + timer, advance time past deadline.
        # _poll_until_ready computes deadline = current + timeout.
        # We yield pending, then timer, then on the next loop iteration
        # current_utc_datetime > deadline → timeout.
        def _run_poll_with_time_advance(
            ctx: MagicMock,
            acq: dict[str, object],
            **kw: int,
        ) -> dict[str, object]:
            gen = _poll_until_ready(ctx, acq, **kw)  # type: ignore[arg-type]
            next(gen)  # first poll_order yield

            # Send pending result → timer yield
            gen.send(
                {
                    "state": "pending",
                    "is_terminal": False,
                    "message": "Processing",
                    "progress_pct": 10.0,
                }
            )

            # Advance time past deadline before sending timer result
            ctx.current_utc_datetime = base_time + timedelta(seconds=9999)
            try:
                gen.send(None)  # timer ack → re-enters while loop → timeout
            except StopIteration as exc:
                return exc.value  # type: ignore[return-value]

            msg = "Expected StopIteration"  # pragma: no cover
            raise RuntimeError(msg)  # pragma: no cover

        result = _run_poll_with_time_advance(
            context,
            self._make_acq(),
            poll_timeout=60,
        )
        assert result["state"] == "acquisition_timeout"
        assert "timed out" in result["error"]

    def test_creates_timer_between_polls(self) -> None:
        """Timer is created between non-terminal polls."""
        context = _make_context({})
        self._run_poll(
            context,
            self._make_acq(),
            [
                {
                    "state": "pending",
                    "is_terminal": False,
                    "message": "Processing",
                    "progress_pct": 50.0,
                },
                None,  # timer yield
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                },
            ],
        )
        context.create_timer.assert_called_once()

    def test_backoff_timer_on_error(self) -> None:
        """Error triggers a backoff timer before retrying."""
        context = _make_context({})
        self._run_poll(
            context,
            self._make_acq(),
            [
                RuntimeError("err"),
                None,  # backoff timer
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                },
            ],
            retry_base=10,
        )
        timer_calls = context.create_timer.call_args_list
        assert len(timer_calls) == 1

    def test_result_includes_metadata(self) -> None:
        """Result includes order_id, scene_id, provider, feature_name."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq("pc-MY_SCENE"),
            [
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                }
            ],
        )
        assert result["order_id"] == "pc-MY_SCENE"
        assert result["scene_id"] == "SCENE"
        assert result["provider"] == "planetary_computer"
        assert result["aoi_feature_name"] == "Block A"

    def test_cancelled_is_terminal(self) -> None:
        """CANCELLED state is treated as terminal."""
        context = _make_context({})
        result = self._run_poll(
            context,
            self._make_acq(),
            [
                {
                    "state": "cancelled",
                    "is_terminal": True,
                    "message": "User cancelled",
                    "progress_pct": 0.0,
                }
            ],
        )
        assert result["state"] == "cancelled"
        assert result["error"] == "User cancelled"


# ===========================================================================
# Polling defaults exported
# ===========================================================================


class TestPollingDefaults:
    """Verify exported default constants."""

    def test_default_poll_interval(self) -> None:
        assert DEFAULT_POLL_INTERVAL_SECONDS == 30

    def test_default_poll_timeout(self) -> None:
        assert DEFAULT_POLL_TIMEOUT_SECONDS == 1800

    def test_default_max_retries(self) -> None:
        assert DEFAULT_MAX_RETRIES == 3

    def test_default_retry_base(self) -> None:
        assert DEFAULT_RETRY_BASE_SECONDS == 5
