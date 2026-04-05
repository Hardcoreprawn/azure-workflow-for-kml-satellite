"""Tests for signed-in analysis submission endpoints."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import azure.functions as func

from tests.conftest import TEST_LOCAL_ORIGIN, make_test_request
from treesight.constants import DEFAULT_INPUT_CONTAINER, PIPELINE_PAYLOADS_CONTAINER

PIPELINE_PKG = Path(__file__).resolve().parent.parent / "blueprints" / "pipeline"


def _make_req(
    url: str,
    body: dict[str, object] | None = None,
    *,
    method: str = "POST",
    params: dict[str, str] | None = None,
    auth_header: str | None = "Bearer fake-token",
) -> func.HttpRequest:
    payload = body if body is not None else {"kml_content": "<kml></kml>"}
    return make_test_request(
        url=url,
        method=method,
        body=payload,
        params=params,
        origin=TEST_LOCAL_ORIGIN,
        auth_header=auth_header,
    )


class _FakeDurableClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def start_new(self, name: str, instance_id: str, client_input: dict[str, object]) -> str:
        self.calls.append({"name": name, "instance_id": instance_id, "client_input": client_input})
        return instance_id


class _FakeRuntimeStatus:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeDurableStatus:
    def __init__(
        self,
        instance_id: str,
        *,
        runtime_status: str,
        created_time: datetime,
        last_updated_time: datetime,
        custom_status: dict[str, object] | None = None,
        output: dict[str, object] | None = None,
    ) -> None:
        self.instance_id = instance_id
        self.name = "treesight_orchestrator"
        self.runtime_status = _FakeRuntimeStatus(runtime_status)
        self.created_time = created_time
        self.last_updated_time = last_updated_time
        self.custom_status = custom_status
        self.output = output


class _HistoryDurableClient(_FakeDurableClient):
    def __init__(self, statuses: dict[str, _FakeDurableStatus]) -> None:
        super().__init__()
        self._statuses = statuses

    async def get_status(self, instance_id: str):
        return self._statuses.get(instance_id)


class TestAnalysisSubmissionRoutes:
    def test_pipeline_declares_production_named_analysis_route(self):
        source = (PIPELINE_PKG / "submission.py").read_text()
        assert 'route="analysis/submit"' in source
        assert 'route="demo-process"' not in source

    def test_analysis_submit_uses_analysis_prefix(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = _FakeDurableClient()
        req = _make_req(
            "/api/analysis/submit",
            {
                "kml_content": "<kml></kml>",
                "submission_context": {
                    "feature_count": 12,
                    "aoi_count": 10,
                    "max_spread_km": 37.4,
                    "processing_mode": "Bulk-ready",
                    "provider_name": "planetary_computer",
                    "workspace_role": "portfolio",
                    "workspace_preference": "report",
                },
            },
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, client, blob_prefix="analysis"))

        assert resp.status_code == 202
        data = json.loads(resp.get_body())
        assert data["submission_prefix"] == "analysis"
        assert data["instance_id"]

        upload_args, upload_kwargs = mock_storage_cls.return_value.upload_bytes.call_args
        assert upload_args[0] == DEFAULT_INPUT_CONTAINER
        assert upload_args[1].startswith("analysis/")
        assert upload_args[1].endswith(".kml")
        assert upload_args[2] == b"<kml></kml>"
        assert upload_kwargs["content_type"] == "application/vnd.google-earth.kml+xml"

        record_args, _record_kwargs = mock_storage_cls.return_value.upload_json.call_args
        assert record_args[0] == PIPELINE_PAYLOADS_CONTAINER
        assert record_args[1] == f"analysis-submissions/user-123/{data['instance_id']}.json"
        assert record_args[2]["instance_id"] == data["instance_id"]
        assert record_args[2]["user_id"] == "user-123"
        assert record_args[2]["submission_prefix"] == "analysis"
        assert record_args[2]["feature_count"] == 12
        assert record_args[2]["aoi_count"] == 10
        assert record_args[2]["max_spread_km"] == 37.4
        assert record_args[2]["processing_mode"] == "Bulk-ready"
        assert record_args[2]["workspace_role"] == "portfolio"
        assert record_args[2]["workspace_preference"] == "report"

        assert len(client.calls) == 1
        assert client.calls[0]["name"] == "treesight_orchestrator"
        assert client.calls[0]["instance_id"] == data["instance_id"]
        assert client.calls[0]["client_input"]["blob_name"].startswith("analysis/")
        assert client.calls[0]["client_input"]["user_id"] == "user-123"

    def test_free_tier_submit_uses_analysis_prefix_and_limited_pipeline(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = _FakeDurableClient()
        req = _make_req("/api/analysis/submit")

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch(
                "blueprints.pipeline.submission.get_effective_subscription",
                return_value={"tier": "free", "status": "none"},
            ),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, client))

        assert resp.status_code == 202
        data = json.loads(resp.get_body())
        assert data["submission_prefix"] == "analysis"

        upload_args, _upload_kwargs = mock_storage_cls.return_value.upload_bytes.call_args
        assert upload_args[0] == DEFAULT_INPUT_CONTAINER
        assert upload_args[1].startswith("analysis/")
        assert client.calls[0]["client_input"]["blob_name"].startswith("analysis/")
        assert client.calls[0]["client_input"]["user_id"] == "user-123"
        assert client.calls[0]["client_input"]["tier"] == "free"
        assert client.calls[0]["client_input"]["cadence"] == "seasonal"
        assert client.calls[0]["client_input"]["max_history_years"] == 2

    def test_orchestrator_status_allows_anonymous_access(self):
        from blueprints.pipeline.diagnostics import _build_orchestrator_status_response

        client = _HistoryDurableClient(
            {
                "demo-run": _FakeDurableStatus(
                    "demo-run",
                    runtime_status="Completed",
                    created_time=datetime(2026, 4, 5, 15, 11, 0, tzinfo=UTC),
                    last_updated_time=datetime(2026, 4, 5, 15, 13, 0, tzinfo=UTC),
                    output={"status": "completed", "message": "done"},
                )
            }
        )
        req = func.HttpRequest(
            method="GET",
            url="/api/orchestrator/demo-run",
            headers={"Origin": TEST_LOCAL_ORIGIN},
            params={},
            route_params={"instance_id": "demo-run"},
            body=b"",
        )

        with patch(
            "blueprints.pipeline.diagnostics.pipeline_limiter.is_allowed", return_value=True
        ):
            resp = asyncio.run(_build_orchestrator_status_response(req, client))

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["instanceId"] == "demo-run"
        assert data["runtimeStatus"] == "Completed"

    def test_analysis_history_returns_recent_runs_and_active_run(self):
        from blueprints.pipeline.history import _build_analysis_history_response

        client = _HistoryDurableClient(
            {
                "active-run": _FakeDurableStatus(
                    "active-run",
                    runtime_status="Running",
                    created_time=datetime(2026, 3, 28, 19, 7, 20, tzinfo=UTC),
                    last_updated_time=datetime(2026, 3, 28, 19, 7, 53, tzinfo=UTC),
                    custom_status={"phase": "enrichment", "step": "fetching_data"},
                ),
                "done-run": _FakeDurableStatus(
                    "done-run",
                    runtime_status="Completed",
                    created_time=datetime(2026, 3, 28, 18, 0, 0, tzinfo=UTC),
                    last_updated_time=datetime(2026, 3, 28, 18, 4, 0, tzinfo=UTC),
                    output={
                        "status": "completed",
                        "message": "Analysis complete",
                        "blob_name": "analysis/done-run.kml",
                        "feature_count": 3,
                        "aoi_count": 3,
                        "metadata_count": 3,
                        "imagery_ready": 2,
                        "imagery_failed": 1,
                        "downloads_completed": 2,
                        "downloads_failed": 1,
                        "post_process_completed": 2,
                        "post_process_failed": 1,
                        "artifacts": {"report": "analysis/done-run/report.json"},
                    },
                ),
            }
        )
        req = _make_req(
            "/api/analysis/history",
            body={},
            method="GET",
            params={"limit": "2"},
        )

        with (
            patch("blueprints.pipeline.diagnostics.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.diagnostics.pipeline_limiter.is_allowed", return_value=True),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            mock_storage_cls.return_value.list_blobs.return_value = [
                "analysis-submissions/user-123/done-run.json",
                "analysis-submissions/user-123/active-run.json",
            ]
            mock_storage_cls.return_value.download_json.side_effect = [
                {
                    "submission_id": "done-run",
                    "instance_id": "done-run",
                    "user_id": "user-123",
                    "submitted_at": "2026-03-28T18:00:00+00:00",
                    "kml_blob_name": "analysis/done-run.kml",
                    "kml_size_bytes": 120,
                    "submission_prefix": "analysis",
                    "feature_count": 3,
                    "aoi_count": 3,
                    "processing_mode": "Single run",
                    "provider_name": "planetary_computer",
                    "status": "submitted",
                },
                {
                    "submission_id": "active-run",
                    "instance_id": "active-run",
                    "user_id": "user-123",
                    "submitted_at": "2026-03-28T19:07:20+00:00",
                    "kml_blob_name": "analysis/active-run.kml",
                    "kml_size_bytes": 240,
                    "submission_prefix": "analysis",
                    "feature_count": 50,
                    "aoi_count": 50,
                    "processing_mode": "May batch",
                    "provider_name": "planetary_computer",
                    "max_spread_km": 126.4,
                    "status": "submitted",
                },
            ]

            resp = asyncio.run(_build_analysis_history_response(req, client, "user-123"))

        assert resp.status_code == 200
        data = json.loads(resp.get_body())

        mock_storage_cls.return_value.list_blobs.assert_called_once_with(
            PIPELINE_PAYLOADS_CONTAINER,
            prefix="analysis-submissions/user-123/",
        )
        assert [run["instanceId"] for run in data["runs"]] == ["active-run", "done-run"]
        assert data["activeRun"]["instanceId"] == "active-run"
        assert data["activeRun"]["runtimeStatus"] == "Running"
        assert data["activeRun"]["featureCount"] == 50
        assert data["activeRun"]["aoiCount"] == 50
        assert data["activeRun"]["processingMode"] == "May batch"
        assert data["runs"][1]["runtimeStatus"] == "Completed"
        assert data["runs"][1]["output"]["blobName"] == "analysis/done-run.kml"
        assert data["runs"][1]["featureCount"] == 3
        assert data["runs"][1]["aoiCount"] == 3
        assert data["runs"][1]["partialFailures"] == {
            "imagery": 1,
            "downloads": 1,
            "postProcess": 1,
        }
        assert data["runs"][1]["artifactCount"] == 1


class TestBlobTriggerIngress:
    def _make_blob_event(self, blob_name: str, event_id: str) -> MagicMock:
        event = MagicMock()
        event.id = event_id
        event.event_time = datetime(2026, 4, 5, 15, 11, 35, tzinfo=UTC)
        event.get_json.return_value = {
            "url": f"https://devstoreaccount1.blob.core.windows.net/kml-input/{blob_name}",
            "contentLength": 42,
            "contentType": "application/vnd.google-earth.kml+xml",
        }
        return event

    def test_blob_trigger_skips_direct_submission_blobs(self):
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("analysis/test-run.kml", "evt-analysis")

        asyncio.run(_process_blob_trigger(event, client))

        assert client.calls == []

    def test_blob_trigger_starts_storage_native_uploads(self):
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("uploads/test-run.kml", "evt-upload")

        asyncio.run(_process_blob_trigger(event, client))

        assert len(client.calls) == 1
        assert client.calls[0]["name"] == "treesight_orchestrator"
        assert client.calls[0]["instance_id"] == "evt-upload"
        assert client.calls[0]["client_input"]["blob_name"] == "uploads/test-run.kml"


# ---------------------------------------------------------------------------
# Cosmos DB paths — _fetch_submission_records / _persist_submission_record
# ---------------------------------------------------------------------------


class TestFetchSubmissionRecordsCosmos:
    def test_queries_cosmos_when_available(self):
        from blueprints.pipeline.history import _fetch_submission_records

        records = [
            {"submission_id": "r1", "user_id": "u1", "submitted_at": "2026-04-01T12:00:00Z"},
        ]

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=records) as mock_q,
        ):
            result = _fetch_submission_records("u1", 8)

        assert result == records
        mock_q.assert_called_once()
        args, kwargs = mock_q.call_args
        assert args[0] == "runs"
        assert kwargs["partition_key"] == "u1"

    def test_falls_back_to_blob_when_cosmos_not_available(self):
        from blueprints.pipeline.history import _fetch_submission_records

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=False),
            patch("treesight.storage.client.BlobStorageClient") as mock_cls,
        ):
            mock_cls.return_value.list_blobs.return_value = [
                "analysis-submissions/u1/s1.json",
            ]
            mock_cls.return_value.download_json.return_value = {
                "submission_id": "s1",
                "user_id": "u1",
                "submitted_at": "2026-04-01T12:00:00Z",
            }
            result = _fetch_submission_records("u1", 8)

        assert len(result) == 1
        assert result[0]["submission_id"] == "s1"

    def test_falls_back_to_blob_on_cosmos_error(self):
        from blueprints.pipeline.history import _fetch_submission_records

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", side_effect=RuntimeError("boom")),
            patch("treesight.storage.client.BlobStorageClient") as mock_cls,
        ):
            mock_cls.return_value.list_blobs.return_value = []
            result = _fetch_submission_records("u1", 8)

        assert result == []


class TestPersistSubmissionRecordCosmos:
    def test_upserts_to_cosmos_when_available(self):
        from blueprints.pipeline.history import _persist_submission_record

        record = {"submission_id": "s1", "user_id": "u1", "status": "submitted"}

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.upsert_item") as mock_upsert,
        ):
            _persist_submission_record(None, record, "u1", "s1")

        mock_upsert.assert_called_once()
        args = mock_upsert.call_args[0]
        assert args[0] == "runs"
        assert args[1]["id"] == "s1"

    def test_falls_back_to_blob_when_cosmos_unavailable(self):
        from unittest.mock import MagicMock

        from blueprints.pipeline.history import _persist_submission_record

        storage = MagicMock()
        record = {"submission_id": "s1", "user_id": "u1", "status": "submitted"}

        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            _persist_submission_record(storage, record, "u1", "s1")

        storage.upload_json.assert_called_once()

    def test_falls_back_to_blob_on_cosmos_error(self):
        from unittest.mock import MagicMock

        from blueprints.pipeline.history import _persist_submission_record

        storage = MagicMock()
        record = {"submission_id": "s1", "user_id": "u1", "status": "submitted"}

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.upsert_item", side_effect=RuntimeError("boom")),
        ):
            _persist_submission_record(storage, record, "u1", "s1")

        storage.upload_json.assert_called_once()
