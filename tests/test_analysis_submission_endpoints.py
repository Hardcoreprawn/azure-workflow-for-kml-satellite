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
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202
        data = json.loads(resp.get_body())
        assert data["submission_prefix"] == "analysis"
        assert data["instance_id"]

        # Verify KML upload
        upload_calls = list(mock_storage_cls.return_value.upload_bytes.call_args_list)
        assert len(upload_calls) >= 1
        upload_args, upload_kwargs = upload_calls[0]
        assert upload_args[0] == DEFAULT_INPUT_CONTAINER
        assert upload_args[1].startswith("analysis/")
        assert upload_args[1].endswith(".kml")
        assert upload_args[2] == b"<kml></kml>"
        assert upload_kwargs["content_type"] == "application/vnd.google-earth.kml+xml"

        # Verify ticket blob written
        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        assert len(ticket_calls) >= 1
        ticket_args = ticket_calls[0][0]
        assert ticket_args[0] == DEFAULT_INPUT_CONTAINER  # same container
        assert ticket_args[1].startswith(".tickets/")
        assert ticket_args[1].endswith(".json")
        ticket_data = ticket_args[2]
        assert ticket_data["user_id"] == "user-123"

        # Verify submission history record
        history_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if "analysis-submissions/" in str(c)
        ]
        assert len(history_calls) >= 1
        record_args = history_calls[0][0]
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

        # No direct orchestrator start — Event Grid handles it now

    def test_free_tier_submit_uses_analysis_prefix_and_limited_pipeline(self):
        from blueprints.pipeline.submission import _submit_analysis_request

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
            resp = asyncio.run(_submit_analysis_request(req))

        assert resp.status_code == 202
        data = json.loads(resp.get_body())
        assert data["submission_prefix"] == "analysis"

        upload_args, _upload_kwargs = mock_storage_cls.return_value.upload_bytes.call_args
        assert upload_args[0] == DEFAULT_INPUT_CONTAINER
        assert upload_args[1].startswith("analysis/")

        # Verify ticket includes tier info for blob_trigger to read
        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        assert len(ticket_calls) >= 1
        ticket_data = ticket_calls[0][0][2]
        assert ticket_data["user_id"] == "user-123"
        assert ticket_data["tier"] == "free"
        assert ticket_data["cadence"] == "seasonal"
        assert ticket_data["max_history_years"] == 2

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

    def test_blob_trigger_processes_analysis_prefix_blobs(self):
        """After event-driven unification, blob_trigger processes ALL blobs."""
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("analysis/test-run.kml", "evt-analysis")

        with patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls:
            mock_storage_cls.return_value.download_json.return_value = {
                "user_id": "user-abc",
                "provider_name": "planetary_computer",
                "created_at": "2026-04-05T15:11:00Z",
            }
            asyncio.run(_process_blob_trigger(event, client))

        assert len(client.calls) == 1
        assert client.calls[0]["name"] == "treesight_orchestrator"
        # Uses submission_id from blob path, not event.id
        assert client.calls[0]["instance_id"] == "test-run"
        assert client.calls[0]["client_input"]["blob_name"] == "analysis/test-run.kml"

    def test_blob_trigger_enriches_from_ticket(self):
        """Blob trigger reads ticket blob for user metadata."""
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("analysis/abc-123.kml", "evt-1")

        ticket = {
            "user_id": "user-xyz",
            "provider_name": "planetary_computer",
            "created_at": "2026-04-05T15:00:00Z",
        }
        with (
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
            patch(
                "blueprints.pipeline.blob_trigger.get_effective_subscription",
                return_value={"tier": "pro", "status": "active"},
            ),
        ):
            mock_storage_cls.return_value.download_json.return_value = ticket
            asyncio.run(_process_blob_trigger(event, client))

        orch_input = client.calls[0]["client_input"]
        assert orch_input["user_id"] == "user-xyz"
        assert orch_input["provider_name"] == "planetary_computer"
        assert orch_input["tier"] == "pro"

    def test_blob_trigger_enriches_with_pre_resolved_tier(self):
        """When ticket already has tier, billing lookup is skipped."""
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("analysis/pre-resolved.kml", "evt-pre")

        ticket = {
            "user_id": "user-pre",
            "tier": "pro",
            "cadence": "monthly",
            "max_history_years": 5,
            "provider_name": "planetary_computer",
            "created_at": "2026-04-05T15:00:00Z",
        }
        with patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls:
            mock_storage_cls.return_value.download_json.return_value = ticket
            # No billing mock — should NOT be called
            asyncio.run(_process_blob_trigger(event, client))

        orch_input = client.calls[0]["client_input"]
        assert orch_input["user_id"] == "user-pre"
        assert orch_input["tier"] == "pro"
        assert orch_input["cadence"] == "monthly"
        assert orch_input["max_history_years"] == 5

    def test_blob_trigger_works_without_ticket(self):
        """Storage-native uploads (no ticket) still work."""
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("uploads/test-run.kml", "evt-upload")

        with patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls:
            mock_storage_cls.return_value.download_json.side_effect = Exception("not found")
            asyncio.run(_process_blob_trigger(event, client))

        assert len(client.calls) == 1
        assert client.calls[0]["name"] == "treesight_orchestrator"
        assert client.calls[0]["instance_id"] == "evt-upload"
        assert client.calls[0]["client_input"]["blob_name"] == "uploads/test-run.kml"
        # No user_id when no ticket
        assert "user_id" not in client.calls[0]["client_input"]

    def test_blob_trigger_applies_free_tier_limits(self):
        """Free tier ticket should apply cadence and history limits."""
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        event = self._make_blob_event("analysis/free-run.kml", "evt-free")

        ticket = {"user_id": "free-user", "created_at": "2026-04-05T15:00:00Z"}
        with (
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
            patch(
                "blueprints.pipeline.blob_trigger.get_effective_subscription",
                return_value={"tier": "free", "status": "none"},
            ),
        ):
            mock_storage_cls.return_value.download_json.return_value = ticket
            asyncio.run(_process_blob_trigger(event, client))

        orch_input = client.calls[0]["client_input"]
        assert orch_input["tier"] == "free"
        assert orch_input["cadence"] == "seasonal"
        assert orch_input["max_history_years"] == 2


class TestDeriveInstanceId:
    """Unit tests for _derive_instance_id (pure function)."""

    def test_analysis_prefix_uses_stem(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        assert _derive_instance_id("analysis/abc-123.kml", "evt-1") == "abc-123"

    def test_non_analysis_prefix_uses_event_id(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        assert _derive_instance_id("uploads/test.kml", "evt-2") == "evt-2"

    def test_single_part_path_uses_event_id(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        assert _derive_instance_id("orphan.kml", "evt-3") == "evt-3"

    def test_nested_analysis_path(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        assert _derive_instance_id("analysis/sub/deep.kml", "evt-4") == "deep"


class TestEnrichFromTicket:
    """Unit tests for _enrich_from_ticket type validation."""

    def test_rejects_non_string_user_id(self):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch = {}
        _enrich_from_ticket(orch, {"user_id": 12345})
        assert "user_id" not in orch

    @patch(
        "blueprints.pipeline.blob_trigger.get_effective_subscription",
        return_value={"tier": "free", "status": "none"},
    )
    def test_rejects_non_string_tier(self, _mock_billing):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch = {}
        _enrich_from_ticket(orch, {"user_id": "u1", "tier": 999})
        # tier 999 rejected; billing lookup sets "free"
        assert orch["tier"] == "free"

    @patch(
        "blueprints.pipeline.blob_trigger.get_effective_subscription",
        return_value={"tier": "free", "status": "none"},
    )
    def test_rejects_non_numeric_max_history_years(self, _mock_billing):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch = {}
        _enrich_from_ticket(orch, {"user_id": "u1", "max_history_years": "unlimited"})
        assert "max_history_years" not in orch or isinstance(orch.get("max_history_years"), int)

    def test_accepts_valid_typed_fields(self):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch = {}
        _enrich_from_ticket(
            orch,
            {
                "user_id": "u1",
                "tier": "pro",
                "cadence": "monthly",
                "max_history_years": 5,
                "provider_name": "planetary_computer",
            },
        )
        assert orch["user_id"] == "u1"
        assert orch["tier"] == "pro"
        assert orch["cadence"] == "monthly"
        assert orch["max_history_years"] == 5
        assert orch["provider_name"] == "planetary_computer"


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
