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

    def test_analysis_history_org_scope_returns_portfolio_stats(self):
        from blueprints.pipeline.history import _build_analysis_history_response

        client = _HistoryDurableClient(
            {
                "member-a-run": _FakeDurableStatus(
                    "member-a-run",
                    runtime_status="Running",
                    created_time=datetime(2026, 4, 10, 11, 0, 0, tzinfo=UTC),
                    last_updated_time=datetime(2026, 4, 10, 11, 2, 0, tzinfo=UTC),
                    custom_status={"phase": "acquisition"},
                ),
                "member-b-run": _FakeDurableStatus(
                    "member-b-run",
                    runtime_status="Completed",
                    created_time=datetime(2026, 4, 10, 9, 0, 0, tzinfo=UTC),
                    last_updated_time=datetime(2026, 4, 10, 9, 5, 0, tzinfo=UTC),
                    output={"feature_count": 2, "aoi_count": 2},
                ),
            }
        )
        req = _make_req(
            "/api/analysis/history",
            body={},
            method="GET",
            params={"limit": "6", "scope": "org"},
        )

        def _list_blobs(_container: str, *, prefix: str):
            if prefix.endswith("user-123/"):
                return [f"{prefix}member-a-run.json"]
            if prefix.endswith("member-b/"):
                return [f"{prefix}member-b-run.json"]
            return []

        def _download_json(_container: str, blob_name: str):
            if blob_name.endswith("member-a-run.json"):
                return {
                    "submission_id": "member-a-run",
                    "instance_id": "member-a-run",
                    "user_id": "user-123",
                    "submitted_at": "2026-04-10T11:00:00+00:00",
                    "aoi_count": 5,
                    "provider_name": "planetary_computer",
                    "status": "submitted",
                }
            return {
                "submission_id": "member-b-run",
                "instance_id": "member-b-run",
                "user_id": "member-b",
                "submitted_at": "2026-04-10T09:00:00+00:00",
                "aoi_count": 2,
                "provider_name": "planetary_computer",
                "status": "submitted",
            }

        with (
            patch("blueprints.pipeline.history.get_user_org") as mock_get_org,
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            mock_get_org.return_value = {
                "org_id": "org-1",
                "members": [
                    {"user_id": "user-123", "role": "owner"},
                    {"user_id": "member-b", "role": "member"},
                ],
            }
            mock_storage_cls.return_value.list_blobs.side_effect = _list_blobs
            mock_storage_cls.return_value.download_json.side_effect = _download_json

            resp = asyncio.run(_build_analysis_history_response(req, client, "user-123"))

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["scope"] == "org"
        assert data["orgId"] == "org-1"
        assert data["memberCount"] == 2
        assert [run["instanceId"] for run in data["runs"]] == ["member-a-run", "member-b-run"]
        assert data["stats"] == {
            "totalRuns": 2,
            "activeRuns": 1,
            "completedRuns": 1,
            "failedRuns": 0,
            "totalParcels": 7,
            "lastSubmittedAt": "2026-04-10T11:00:00+00:00",
        }

    def test_analysis_history_org_scope_falls_back_to_user_scope_without_org(self):
        from blueprints.pipeline.history import _build_analysis_history_response

        client = _HistoryDurableClient({})
        req = _make_req(
            "/api/analysis/history",
            body={},
            method="GET",
            params={"limit": "2", "scope": "org"},
        )

        with (
            patch("blueprints.pipeline.history.get_user_org", return_value=None),
            patch("blueprints.pipeline.history._fetch_submission_records", return_value=[]),
        ):
            resp = asyncio.run(_build_analysis_history_response(req, client, "user-123"))

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["scope"] == "user"
        assert data["orgId"] is None
        assert data["memberCount"] == 1


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

        sub_id = "550e8400-e29b-41d4-a716-446655440000"
        client = _FakeDurableClient()
        event = self._make_blob_event(f"analysis/{sub_id}.kml", "evt-analysis")

        with patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls:
            mock_storage_cls.return_value.download_json.return_value = {
                "user_id": "user-abc",
                "provider_name": "planetary_computer",
                "created_at": "2026-04-05T15:11:00Z",
            }
            asyncio.run(_process_blob_trigger(event, client))

        assert len(client.calls) == 1
        assert client.calls[0]["name"] == "treesight_orchestrator"
        # Uses submission_id (UUID) from blob path, not event.id
        assert client.calls[0]["instance_id"] == sub_id
        assert client.calls[0]["client_input"]["blob_name"] == f"analysis/{sub_id}.kml"

    def test_blob_trigger_enriches_from_ticket(self):
        """Blob trigger reads ticket blob for user metadata."""
        from blueprints.pipeline.blob_trigger import _process_blob_trigger

        client = _FakeDurableClient()
        sub_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        event = self._make_blob_event(f"analysis/{sub_id}.kml", "evt-1")

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
        sub_id = "deadbeef-dead-beef-dead-beefdeadbeef"
        event = self._make_blob_event(f"analysis/{sub_id}.kml", "evt-pre")

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
        sub_id = "12345678-1234-1234-1234-123456789012"
        event = self._make_blob_event(f"analysis/{sub_id}.kml", "evt-free")

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

        # Valid UUID stem → used as instance_id
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert _derive_instance_id(f"analysis/{test_uuid}.kml", "evt-1") == test_uuid

    def test_non_analysis_prefix_uses_event_id(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        assert _derive_instance_id("uploads/test.kml", "evt-2") == "evt-2"

    def test_single_part_path_uses_event_id(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        assert _derive_instance_id("orphan.kml", "evt-3") == "evt-3"

    def test_nested_analysis_path_uses_event_id(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        # Nested paths (analysis/sub/deep.kml) are not
        # direct submissions — fall back to event_id
        assert _derive_instance_id("analysis/sub/deep.kml", "evt-4") == "evt-4"

    def test_non_uuid_stem_uses_event_id(self):
        from blueprints.pipeline.blob_trigger import _derive_instance_id

        # Non-UUID stem should not be used as instance_id
        assert _derive_instance_id("analysis/not-a-uuid.kml", "evt-5") == "evt-5"


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

    def test_copies_eudr_mode_true(self):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch: dict[str, object] = {}
        _enrich_from_ticket(orch, {"user_id": "u1", "tier": "pro", "eudr_mode": True})
        assert orch["eudr_mode"] is True

    def test_copies_eudr_mode_false(self):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch: dict[str, object] = {}
        _enrich_from_ticket(orch, {"user_id": "u1", "tier": "pro", "eudr_mode": False})
        assert orch.get("eudr_mode") is False

    def test_rejects_non_bool_eudr_mode(self):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch: dict[str, object] = {}
        _enrich_from_ticket(orch, {"user_id": "u1", "tier": "pro", "eudr_mode": "yes"})
        assert "eudr_mode" not in orch

    def test_eudr_mode_absent_not_injected(self):
        from blueprints.pipeline.blob_trigger import _enrich_from_ticket

        orch: dict[str, object] = {}
        _enrich_from_ticket(orch, {"user_id": "u1", "tier": "pro"})
        assert "eudr_mode" not in orch


# ---------------------------------------------------------------------------
# EUDR mode submission flag (#600)
# ---------------------------------------------------------------------------


class TestEudrModeSubmission:
    """Verify eudr_mode flows from request body to ticket and run record."""

    def test_eudr_mode_true_included_in_ticket(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"kml_content": "<kml></kml>", "eudr_mode": True},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202

        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        assert len(ticket_calls) >= 1
        ticket_data = ticket_calls[0][0][2]
        assert ticket_data["eudr_mode"] is True

    def test_eudr_mode_false_not_in_ticket(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"kml_content": "<kml></kml>", "eudr_mode": False},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202

        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        ticket_data = ticket_calls[0][0][2]
        assert ticket_data.get("eudr_mode") is not True

    def test_eudr_mode_non_bool_rejected(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"kml_content": "<kml></kml>", "eudr_mode": "yes"},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202

        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        ticket_data = ticket_calls[0][0][2]
        assert "eudr_mode" not in ticket_data

    def test_eudr_mode_stored_in_run_record(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {
                "kml_content": "<kml></kml>",
                "eudr_mode": True,
                "submission_context": {"feature_count": 1},
            },
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202

        # Check the run record (uploaded to analysis-submissions/)
        history_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if "analysis-submissions/" in str(c)
        ]
        assert len(history_calls) >= 1
        record = history_calls[0][0][2]
        assert record["eudr_mode"] is True


# ---------------------------------------------------------------------------
# EUDR mode — acquisition date filtering (#600)
# ---------------------------------------------------------------------------


class TestEudrModeAcquisitionDateFilter:
    """When eudr_mode=True, imagery_filters.date_start must be >= EUDR cutoff."""

    def test_eudr_mode_sets_date_start_on_imagery_filters(self):
        """Orchestrator input with eudr_mode=True should inject imagery_filters date_start."""
        from treesight.constants import EUDR_CUTOFF_DATE
        from treesight.pipeline.submission_helpers import build_eudr_imagery_overrides

        overrides = build_eudr_imagery_overrides(eudr_mode=True, existing_filters=None)
        assert overrides is not None
        assert overrides["date_start"]
        # date_start should be the EUDR cutoff
        assert EUDR_CUTOFF_DATE in overrides["date_start"]

    def test_eudr_mode_false_no_overrides(self):
        from treesight.pipeline.submission_helpers import build_eudr_imagery_overrides

        overrides = build_eudr_imagery_overrides(eudr_mode=False, existing_filters=None)
        assert overrides is None

    def test_eudr_mode_preserves_existing_filters(self):
        from treesight.constants import EUDR_CUTOFF_DATE
        from treesight.pipeline.submission_helpers import build_eudr_imagery_overrides

        existing = {"max_cloud_cover_pct": 15.0}
        overrides = build_eudr_imagery_overrides(eudr_mode=True, existing_filters=existing)
        assert overrides is not None
        assert overrides["max_cloud_cover_pct"] == 15.0
        assert EUDR_CUTOFF_DATE in overrides["date_start"]


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


class TestCoordinateSubmission:
    """Tests for coordinate/CSV submission paths (#601)."""

    def test_coordinate_text_submission(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"coordinates": "51.5, -0.1"},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202
        # Verify KML was generated from coordinates
        upload_calls = list(mock_storage_cls.return_value.upload_bytes.call_args_list)
        assert len(upload_calls) >= 1
        kml_bytes = upload_calls[0][0][2]
        assert b"<kml" in kml_bytes
        assert b"Point" in kml_bytes  # Feature name contains "Point"

    def test_csv_submission(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"csv_content": "name,lat,lon\nFarm A,51.5,-0.1\nFarm B,48.8,2.3"},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient") as mock_storage_cls,
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202
        kml_bytes = mock_storage_cls.return_value.upload_bytes.call_args_list[0][0][2]
        assert b"Farm A" in kml_bytes
        assert b"Farm B" in kml_bytes

    def test_invalid_coordinates_returns_400(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"coordinates": "not valid coords"},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 400

    def test_invalid_csv_returns_400(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"csv_content": "x,y\n1,2"},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 400

    def test_kml_still_works(self):
        """Classic KML submission still functions after coordinate support added."""
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_req(
            "/api/analysis/submit",
            {"kml_content": "<kml><Document></Document></kml>"},
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient"),
        ):
            resp = asyncio.run(_submit_analysis_request(req, blob_prefix="analysis"))

        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Parcel annotation and override endpoints (Stage 3C.2 / 3C.3)
# ---------------------------------------------------------------------------

_FAKE_RUN = {
    "id": "inst-abc",
    "user_id": "user-123",
    "submitted_at": "2026-04-01T10:00:00Z",
    "status": "completed",
}


class TestRunRecordLookup:
    """Unit tests for get_run_record_by_instance_id and assert_run_write_access."""

    def test_get_run_record_returns_none_when_cosmos_unavailable(self):
        from blueprints.pipeline.history import get_run_record_by_instance_id

        with patch("blueprints.pipeline.history._cosmos_mod.cosmos_available", return_value=False):
            result = get_run_record_by_instance_id("inst-abc")

        assert result is None

    def test_get_run_record_queries_cosmos_by_id(self):
        from blueprints.pipeline.history import get_run_record_by_instance_id

        with (
            patch("blueprints.pipeline.history._cosmos_mod.cosmos_available", return_value=True),
            patch(
                "blueprints.pipeline.history._cosmos_mod.query_items",
                return_value=[_FAKE_RUN],
            ) as mock_query,
        ):
            result = get_run_record_by_instance_id("inst-abc")

        assert result == _FAKE_RUN
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        assert "@id" in str(call_args)

    def test_get_run_record_returns_none_when_not_found(self):
        from blueprints.pipeline.history import get_run_record_by_instance_id

        with (
            patch("blueprints.pipeline.history._cosmos_mod.cosmos_available", return_value=True),
            patch("blueprints.pipeline.history._cosmos_mod.query_items", return_value=[]),
        ):
            result = get_run_record_by_instance_id("no-such-id")

        assert result is None

    def test_assert_run_write_access_permits_owner(self):
        from blueprints.pipeline.history import assert_run_write_access

        # Should not raise
        assert_run_write_access(_FAKE_RUN, "user-123")

    def test_assert_run_write_access_permits_org_member(self):
        from blueprints.pipeline.history import assert_run_write_access

        org = {"members": [{"user_id": "user-123"}, {"user_id": "user-456"}]}
        with patch("blueprints.pipeline.history.get_user_org", return_value=org):
            # user-456 is an org member; user-123 is the owner → access granted
            assert_run_write_access(_FAKE_RUN, "user-456")

    def test_assert_run_write_access_denies_stranger(self):
        import pytest

        from blueprints.pipeline.history import assert_run_write_access

        with (
            patch("blueprints.pipeline.history.get_user_org", return_value=None),
            pytest.raises(ValueError, match="permission"),
        ):
            assert_run_write_access(_FAKE_RUN, "stranger-999")


class TestAnnotationEndpoints:
    """Endpoint-level tests for /api/analysis/notes and /api/analysis/override."""

    def _make_req(self, url: str, body: dict) -> func.HttpRequest:
        return make_test_request(
            url=url,
            method="POST",
            body=body,
            origin=TEST_LOCAL_ORIGIN,
            auth_header="Bearer fake-token",
        )

    def test_notes_requires_auth(self):
        from blueprints.pipeline.annotations import analysis_notes

        req = make_test_request(
            url="/api/analysis/notes",
            method="POST",
            body={"instance_id": "inst-abc", "parcel_key": "0", "note": "test"},
            origin=TEST_LOCAL_ORIGIN,
            auth_header=None,
        )
        with patch(
            "blueprints.pipeline.annotations.check_auth",
            side_effect=ValueError("Unauthorized"),
        ):
            resp = analysis_notes(req)
        assert resp.status_code == 401

    def test_notes_saves_note_to_cosmos(self):
        from blueprints.pipeline.annotations import analysis_notes

        req = self._make_req(
            "/api/analysis/notes",
            {"instance_id": "inst-abc", "parcel_key": "0", "note": "This parcel looks fine."},
        )
        with (
            patch("blueprints.pipeline.annotations.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.annotations.pipeline_limiter.is_allowed", return_value=True),
            patch(
                "blueprints.pipeline.annotations._cosmos_mod.cosmos_available", return_value=True
            ),
            patch(
                "blueprints.pipeline.annotations.get_run_record_by_instance_id",
                return_value=dict(_FAKE_RUN),
            ),
            patch("blueprints.pipeline.annotations.assert_run_write_access"),
            patch("blueprints.pipeline.annotations.cosmos") as mock_cosmos,
        ):
            resp = analysis_notes(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["saved"] is True
        assert data["parcel_key"] == "0"
        mock_cosmos.upsert_item.assert_called_once()
        upserted = mock_cosmos.upsert_item.call_args[0][1]
        assert "parcel_notes" in upserted
        assert upserted["parcel_notes"]["0"]["text"] == "This parcel looks fine."
        assert upserted["parcel_notes"]["0"]["author_id"] == "user-123"

    def test_notes_denies_non_owner(self):
        from blueprints.pipeline.annotations import analysis_notes

        req = self._make_req(
            "/api/analysis/notes",
            {"instance_id": "inst-abc", "parcel_key": "0", "note": "sneaky"},
        )
        with (
            patch("blueprints.pipeline.annotations.check_auth", return_value=({}, "stranger-999")),
            patch("blueprints.pipeline.annotations.pipeline_limiter.is_allowed", return_value=True),
            patch(
                "blueprints.pipeline.annotations._cosmos_mod.cosmos_available", return_value=True
            ),
            patch(
                "blueprints.pipeline.annotations.get_run_record_by_instance_id",
                return_value=dict(_FAKE_RUN),
            ),
            patch(
                "blueprints.pipeline.annotations.assert_run_write_access",
                side_effect=ValueError("permission"),
            ),
        ):
            resp = analysis_notes(req)

        assert resp.status_code == 403

    def test_override_requires_reason_min_length(self):
        from blueprints.pipeline.annotations import analysis_override

        req = self._make_req(
            "/api/analysis/override",
            {"instance_id": "inst-abc", "parcel_key": "0", "reason": "too short"},
        )
        with (
            patch("blueprints.pipeline.annotations.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.annotations.pipeline_limiter.is_allowed", return_value=True),
            patch(
                "blueprints.pipeline.annotations._cosmos_mod.cosmos_available", return_value=True
            ),
        ):
            resp = analysis_override(req)

        assert resp.status_code == 400
        assert b"20 characters" in resp.get_body()

    def test_override_saves_to_cosmos_with_audit_trail(self):
        from blueprints.pipeline.annotations import analysis_override

        reason = "Seasonal clearing — farmer confirmed replanting schedule on record."
        req = self._make_req(
            "/api/analysis/override",
            {"instance_id": "inst-abc", "parcel_key": "1", "reason": reason},
        )
        with (
            patch("blueprints.pipeline.annotations.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.annotations.pipeline_limiter.is_allowed", return_value=True),
            patch(
                "blueprints.pipeline.annotations._cosmos_mod.cosmos_available", return_value=True
            ),
            patch(
                "blueprints.pipeline.annotations.get_run_record_by_instance_id",
                return_value=dict(_FAKE_RUN),
            ),
            patch("blueprints.pipeline.annotations.assert_run_write_access"),
            patch("blueprints.pipeline.annotations.cosmos") as mock_cosmos,
        ):
            resp = analysis_override(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["saved"] is True
        assert data["reverted"] is False
        upserted = mock_cosmos.upsert_item.call_args[0][1]
        override = upserted["parcel_overrides"]["1"]
        assert override["override_determination"] == "compliant"
        assert override["overridden_by"] == "user-123"
        assert override["reason"] == reason

    def test_override_revert_removes_entry(self):
        from blueprints.pipeline.annotations import analysis_override

        run_with_override = dict(_FAKE_RUN)
        run_with_override["parcel_overrides"] = {
            "0": {
                "reason": "old reason",
                "overridden_by": "user-123",
                "override_determination": "compliant",
            }
        }
        req = self._make_req(
            "/api/analysis/override",
            {"instance_id": "inst-abc", "parcel_key": "0", "revert": True},
        )
        with (
            patch("blueprints.pipeline.annotations.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.annotations.pipeline_limiter.is_allowed", return_value=True),
            patch(
                "blueprints.pipeline.annotations._cosmos_mod.cosmos_available", return_value=True
            ),
            patch(
                "blueprints.pipeline.annotations.get_run_record_by_instance_id",
                return_value=run_with_override,
            ),
            patch("blueprints.pipeline.annotations.assert_run_write_access"),
            patch("blueprints.pipeline.annotations.cosmos") as mock_cosmos,
        ):
            resp = analysis_override(req)

        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["reverted"] is True
        upserted = mock_cosmos.upsert_item.call_args[0][1]
        assert "0" not in upserted.get("parcel_overrides", {})
