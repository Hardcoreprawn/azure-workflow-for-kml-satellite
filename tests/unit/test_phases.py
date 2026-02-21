"""Tests for the decomposed orchestrator phases module.

Verifies each phase generator independently and the pipeline summary
builder.  Uses the same mock-context pattern as ``test_orchestrator.py``.

References:
    Issue #59  (Decompose pipeline orchestration)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from kml_satellite.orchestrators.phases import (
    AcquisitionResult,
    FulfillmentResult,
    IngestionResult,
    _poll_until_ready,
    build_pipeline_summary,
    run_acquisition_phase,
    run_fulfillment_phase,
    run_ingestion_phase,
)


def _make_context(
    *,
    instance_id: str = "test-instance-001",
    is_replaying: bool = False,
    current_utc: datetime | None = None,
) -> MagicMock:
    """Create a mock DurableOrchestrationContext."""
    ctx = MagicMock()
    ctx.instance_id = instance_id
    ctx.is_replaying = is_replaying
    ctx.current_utc_datetime = current_utc or datetime(2026, 2, 17, 12, 0, 0, tzinfo=UTC)
    return ctx


def _sample_blob_event() -> dict[str, Any]:
    return {
        "blob_url": "https://stkmlsatdev.blob.core.windows.net/kml-input/orchard.kml",
        "container_name": "kml-input",
        "blob_name": "orchard.kml",
        "content_length": 2048,
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": "2026-02-15T12:00:00",
        "correlation_id": "evt-abc-123",
    }


# ===================================================================
# Ingestion phase tests
# ===================================================================


class TestIngestionPhase:
    """Tests for run_ingestion_phase generator."""

    def _run_ingestion(
        self,
        context: MagicMock,
        blob_event: dict[str, object],
        *,
        features: list[dict[str, object]] | None = None,
        aois: list[dict[str, object]] | None = None,
        metadata_results: list[dict[str, object]] | None = None,
    ) -> IngestionResult:
        if features is None:
            features = [{"name": "f1"}]
        if aois is None:
            aois = [{"feature_name": "a1"}]
        if metadata_results is None:
            metadata_results = [{"metadata_path": "p1"}]

        gen = run_ingestion_phase(
            context,
            blob_event,
            timestamp="2026-02-17T12:00:00+00:00",
            instance_id=context.instance_id,
            blob_name=str(blob_event.get("blob_name", "")),
        )
        next(gen)  # yield parse_kml
        gen.send(features)  # yield task_all(prepare_aoi)
        gen.send(aois)  # yield task_all(write_metadata)
        try:
            gen.send(metadata_results)
        except StopIteration as exc:
            return exc.value  # type: ignore[return-value]
        msg = "Expected StopIteration"
        raise RuntimeError(msg)

    def test_returns_feature_count(self) -> None:
        ctx = _make_context()
        result = self._run_ingestion(ctx, _sample_blob_event())
        assert result["feature_count"] == 1

    def test_returns_aoi_count(self) -> None:
        ctx = _make_context()
        result = self._run_ingestion(
            ctx,
            _sample_blob_event(),
            features=[{"name": "f1"}, {"name": "f2"}],
            aois=[{"feature_name": "a1"}, {"feature_name": "a2"}],
        )
        assert result["aoi_count"] == 2

    def test_returns_metadata_count(self) -> None:
        ctx = _make_context()
        result = self._run_ingestion(ctx, _sample_blob_event())
        assert result["metadata_count"] == 1

    def test_offloaded_false_for_list(self) -> None:
        ctx = _make_context()
        result = self._run_ingestion(ctx, _sample_blob_event())
        assert result["offloaded"] is False

    def test_offloaded_true_for_ref(self) -> None:
        ctx = _make_context()
        ref: dict[str, object] = {
            "__payload_offloaded__": True,
            "container": "kml-payloads",
            "blob_path": "payloads/x/features.json",
            "count": 2,
            "size_bytes": 100000,
        }
        gen = run_ingestion_phase(
            ctx,
            _sample_blob_event(),
            timestamp="2026-02-17T12:00:00+00:00",
            instance_id="test",
        )
        next(gen)  # yield parse_kml
        gen.send(ref)  # yield task_all(prepare_aoi) — 2 ref inputs
        gen.send([{"feature_name": "a1"}, {"feature_name": "a2"}])  # task_all(write_metadata)
        try:
            gen.send([{"metadata_path": "p1"}, {"metadata_path": "p2"}])
        except StopIteration as exc:
            result: IngestionResult = exc.value
        else:
            raise AssertionError("Expected StopIteration")
        assert result["offloaded"] is True
        assert result["feature_count"] == 2

    def test_aois_populated(self) -> None:
        ctx = _make_context()
        aois: list[dict[str, object]] = [{"feature_name": "block-a"}]
        result = self._run_ingestion(ctx, _sample_blob_event(), aois=aois)
        assert result["aois"] == aois

    def test_metadata_results_populated(self) -> None:
        ctx = _make_context()
        meta: list[dict[str, object]] = [{"metadata_path": "test.json"}]
        result = self._run_ingestion(ctx, _sample_blob_event(), metadata_results=meta)
        assert result["metadata_results"] == meta

    def test_calls_parse_kml_with_blob_event(self) -> None:
        ctx = _make_context()
        event = _sample_blob_event()
        self._run_ingestion(ctx, event)
        ctx.call_activity.assert_any_call("parse_kml", event)

    def test_calls_write_metadata_with_processing_id(self) -> None:
        ctx = _make_context(instance_id="inst-42")
        self._run_ingestion(ctx, _sample_blob_event())
        calls = [c for c in ctx.call_activity.call_args_list if c[0][0] == "write_metadata"]
        assert len(calls) == 1
        assert calls[0][0][1]["processing_id"] == "inst-42"


# ===================================================================
# Acquisition phase tests
# ===================================================================


class TestAcquisitionPhase:
    """Tests for run_acquisition_phase generator."""

    def _run_acquisition(
        self,
        context: MagicMock,
        aois: list[dict[str, Any]],
        *,
        acquisition_results: list[dict[str, object]] | None = None,
        poll_outcomes: list[dict[str, object]] | None = None,
        blob_event: dict[str, Any] | None = None,
    ) -> AcquisitionResult:
        if blob_event is None:
            blob_event = _sample_blob_event()
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

        gen = run_acquisition_phase(
            context,
            aois,
            blob_event=blob_event,
            instance_id=context.instance_id,
            blob_name=str(blob_event.get("blob_name", "")),
        )
        next(gen)  # yield task_all(acquire_imagery)
        gen.send(acquisition_results)  # yield task_all(sub-orchestrator polls)
        try:
            gen.send(poll_outcomes)
        except StopIteration as exc:
            return exc.value  # type: ignore[return-value]
        msg = "Expected StopIteration"
        raise RuntimeError(msg)

    def test_all_ready(self) -> None:
        ctx = _make_context()
        result = self._run_acquisition(ctx, [{"feature_name": "a1"}])
        assert result["ready_count"] == 1
        assert result["failed_count"] == 0

    def test_one_failed(self) -> None:
        ctx = _make_context()
        result = self._run_acquisition(
            ctx,
            [{"feature_name": "a1"}],
            poll_outcomes=[
                {
                    "state": "failed",
                    "order_id": "pc-scene-0",
                    "error": "Rejected",
                }
            ],
        )
        assert result["ready_count"] == 0
        assert result["failed_count"] == 1

    def test_imagery_outcomes_populated(self) -> None:
        ctx = _make_context()
        result = self._run_acquisition(
            ctx,
            [{"feature_name": "a1"}, {"feature_name": "a2"}],
        )
        assert len(result["imagery_outcomes"]) == 2

    def test_calls_acquire_imagery_per_aoi(self) -> None:
        ctx = _make_context()
        self._run_acquisition(
            ctx,
            [{"feature_name": "a1"}, {"feature_name": "a2"}],
        )
        acq_calls = [c for c in ctx.call_activity.call_args_list if c[0][0] == "acquire_imagery"]
        assert len(acq_calls) == 2

    def test_calls_sub_orchestrator_per_acquisition(self) -> None:
        ctx = _make_context()
        self._run_acquisition(ctx, [{"feature_name": "a1"}])
        sub_calls = ctx.call_sub_orchestrator.call_args_list
        assert len(sub_calls) == 1
        assert sub_calls[0][0][0] == "poll_order_suborchestrator"


# ===================================================================
# Fulfillment phase tests
# ===================================================================


class TestFulfillmentPhase:
    """Tests for run_fulfillment_phase generator (parallel batches)."""

    def _run_fulfillment(
        self,
        context: MagicMock,
        ready_outcomes: list[dict[str, Any]],
        aois: list[dict[str, Any]],
        *,
        download_results: list[dict[str, Any]] | None = None,
        post_process_results: list[dict[str, Any]] | None = None,
        instance_id: str = "",
        blob_name: str = "orchard.kml",
    ) -> FulfillmentResult:
        if download_results is None:
            download_results = [
                {
                    "order_id": o.get("order_id", f"order-{i}"),
                    "aoi_feature_name": o.get("aoi_feature_name", f"aoi-{i}"),
                    "blob_path": f"imagery/raw/2026/02/test/aoi-{i}.tif",
                    "size_bytes": 1024,
                }
                for i, o in enumerate(ready_outcomes)
            ]
        successful_downloads = [d for d in download_results if d.get("state") != "failed"]
        if post_process_results is None:
            post_process_results = [
                {
                    "order_id": d.get("order_id", f"order-{i}"),
                    "clipped": True,
                    "reprojected": False,
                    "clipped_blob_path": f"imagery/clipped/2026/02/test/aoi-{i}.tif",
                }
                for i, d in enumerate(successful_downloads)
            ]

        gen = run_fulfillment_phase(
            context,
            ready_outcomes,
            aois,
            provider_name="planetary_computer",
            provider_config=None,
            project_name="test-orchard",
            timestamp="2026-02-17T12:00:00+00:00",
            instance_id=instance_id or context.instance_id,
            blob_name=blob_name,
        )

        # No ready outcomes → no yields at all
        if not ready_outcomes:
            try:
                next(gen)
            except StopIteration as exc:
                return exc.value  # type: ignore[return-value]

        # First yield: task_all(download batch)
        try:
            next(gen)
        except StopIteration as exc:
            return exc.value  # type: ignore[return-value]

        # Send download results as a batch list
        if not successful_downloads:
            try:
                gen.send(download_results)
            except StopIteration as exc:
                return exc.value  # type: ignore[return-value]
        else:
            gen.send(download_results)
            # Send post-process results as a batch list
            try:
                gen.send(post_process_results)
            except StopIteration as exc:
                return exc.value  # type: ignore[return-value]

        msg = "Expected StopIteration"
        raise RuntimeError(msg)

    def test_all_successful(self) -> None:
        ctx = _make_context()
        outcomes: list[dict[str, Any]] = [
            {"order_id": "o1", "aoi_feature_name": "a1", "state": "ready"},
        ]
        aois: list[dict[str, Any]] = [{"feature_name": "a1"}]
        result = self._run_fulfillment(ctx, outcomes, aois)
        assert result["downloads_completed"] == 1
        assert result["downloads_failed"] == 0
        assert result["pp_clipped"] == 1

    def test_download_failure_captured(self) -> None:
        ctx = _make_context()
        outcomes: list[dict[str, Any]] = [
            {"order_id": "o1", "aoi_feature_name": "a1", "state": "ready"},
        ]
        aois: list[dict[str, Any]] = [{"feature_name": "a1"}]

        gen = run_fulfillment_phase(
            ctx,
            outcomes,
            aois,
            provider_name="planetary_computer",
            provider_config=None,
            project_name="test",
            timestamp="2026-02-17T12:00:00+00:00",
        )
        next(gen)  # download batch yield
        try:
            gen.throw(RuntimeError("Download failed"))
        except StopIteration as exc:
            result: FulfillmentResult = exc.value
        else:
            raise AssertionError("Expected StopIteration")

        assert result["downloads_completed"] == 1
        assert result["downloads_failed"] == 1
        assert result["pp_completed"] == 0

    def test_no_downloads_for_empty_outcomes(self) -> None:
        ctx = _make_context()
        gen = run_fulfillment_phase(
            ctx,
            [],
            [],
            provider_name="pc",
            provider_config=None,
            project_name="test",
            timestamp="2026-02-17T12:00:00+00:00",
        )
        try:
            next(gen)
        except StopIteration as exc:
            result: FulfillmentResult = exc.value
        else:
            raise AssertionError("Expected StopIteration")

        assert result["downloads_completed"] == 0
        assert result["pp_completed"] == 0

    def test_post_process_failure_captured(self) -> None:
        ctx = _make_context()
        outcomes: list[dict[str, Any]] = [
            {"order_id": "o1", "aoi_feature_name": "a1", "state": "ready"},
        ]
        aois: list[dict[str, Any]] = [{"feature_name": "a1"}]
        dl_results: list[dict[str, Any]] = [
            {"order_id": "o1", "aoi_feature_name": "a1", "blob_path": "test.tif"},
        ]

        gen = run_fulfillment_phase(
            ctx,
            outcomes,
            aois,
            provider_name="pc",
            provider_config=None,
            project_name="test",
            timestamp="2026-02-17T12:00:00+00:00",
        )
        next(gen)  # download batch yield
        gen.send(dl_results)  # post-process batch yield
        try:
            gen.throw(RuntimeError("Clip failed"))
        except StopIteration as exc:
            result: FulfillmentResult = exc.value
        else:
            raise AssertionError("Expected StopIteration")

        assert result["downloads_completed"] == 1
        assert result["downloads_failed"] == 0
        assert result["pp_completed"] == 1
        assert result["pp_failed"] == 1

    def test_matching_aoi_passed_to_post_process(self) -> None:
        ctx = _make_context()
        outcomes: list[dict[str, Any]] = [
            {"order_id": "o1", "aoi_feature_name": "block-a", "state": "ready"},
        ]
        aois: list[dict[str, Any]] = [
            {"feature_name": "block-a", "exterior_coords": [[0, 0], [1, 0], [1, 1], [0, 0]]},
        ]
        self._run_fulfillment(ctx, outcomes, aois)

        pp_calls = [
            c for c in ctx.call_activity.call_args_list if c[0][0] == "post_process_imagery"
        ]
        assert len(pp_calls) == 1
        assert pp_calls[0][0][1]["aoi"]["feature_name"] == "block-a"


# ===================================================================
# Pipeline summary builder tests
# ===================================================================


class TestBuildPipelineSummary:
    """Tests for build_pipeline_summary function."""

    def _make_ingestion(self, **overrides: Any) -> IngestionResult:
        base: IngestionResult = {
            "feature_count": 2,
            "offloaded": False,
            "aois": [{"feature_name": "a1"}, {"feature_name": "a2"}],
            "aoi_count": 2,
            "metadata_results": [{"p": 1}, {"p": 2}],
            "metadata_count": 2,
        }
        base.update(overrides)  # type: ignore[typeddict-item]
        return base

    def _make_acquisition(self, **overrides: Any) -> AcquisitionResult:
        base: AcquisitionResult = {
            "imagery_outcomes": [
                {"state": "ready", "order_id": "o1"},
                {"state": "ready", "order_id": "o2"},
            ],
            "ready_count": 2,
            "failed_count": 0,
        }
        base.update(overrides)  # type: ignore[typeddict-item]
        return base

    def _make_fulfillment(self, **overrides: Any) -> FulfillmentResult:
        base: FulfillmentResult = {
            "download_results": [{"order_id": "o1"}, {"order_id": "o2"}],
            "downloads_completed": 2,
            "downloads_succeeded": 2,
            "downloads_failed": 0,
            "post_process_results": [
                {"order_id": "o1", "clipped": True, "reprojected": False},
                {"order_id": "o2", "clipped": True, "reprojected": True},
            ],
            "pp_completed": 2,
            "pp_clipped": 2,
            "pp_reprojected": 1,
            "pp_failed": 0,
        }
        base.update(overrides)  # type: ignore[typeddict-item]
        return base

    def test_completed_status(self) -> None:
        result = build_pipeline_summary(
            self._make_ingestion(),
            self._make_acquisition(),
            self._make_fulfillment(),
            instance_id="inst-1",
            blob_event=_sample_blob_event(),
        )
        assert result["status"] == "completed"

    def test_partial_imagery_on_acquisition_failure(self) -> None:
        result = build_pipeline_summary(
            self._make_ingestion(),
            self._make_acquisition(ready_count=1, failed_count=1),
            self._make_fulfillment(downloads_completed=1, downloads_succeeded=1),
            instance_id="inst-1",
            blob_event=_sample_blob_event(),
        )
        assert result["status"] == "partial_imagery"

    def test_partial_imagery_on_download_failure(self) -> None:
        result = build_pipeline_summary(
            self._make_ingestion(),
            self._make_acquisition(),
            self._make_fulfillment(downloads_failed=1, downloads_succeeded=1),
            instance_id="inst-1",
            blob_event=_sample_blob_event(),
        )
        assert result["status"] == "partial_imagery"

    def test_partial_imagery_on_pp_failure(self) -> None:
        result = build_pipeline_summary(
            self._make_ingestion(),
            self._make_acquisition(),
            self._make_fulfillment(pp_failed=1),
            instance_id="inst-1",
            blob_event=_sample_blob_event(),
        )
        assert result["status"] == "partial_imagery"

    def test_includes_blob_info(self) -> None:
        event = _sample_blob_event()
        result = build_pipeline_summary(
            self._make_ingestion(),
            self._make_acquisition(),
            self._make_fulfillment(),
            instance_id="inst-1",
            blob_event=event,
        )
        assert result["blob_name"] == "orchard.kml"
        assert result["blob_url"] == event["blob_url"]
        assert result["instance_id"] == "inst-1"

    def test_message_contains_counts(self) -> None:
        result = build_pipeline_summary(
            self._make_ingestion(feature_count=3, aoi_count=3, metadata_count=3),
            self._make_acquisition(ready_count=3, failed_count=0),
            self._make_fulfillment(downloads_completed=3, pp_clipped=2, pp_reprojected=1),
            instance_id="inst-1",
            blob_event=_sample_blob_event(),
        )
        msg = str(result["message"])
        assert "3 feature(s)" in msg
        assert "3 AOI(s)" in msg
        assert "3 metadata record(s)" in msg
        assert "ready=3" in msg
        assert "downloaded=3" in msg
        assert "clipped=2" in msg
        assert "reprojected=1" in msg

    def test_counts_propagated(self) -> None:
        result = build_pipeline_summary(
            self._make_ingestion(feature_count=5, aoi_count=5, metadata_count=5),
            self._make_acquisition(ready_count=4, failed_count=1),
            self._make_fulfillment(
                downloads_completed=4,
                pp_completed=4,
                pp_clipped=3,
                pp_reprojected=2,
            ),
            instance_id="inst-1",
            blob_event=_sample_blob_event(),
        )
        assert result["feature_count"] == 5
        assert result["aoi_count"] == 5
        assert result["metadata_count"] == 5
        assert result["imagery_ready"] == 4
        assert result["imagery_failed"] == 1
        assert result["downloads_completed"] == 4
        assert result["post_process_completed"] == 4
        assert result["post_process_clipped"] == 3
        assert result["post_process_reprojected"] == 2


# ===================================================================
# Backward compatibility: _poll_until_ready accessible from phases
# ===================================================================


class TestPollUntilReadyInPhases:
    """Verify _poll_until_ready is importable from phases module."""

    def test_importable(self) -> None:
        assert callable(_poll_until_ready)

    def test_immediate_ready(self) -> None:
        ctx = _make_context()
        acq: dict[str, object] = {
            "order_id": "o1",
            "scene_id": "s1",
            "provider": "pc",
            "aoi_feature_name": "f1",
        }
        gen = _poll_until_ready(ctx, acq)
        next(gen)
        try:
            gen.send(
                {
                    "state": "ready",
                    "is_terminal": True,
                    "message": "",
                    "progress_pct": 100.0,
                }
            )
        except StopIteration as exc:
            result: dict[str, Any] = exc.value
        else:
            raise AssertionError("Expected StopIteration")
        assert result["state"] == "ready"


# ===================================================================
# Phase contract TypedDict key verification
# ===================================================================


class TestPhaseContracts:
    """Verify that phase result TypedDicts have expected keys."""

    def test_ingestion_result_keys(self) -> None:
        expected = {
            "feature_count",
            "offloaded",
            "aois",
            "aoi_count",
            "metadata_results",
            "metadata_count",
        }
        assert set(IngestionResult.__annotations__) == expected

    def test_acquisition_result_keys(self) -> None:
        expected = {"imagery_outcomes", "ready_count", "failed_count"}
        assert set(AcquisitionResult.__annotations__) == expected

    def test_fulfillment_result_keys(self) -> None:
        expected = {
            "download_results",
            "downloads_completed",
            "downloads_succeeded",
            "downloads_failed",
            "post_process_results",
            "pp_completed",
            "pp_clipped",
            "pp_reprojected",
            "pp_failed",
        }
        assert set(FulfillmentResult.__annotations__) == expected
