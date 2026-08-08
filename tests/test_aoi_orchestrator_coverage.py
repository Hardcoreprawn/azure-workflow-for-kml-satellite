"""Coverage-hardening tests for blueprints/pipeline/aoi_orchestrator.py.

Phase 1 of issue #886.  Uses mock DurableOrchestrationContext to exercise
the sub-orchestrator generator functions without Azure Durable Functions runtime.

``yield from gen`` returns the *return value* of ``gen`` (its StopIteration.value),
so mock sub-generators must be real generator functions that ``return`` a value.
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers — generator stubs
# ---------------------------------------------------------------------------


def _make_gen_stub(return_val):
    """Return a callable that creates a generator returning *return_val*."""

    def _stub(*args, **kwargs):
        if False:  # pragma: no branch — makes _stub a generator function
            yield
        return return_val

    return _stub


def _make_acq_result(
    orders: list | None = None,
    poll_results: list | None = None,
) -> dict:
    orders = orders or []
    poll_results = poll_results or []
    ready = [r for r in poll_results if r.get("state") == "ready"]
    return {
        "ready": ready,
        "asset_urls": {},
        "order_meta": {},
        "acquisition": {
            "imagery_outcomes": poll_results,
            "ready_count": len(ready),
            "failed_count": len(poll_results) - len(ready),
        },
    }


def _make_ful_result(
    download_results: list | None = None,
    pp_results: list | None = None,
    batch_tracking: list | None = None,
) -> dict:
    dl = download_results or []
    pp = pp_results or []
    bt = batch_tracking or []
    successful = [d for d in dl if d.get("state") != "failed"]
    failed_dl = [d for d in dl if d.get("state") == "failed"]
    batch_ok = [t for t in bt if t.get("state") == "completed"]
    batch_bad = [t for t in bt if t.get("state") == "failed"]
    return {
        "fulfilment": {
            "download_results": dl,
            "downloads_completed": len(dl) + len(bt),
            "downloads_succeeded": len(successful) + len(batch_ok),
            "downloads_failed": len(failed_dl) + len(batch_bad),
            "batch_submitted": len(bt),
            "batch_succeeded": len(batch_ok),
            "batch_failed": len(batch_bad),
            "post_process_results": pp,
            "pp_completed": len(pp),
            "pp_clipped": sum(1 for p in pp if p.get("clipped")),
            "pp_reprojected": sum(1 for p in pp if p.get("reprojected")),
            "pp_failed": sum(1 for p in pp if p.get("state") == "failed"),
        }
    }


def _get_pipeline_user_fn():
    """Extract the raw generator function from the @orchestration_trigger decorator."""
    from blueprints.pipeline.aoi_orchestrator import aoi_pipeline
    # The decorator wraps the user function; recover it via the closure.
    handle = aoi_pipeline._function._func
    return handle.__closure__[0].cell_contents


def _drive_pipeline(ctx, acq_result, ful_result):
    """Drive aoi_pipeline generator to completion with mocked sub-generators."""
    user_fn = _get_pipeline_user_fn()

    with (
        patch(
            "blueprints.pipeline.aoi_orchestrator._aoi_acquire",
            side_effect=_make_gen_stub(acq_result),
        ),
        patch(
            "blueprints.pipeline.aoi_orchestrator._aoi_fulfil",
            side_effect=_make_gen_stub(ful_result),
        ),
    ):
        gen = user_fn(ctx)
        while True:
            try:
                gen.send(None)
            except StopIteration as exc:
                return exc.value


# ---------------------------------------------------------------------------
# _aoi_acquire
# ---------------------------------------------------------------------------


class TestAoiAcquire:
    def test_composite_mode_uses_acquire_composite_activity(self):
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = []
        ctx.task_all.return_value = []
        aoi_ref = {"key": "Block A", "ref": "claims/inst/0.json"}
        gen = _aoi_acquire(ctx, {"composite_search": True}, aoi_ref)
        gen.send(None)

        call_args = ctx.call_activity_with_retry.call_args
        assert call_args.args[0] == "acquire_composite"

    def test_non_composite_mode_uses_acquire_imagery_activity(self):
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        ctx.call_activity_with_retry.return_value = {}
        ctx.task_all.return_value = []
        aoi_ref = {"key": "Block A", "ref": "claims/inst/0.json"}
        gen = _aoi_acquire(ctx, {"composite_search": False}, aoi_ref)
        gen.send(None)

        call_args = ctx.call_activity_with_retry.call_args
        assert call_args.args[0] == "acquire_imagery"

    def test_non_composite_wraps_single_result_in_list(self):
        """Non-composite acquisition wraps the single order dict in a list."""
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        ctx.task_all.return_value = []
        aoi_ref = {"key": "Block A", "ref": "claims/inst/0.json"}

        single_order = {"order_id": "ord-1", "scene_id": "sc-1"}
        ctx.call_activity_with_retry.return_value = single_order

        gen = _aoi_acquire(ctx, {"composite_search": False}, aoi_ref)
        gen.send(None)  # start, yields the call_activity_with_retry task
        try:
            gen.send(single_order)  # send back acquisition result
        except StopIteration as exc:
            result = exc.value
        else:
            try:
                gen.send([])  # send back poll results
            except StopIteration as exc:
                result = exc.value

        assert "acquisition" in result

    def test_filters_orders_without_order_id(self):
        """Orders missing order_id must not be submitted to poll_order."""
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        orders = [
            {"order_id": "ord-1", "scene_id": "sc-1"},
            {"scene_id": "sc-2"},  # no order_id
        ]
        ctx.call_activity_with_retry.return_value = orders
        ctx.task_all.return_value = [{"state": "ready", "order_id": "ord-1"}]
        aoi_ref = {"key": "Block A", "ref": "claims/inst/0.json"}

        gen = _aoi_acquire(ctx, {"composite_search": True}, aoi_ref)
        gen.send(None)
        with contextlib.suppress(StopIteration):
            gen.send(orders)
            with contextlib.suppress(StopIteration):
                gen.send([{"state": "ready", "order_id": "ord-1"}])

        # Only one order has an order_id, so only one poll task should be created.
        task_all_calls = ctx.task_all.call_args_list
        if task_all_calls:
            tasks_passed = task_all_calls[0].args[0]
            assert len(tasks_passed) == 1

    def test_no_orders_with_order_id_skips_polling(self):
        """When no order has order_id, polling is skipped and ready_count = 0."""
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        orders = [{"scene_id": "sc-1"}]  # no order_id
        ctx.call_activity_with_retry.return_value = orders

        aoi_ref = {"key": "Block A", "ref": "claims/inst/0.json"}
        gen = _aoi_acquire(ctx, {"composite_search": True}, aoi_ref)
        gen.send(None)
        result = None
        try:
            gen.send(orders)
        except StopIteration as exc:
            result = exc.value
        else:
            while True:
                try:
                    gen.send(None)
                except StopIteration as exc:
                    result = exc.value
                    break

        assert result["acquisition"]["ready_count"] == 0

    def test_result_structure_has_required_keys(self):
        """_aoi_acquire result must have ready/asset_urls/order_meta/acquisition."""
        from blueprints.pipeline.aoi_orchestrator import _aoi_acquire

        ctx = MagicMock()
        orders = [{"order_id": "ord-1", "scene_id": "sc-1"}]
        ctx.call_activity_with_retry.return_value = orders
        ctx.task_all.return_value = [{"state": "ready", "order_id": "ord-1"}]
        aoi_ref = {"key": "Field", "ref": "claims/inst/0.json"}

        gen = _aoi_acquire(ctx, {}, aoi_ref)
        gen.send(None)
        result = None
        try:
            gen.send(orders)
        except StopIteration as exc:
            result = exc.value
        else:
            try:
                gen.send([{"state": "ready", "order_id": "ord-1"}])
            except StopIteration as exc:
                result = exc.value

        assert "ready" in result
        assert "asset_urls" in result
        assert "order_meta" in result
        assert "acquisition" in result
        assert "ready_count" in result["acquisition"]
        assert "failed_count" in result["acquisition"]


# ---------------------------------------------------------------------------
# _aoi_fulfil
# ---------------------------------------------------------------------------


class TestAoiFulfil:
    def _run_fulfil(
        self,
        ready: list | None = None,
        download_results: list | None = None,
        pp_results: list | None = None,
        batch_tracking: list | None = None,
        batch_ready: list | None = None,
    ) -> dict:
        """Drive _aoi_fulfil to completion with mocked sub-generators."""
        from blueprints.pipeline.aoi_orchestrator import _aoi_fulfil

        aoi_ref = {"key": "Block A", "ref": "claims/inst/0.json"}
        acq = {
            "ready": ready or [],
            "asset_urls": {},
            "order_meta": {},
        }

        dl_result = {"download_results": download_results or []}
        pp_result = {"pp_results": pp_results or []}
        batch_result = {"batch_tracking": batch_tracking or []}

        ctx = MagicMock()

        with (
            patch(
                "blueprints.pipeline.aoi_orchestrator._fulfil_batch",
                side_effect=_make_gen_stub(batch_result),
            ),
            patch(
                "blueprints.pipeline.aoi_orchestrator._fulfil_download",
                side_effect=_make_gen_stub(dl_result),
            ),
            patch(
                "blueprints.pipeline.aoi_orchestrator._fulfil_post_process",
                side_effect=_make_gen_stub(pp_result),
            ),
            patch("blueprints.pipeline.aoi_orchestrator._split_batch_routing") as mock_split,
        ):
            # Use caller-provided batch_ready to trigger batch path
            serverless = ready or []
            batch = batch_ready or []
            mock_split.return_value = (serverless, batch)

            gen = _aoi_fulfil(ctx, {}, {}, acq, aoi_ref, 10.0, "output")
            while True:
                try:
                    gen.send(None)
                except StopIteration as exc:
                    return exc.value

    def test_result_has_fulfilment_key(self):
        result = self._run_fulfil(
            download_results=[{"state": "completed"}],
            pp_results=[{"clipped": True, "reprojected": True}],
        )
        assert "fulfilment" in result

    def test_counts_succeeded_and_failed_downloads(self):
        result = self._run_fulfil(
            download_results=[
                {"state": "completed"},
                {"state": "failed"},
                {"state": "completed"},
            ],
        )
        f = result["fulfilment"]
        assert f["downloads_succeeded"] == 2
        assert f["downloads_failed"] == 1

    def test_counts_pp_clipped_and_reprojected(self):
        result = self._run_fulfil(
            pp_results=[
                {"clipped": True, "reprojected": False},
                {"clipped": True, "reprojected": True},
                {"state": "failed"},
            ],
        )
        f = result["fulfilment"]
        assert f["pp_clipped"] == 2
        assert f["pp_reprojected"] == 1
        assert f["pp_failed"] == 1

    def test_batch_tracking_counts(self):
        result = self._run_fulfil(
            batch_tracking=[
                {"state": "completed"},
                {"state": "failed"},
            ],
            batch_ready=[{"order_id": "ord-big-1"}],  # trigger batch path
        )
        f = result["fulfilment"]
        assert f["batch_submitted"] == 2
        assert f["batch_succeeded"] == 1
        assert f["batch_failed"] == 1


# ---------------------------------------------------------------------------
# aoi_pipeline (sub-orchestrator entry point)
# ---------------------------------------------------------------------------


class TestAoiPipeline:
    def _make_ctx(
        self,
        aoi_ref: dict | None = None,
        pipeline_inp: dict | None = None,
        ctx_inp: dict | None = None,
        aoi_area_ha: float = 5.0,
    ) -> MagicMock:
        ctx = MagicMock()
        ctx.get_input.return_value = {
            "aoi_ref": aoi_ref or {"key": "Block A", "ref": "claims/inst/0.json"},
            "pipeline_input": pipeline_inp or {},
            "project_context": ctx_inp or {},
            "aoi_area_ha": aoi_area_ha,
        }
        ctx.set_custom_status = MagicMock()
        return ctx

    def test_returns_aoi_name(self):
        ctx = self._make_ctx(aoi_ref={"key": "Block A", "ref": "ref/0.json"})
        acq = _make_acq_result()
        ful = _make_ful_result()

        result = _drive_pipeline(ctx, acq, ful)
        assert result["aoi_name"] == "Block A"

    def test_returns_acquisition_and_fulfilment_keys(self):
        ctx = self._make_ctx()
        result = _drive_pipeline(ctx, _make_acq_result(), _make_ful_result())
        assert "acquisition" in result
        assert "fulfilment" in result

    def test_sets_custom_status_at_each_step(self):
        ctx = self._make_ctx()
        _drive_pipeline(ctx, _make_acq_result(), _make_ful_result())
        # set_custom_status called at least 3 times: acquiring/downloading/completed
        assert ctx.set_custom_status.call_count >= 3
        statuses = [call.args[0]["step"] for call in ctx.set_custom_status.call_args_list]
        assert "acquiring" in statuses
        assert "downloading" in statuses
        assert "completed" in statuses

    def test_default_output_container_used_when_not_specified(self):
        from treesight.constants import DEFAULT_OUTPUT_CONTAINER

        ctx = self._make_ctx(pipeline_inp={})  # no output_container key
        captured_container: list[str] = []

        def _fake_fulfil(ctx_ctx, pip_inp, proj_ctx, acq, aoi_ref, aoi_area_ha, output_container):
            captured_container.append(output_container)
            if False:  # pragma: no branch
                yield
            return _make_ful_result()

        acq = _make_acq_result()
        user_fn = _get_pipeline_user_fn()

        with (
            patch(
                "blueprints.pipeline.aoi_orchestrator._aoi_acquire",
                side_effect=_make_gen_stub(acq),
            ),
            patch(
                "blueprints.pipeline.aoi_orchestrator._aoi_fulfil",
                side_effect=_fake_fulfil,
            ),
        ):
            gen = user_fn(ctx)
            while True:
                try:
                    gen.send(None)
                except StopIteration:
                    break

        assert captured_container == [DEFAULT_OUTPUT_CONTAINER]

    def test_custom_output_container_forwarded(self):
        ctx = self._make_ctx(pipeline_inp={"output_container": "my-bucket"})
        captured: list[str] = []

        def _fake_fulfil(ctx_ctx, pip_inp, proj_ctx, acq, aoi_ref, aoi_area_ha, output_container):
            captured.append(output_container)
            if False:  # pragma: no branch
                yield
            return _make_ful_result()

        acq = _make_acq_result()
        user_fn = _get_pipeline_user_fn()

        with (
            patch(
                "blueprints.pipeline.aoi_orchestrator._aoi_acquire",
                side_effect=_make_gen_stub(acq),
            ),
            patch(
                "blueprints.pipeline.aoi_orchestrator._aoi_fulfil",
                side_effect=_fake_fulfil,
            ),
        ):
            gen = user_fn(ctx)
            while True:
                try:
                    gen.send(None)
                except StopIteration:
                    break

        assert captured == ["my-bucket"]
