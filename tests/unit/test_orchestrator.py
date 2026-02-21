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
5. poll_order — concurrent sub-orchestrators via task_all (Issue #55)
6. download_imagery — parallel batches via task_all (Issue #54)
7. post_process_imagery — parallel batches via task_all (Issue #54)

References:
    PID FR-3.9  (poll until completion with timeout)
    PID FR-3.10 (download imagery upon completion)
    PID FR-3.11 (reproject if CRS differs)
    PID FR-3.12 (clip to AOI polygon boundary)
    PID FR-4.2  (store raw imagery under /imagery/raw/)
    PID FR-4.3  (store clipped imagery under /imagery/clipped/)
    PID FR-5.3  (Durable Functions for long-running workflows)
    PID FR-6.4  (exponential backoff)
    PID Section 7.2 (Fan-Out / Fan-In pattern)
    Issue #54   (Parallelize download and post-process stages)
    Issue #55   (Make polling stage concurrency-aware)
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
    poll_outcomes: list[dict[str, object]] | None = None,
    download_results: list[dict[str, object]] | None = None,
    post_process_results: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Drive the orchestrator generator to completion.

    Phases are now parallelised (Issues #54, #55):
    - Polling uses sub-orchestrators via ``task_all`` (one batch)
    - Downloads use ``task_all`` (one batch)
    - Post-processing uses ``task_all`` (one batch)

    Args:
        context: Mock DurableOrchestrationContext.
        features: Simulated return of ``parse_kml`` activity.
        aois: Simulated return of ``prepare_aoi`` fan-out.
        metadata_results: Simulated return of ``write_metadata`` fan-out.
        acquisition_results: Simulated return of ``acquire_imagery`` fan-out.
        poll_outcomes: Simulated return of sub-orchestrator poll tasks.
            Each should have ``state`` (``"ready"`` or ``"failed"``).
        download_results: Simulated return of ``download_imagery`` batch.
        post_process_results: Simulated return of ``post_process_imagery`` batch.

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
    if poll_outcomes is None:
        poll_outcomes = [
            {
                "state": "ready",
                "order_id": a["order_id"],
                "scene_id": str(a.get("scene_id", "")),
                "provider": str(a.get("provider", "")),
                "aoi_feature_name": str(a.get("aoi_feature_name", "")),
                "poll_count": 1,
                "elapsed_seconds": 0.0,
                "error": "",
            }
            for a in acquisition_results
        ]

    # Count how many polls are "ready" to determine download fan-out size
    ready_count = sum(1 for p in poll_outcomes if p.get("state") == "ready")
    if download_results is None:
        download_results = [
            {
                "order_id": f"pc-scene-{i}",
                "aoi_feature_name": f"aoi-{i}",
                "blob_path": f"imagery/raw/2026/02/test/aoi-{i}.tif",
                "size_bytes": 1024,
                "download_duration_seconds": 0.5,
                "retry_count": 0,
            }
            for i in range(ready_count)
        ]

    # Successful downloads (not state="failed") determine post-process count
    successful_downloads = [d for d in download_results if d.get("state") != "failed"]
    if post_process_results is None:
        post_process_results = [
            {
                "order_id": d.get("order_id", f"pc-scene-{i}"),
                "clipped": True,
                "reprojected": False,
                "source_crs": "EPSG:4326",
                "clipped_blob_path": f"imagery/clipped/2026/02/test/aoi-{i}.tif",
                "output_size_bytes": 512,
                "clip_error": "",
            }
            for i, d in enumerate(successful_downloads)
        ]

    gen = orchestrator_function(context)
    next(gen)  # → yield parse_kml
    gen.send(features)  # → yield task_all(prepare_aoi)
    gen.send(aois)  # → yield task_all(write_metadata)
    gen.send(metadata_results)  # → yield task_all(acquire_imagery)

    # Acquisition results → sub-orchestrator poll batch
    try:
        gen.send(acquisition_results)
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]

    # Poll outcomes (list from task_all of sub-orchestrators)
    try:
        gen.send(poll_outcomes)
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]

    # Download results batch (task_all)
    try:
        gen.send(download_results)
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]

    # Post-process results batch (task_all) — generator finishes here
    try:
        gen.send(post_process_results)
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]

    raise RuntimeError("Expected StopIteration")  # pragma: no cover


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
        "tenant_id": "tenant-orch-001",
    }


# ===========================================================================
# Orchestrator integration tests
# ===========================================================================


class TestOrchestratorFunction:
    """Verify the orchestrator across all pipeline phases."""

    def test_returns_completed_status(self) -> None:
        """Orchestrator returns 'completed' when all polls ready and downloads succeed."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        assert result["status"] == "completed"

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
        assert result["status"] == "completed"

    def test_calls_parse_kml_activity(self) -> None:
        """Orchestrator calls parse_kml activity with the blob event."""
        event = _sample_blob_event()
        context = _make_context(event)
        _run_orchestrator(context)
        context.call_activity.assert_any_call("parse_kml", event)

    def test_feature_count_in_result(self) -> None:
        """Result includes counts of features, AOIs, and metadata records."""
        context = _make_context(_sample_blob_event())
        feats: list[dict[str, object]] = [{"name": "f1"}, {"name": "f2"}, {"name": "f3"}]
        aois: list[dict[str, object]] = [
            {"feature_name": "a1"},
            {"feature_name": "a2"},
            {"feature_name": "a3"},
        ]
        meta: list[dict[str, object]] = [
            {"metadata_path": "p1"},
            {"metadata_path": "p2"},
            {"metadata_path": "p3"},
        ]
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
        assert result["downloads_completed"] == 2

    def test_message_includes_imagery_counts(self) -> None:
        """Result message mentions imagery ready/failed/downloaded counts."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        msg = str(result["message"])
        assert "imagery ready=1" in msg
        assert "failed=0" in msg
        assert "downloaded=1" in msg

    def test_message_includes_metadata_count(self) -> None:
        """Result message mentions metadata records."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}, {"name": "f2"}],
            aois=[{"feature_name": "a1"}, {"feature_name": "a2"}],
            metadata_results=[{"p": 1}, {"p": 2}],
        )
        assert "2 metadata record(s)" in str(result["message"])

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

    def test_calls_poll_sub_orchestrator_per_acquisition(self) -> None:
        """Orchestrator calls poll sub-orchestrator for each acquisition (Issue #55)."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        sub_calls = context.call_sub_orchestrator.call_args_list
        assert len(sub_calls) == 1
        assert sub_calls[0][0][0] == "poll_order_suborchestrator"

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
        assert payload["tenant_id"] == "tenant-orch-001"

    def test_partial_imagery_status_on_failure(self) -> None:
        """If any poll returns failed, status is partial_imagery."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            poll_outcomes=[
                {
                    "state": "failed",
                    "order_id": "pc-scene-0",
                    "error": "Rejected",
                }
            ],
            download_results=[],
        )
        assert result["status"] == "partial_imagery"
        assert result["imagery_failed"] == 1
        assert result["imagery_ready"] == 0
        assert result["downloads_completed"] == 0

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

    def test_calls_download_imagery_per_ready_order(self) -> None:
        """Orchestrator calls download_imagery for each ready order."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        dl_calls = [
            c for c in context.call_activity.call_args_list if c[0][0] == "download_imagery"
        ]
        assert len(dl_calls) == 1
        payload = dl_calls[0][0][1]
        assert "imagery_outcome" in payload

    def test_no_download_when_all_failed(self) -> None:
        """No download_imagery calls when all polls fail."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            poll_outcomes=[
                {
                    "state": "failed",
                    "order_id": "pc-scene-0",
                    "error": "Rejected",
                }
            ],
            download_results=[],
        )
        dl_calls = [
            c for c in context.call_activity.call_args_list if c[0][0] == "download_imagery"
        ]
        assert len(dl_calls) == 0
        assert result["downloads_completed"] == 0

    def test_download_results_in_output(self) -> None:
        """Result includes download_results list."""
        context = _make_context(_sample_blob_event())
        dl_results = [
            {
                "order_id": "pc-scene-0",
                "blob_path": "imagery/raw/2026/02/test/a1.tif",
                "size_bytes": 2048,
            }
        ]
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            download_results=dl_results,
        )
        assert result["download_results"] == dl_results

    def test_download_failure_captured_not_fatal(self) -> None:
        """If a download batch raises, the error is captured in results."""
        context = _make_context(_sample_blob_event())

        gen = orchestrator_function(context)
        next(gen)  # parse_kml
        features: list[dict[str, object]] = [{"name": "f1"}]
        aois: list[dict[str, object]] = [{"feature_name": "a1"}]
        gen.send(features)  # prepare_aoi fan-out
        gen.send(aois)  # write_metadata fan-out
        gen.send([{"metadata_path": "p"}])  # acquire_imagery fan-out
        gen.send(
            [
                {
                    "order_id": "pc-scene-0",
                    "scene_id": "scene-0",
                    "provider": "planetary_computer",
                    "aoi_feature_name": "a1",
                }
            ]
        )  # sub-orchestrator poll batch
        # Send terminal-ready poll outcome → orchestrator enters download
        gen.send(
            [
                {
                    "state": "ready",
                    "order_id": "pc-scene-0",
                    "scene_id": "scene-0",
                    "provider": "planetary_computer",
                    "aoi_feature_name": "a1",
                    "poll_count": 1,
                    "elapsed_seconds": 0.0,
                    "error": "",
                }
            ]
        )  # → download batch yield (task_all)

        # Download batch yield — throw an exception to simulate failure
        try:
            gen.throw(RuntimeError("Download exploded"))
        except StopIteration as exc:
            result: dict[str, object] = exc.value
        else:
            raise AssertionError("Expected StopIteration after download failure")

        assert result["status"] == "partial_imagery"
        assert result["downloads_completed"] == 1  # captured failure counted
        dl = result["download_results"]
        assert isinstance(dl, list)
        assert len(dl) == 1
        assert dl[0]["state"] == "failed"
        assert "Download exploded" in str(dl[0]["error"])

    def test_project_name_from_blob_filename(self) -> None:
        """Orchestrator derives project_name from blob_name stem."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        dl_calls = [
            c for c in context.call_activity.call_args_list if c[0][0] == "download_imagery"
        ]
        assert len(dl_calls) == 1
        # blob_name="orchard.kml" → stem="orchard"
        assert dl_calls[0][0][1]["project_name"] == "orchard"
        # output_container should be present in the download payload
        assert dl_calls[0][0][1]["output_container"] == "kml-output"

    def test_calls_post_process_per_download(self) -> None:
        """Orchestrator calls post_process_imagery for each successful download."""
        context = _make_context(_sample_blob_event())
        _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        pp_calls = [
            c for c in context.call_activity.call_args_list if c[0][0] == "post_process_imagery"
        ]
        assert len(pp_calls) == 1
        payload = pp_calls[0][0][1]
        assert "download_result" in payload
        assert "aoi" in payload

    def test_no_post_process_when_no_downloads(self) -> None:
        """No post_process_imagery calls when all polls fail."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            poll_outcomes=[
                {
                    "state": "failed",
                    "order_id": "pc-scene-0",
                    "error": "Rejected",
                }
            ],
            download_results=[],
            post_process_results=[],
        )
        pp_calls = [
            c for c in context.call_activity.call_args_list if c[0][0] == "post_process_imagery"
        ]
        assert len(pp_calls) == 0
        assert result["post_process_completed"] == 0

    def test_post_process_results_in_output(self) -> None:
        """Result includes post_process_results list."""
        context = _make_context(_sample_blob_event())
        pp_results: list[dict[str, object]] = [
            {
                "order_id": "pc-scene-0",
                "clipped": True,
                "reprojected": False,
                "clipped_blob_path": "imagery/clipped/2026/02/test/a1.tif",
            }
        ]
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
            post_process_results=pp_results,
        )
        assert result["post_process_results"] == pp_results
        assert result["post_process_clipped"] == 1

    def test_message_includes_clip_count(self) -> None:
        """Result message mentions clipped/reprojected counts."""
        context = _make_context(_sample_blob_event())
        result = _run_orchestrator(
            context,
            features=[{"name": "f1"}],
            aois=[{"feature_name": "a1"}],
        )
        msg = str(result["message"])
        assert "clipped=1" in msg


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

    def _make_acq(self, order_id: str = "pc-SCENE") -> dict[str, object]:
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
        assert "retries exhausted" in str(result["error"])

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

            raise RuntimeError("Expected StopIteration")  # pragma: no cover

        result = _run_poll_with_time_advance(
            context,
            self._make_acq(),
            poll_timeout=60,
        )
        assert result["state"] == "acquisition_timeout"
        assert "timed out" in str(result["error"])

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
