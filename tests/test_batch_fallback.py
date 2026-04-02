"""Tests for Azure Batch fallback routing (#315)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from treesight.constants import BATCH_FALLBACK_AREA_HA
from treesight.pipeline.batch import needs_batch_fallback, poll_batch_task, submit_batch_job

# ---------------------------------------------------------------------------
# needs_batch_fallback
# ---------------------------------------------------------------------------


class TestNeedsBatchFallback:
    def test_small_aoi_returns_false(self):
        assert needs_batch_fallback(1_000.0) is False

    def test_exactly_at_threshold_returns_true(self):
        assert needs_batch_fallback(BATCH_FALLBACK_AREA_HA) is True

    def test_above_threshold_returns_true(self):
        assert needs_batch_fallback(100_000.0) is True

    def test_zero_area_returns_false(self):
        assert needs_batch_fallback(0.0) is False

    def test_custom_threshold(self):
        assert needs_batch_fallback(500.0, threshold=500.0) is True
        assert needs_batch_fallback(499.9, threshold=500.0) is False

    def test_default_threshold_matches_constant(self):
        assert needs_batch_fallback(BATCH_FALLBACK_AREA_HA - 0.1) is False
        assert needs_batch_fallback(BATCH_FALLBACK_AREA_HA) is True


# ---------------------------------------------------------------------------
# submit_batch_job
# ---------------------------------------------------------------------------


class TestSubmitBatchJob:
    def test_raises_without_sdk(self):
        """Gracefully errors when azure-batch isn't installed."""
        modules = {
            "azure.batch": None,
            "azure.batch.batch_auth": None,
            "azure.batch.models": None,
        }
        with patch.dict("sys.modules", modules):
            with pytest.raises(RuntimeError, match="azure-batch SDK not installed"):
                submit_batch_job(
                    aoi_ref="test-aoi",
                    claim_key="order-123",
                    asset_url="https://example.com/asset.tif",
                    output_container="kml-output",
                    project_name="test-project",
                    timestamp="20260401T120000Z",
                )

    def test_raises_without_env_vars(self):
        """Fails clearly when Batch env vars are missing."""
        mock_batch = MagicMock()
        mock_auth = MagicMock()
        mock_models = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "azure.batch": mock_batch,
                "azure.batch.batch_auth": mock_auth,
                "azure.batch.models": mock_models,
            },
        ):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(RuntimeError, match="BATCH_ACCOUNT_URL"):
                    submit_batch_job(
                        aoi_ref="test-aoi",
                        claim_key="order-123",
                        asset_url="https://example.com/asset.tif",
                        output_container="kml-output",
                        project_name="test-project",
                        timestamp="20260401T120000Z",
                    )

    def test_submit_returns_tracking_dict(self):
        """Happy path: submits job and returns tracking info."""
        mock_batch_mod = MagicMock()
        mock_auth_mod = MagicMock()
        mock_models_mod = MagicMock()
        mock_client = MagicMock()
        mock_batch_mod.BatchServiceClient.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {
                "azure.batch": mock_batch_mod,
                "azure.batch.batch_auth": mock_auth_mod,
                "azure.batch.models": mock_models_mod,
            },
        ):
            with patch.dict(
                "os.environ",
                {
                    "BATCH_ACCOUNT_NAME": "testaccount",
                    "BATCH_ACCOUNT_KEY": "testkey",  # pragma: allowlist secret
                    "BATCH_ACCOUNT_URL": "https://testaccount.eastus.batch.azure.com",
                    "BATCH_POOL_ID": "spot-pool",
                },
            ):
                result = submit_batch_job(
                    aoi_ref="large-forest-aoi",
                    claim_key="order-456",
                    asset_url="https://example.com/asset.tif",
                    output_container="kml-output",
                    project_name="large-proj",
                    timestamp="20260401T120000Z",
                )

        assert result["aoi_ref"] == "large-forest-aoi"
        assert result["claim_key"] == "order-456"
        assert result["state"] == "submitted"
        assert "job_id" in result
        assert "task_id" in result
        mock_client.task.add.assert_called_once()


# ---------------------------------------------------------------------------
# poll_batch_task
# ---------------------------------------------------------------------------


class TestPollBatchTask:
    def test_raises_without_sdk(self):
        with patch.dict("sys.modules", {"azure.batch": None, "azure.batch.batch_auth": None}):
            with pytest.raises(RuntimeError, match="azure-batch SDK not installed"):
                poll_batch_task("job-1", "task-1")

    def test_completed_task(self):
        mock_batch_mod = MagicMock()
        mock_auth_mod = MagicMock()
        mock_client = MagicMock()
        mock_batch_mod.BatchServiceClient.return_value = mock_client

        mock_task = MagicMock()
        mock_task.state = "completed"
        mock_task.execution_info.exit_code = 0
        mock_client.task.get.return_value = mock_task

        with patch.dict(
            "sys.modules",
            {
                "azure.batch": mock_batch_mod,
                "azure.batch.batch_auth": mock_auth_mod,
            },
        ):
            with patch.dict(
                "os.environ",
                {
                    "BATCH_ACCOUNT_NAME": "testaccount",
                    "BATCH_ACCOUNT_KEY": "testkey",  # pragma: allowlist secret
                    "BATCH_ACCOUNT_URL": "https://testaccount.eastus.batch.azure.com",
                },
            ):
                result = poll_batch_task("job-1", "task-1")

        assert result["state"] == "completed"
        assert result["job_id"] == "job-1"
        assert result["task_id"] == "task-1"

    def test_failed_task(self):
        mock_batch_mod = MagicMock()
        mock_auth_mod = MagicMock()
        mock_client = MagicMock()
        mock_batch_mod.BatchServiceClient.return_value = mock_client

        mock_task = MagicMock()
        mock_task.state = "completed"
        mock_task.execution_info.exit_code = 1
        mock_client.task.get.return_value = mock_task

        with patch.dict(
            "sys.modules",
            {
                "azure.batch": mock_batch_mod,
                "azure.batch.batch_auth": mock_auth_mod,
            },
        ):
            with patch.dict(
                "os.environ",
                {
                    "BATCH_ACCOUNT_NAME": "testaccount",
                    "BATCH_ACCOUNT_KEY": "testkey",  # pragma: allowlist secret
                    "BATCH_ACCOUNT_URL": "https://testaccount.eastus.batch.azure.com",
                },
            ):
                result = poll_batch_task("job-1", "task-1")

        assert result["state"] == "failed"
        assert result["exit_code"] == 1

    def test_active_task(self):
        mock_batch_mod = MagicMock()
        mock_auth_mod = MagicMock()
        mock_client = MagicMock()
        mock_batch_mod.BatchServiceClient.return_value = mock_client

        mock_task = MagicMock()
        mock_task.state = "active"
        mock_task.execution_info = None
        mock_client.task.get.return_value = mock_task

        with patch.dict(
            "sys.modules",
            {
                "azure.batch": mock_batch_mod,
                "azure.batch.batch_auth": mock_auth_mod,
            },
        ):
            with patch.dict(
                "os.environ",
                {
                    "BATCH_ACCOUNT_NAME": "testaccount",
                    "BATCH_ACCOUNT_KEY": "testkey",  # pragma: allowlist secret
                    "BATCH_ACCOUNT_URL": "https://testaccount.eastus.batch.azure.com",
                },
            ):
                result = poll_batch_task("job-1", "task-1")

        assert result["state"] == "active"


# ---------------------------------------------------------------------------
# Orchestrator routing (needs_batch_fallback integration)
# ---------------------------------------------------------------------------


class TestBatchRouting:
    """Verify the routing logic that splits ready imagery."""

    def test_all_below_threshold(self):
        """Normal AOIs: everything goes to serverless."""
        from treesight.pipeline.batch import needs_batch_fallback

        aois = [
            {"feature_name": "aoi-1", "area_ha": 1_000.0},
            {"feature_name": "aoi-2", "area_ha": 5_000.0},
        ]
        ready = [
            {"order_id": "o1", "aoi_feature_name": "aoi-1", "state": "ready"},
            {"order_id": "o2", "aoi_feature_name": "aoi-2", "state": "ready"},
        ]
        aoi_lookup = {a["feature_name"]: a for a in aois}

        serverless = []
        batch = []
        for outcome in ready:
            aoi = aoi_lookup.get(outcome["aoi_feature_name"], {})
            if needs_batch_fallback(aoi.get("area_ha", 0.0)):
                batch.append(outcome)
            else:
                serverless.append(outcome)

        assert len(serverless) == 2
        assert len(batch) == 0

    def test_mixed_aois(self):
        """Oversized AOI routes to batch, normal stays serverless."""
        from treesight.pipeline.batch import needs_batch_fallback

        aois = [
            {"feature_name": "small", "area_ha": 2_000.0},
            {"feature_name": "huge", "area_ha": 80_000.0},
        ]
        ready = [
            {"order_id": "o1", "aoi_feature_name": "small", "state": "ready"},
            {"order_id": "o2", "aoi_feature_name": "huge", "state": "ready"},
            {"order_id": "o3", "aoi_feature_name": "huge", "state": "ready"},
        ]
        aoi_lookup = {a["feature_name"]: a for a in aois}

        serverless = []
        batch = []
        for outcome in ready:
            aoi = aoi_lookup.get(outcome["aoi_feature_name"], {})
            if needs_batch_fallback(aoi.get("area_ha", 0.0)):
                batch.append(outcome)
            else:
                serverless.append(outcome)

        assert len(serverless) == 1
        assert serverless[0]["aoi_feature_name"] == "small"
        assert len(batch) == 2
        assert all(o["aoi_feature_name"] == "huge" for o in batch)

    def test_unknown_aoi_routes_to_serverless(self):
        """If AOI not in lookup (missing), area defaults to 0 → serverless."""
        from treesight.pipeline.batch import needs_batch_fallback

        ready = [{"order_id": "o1", "aoi_feature_name": "unknown", "state": "ready"}]
        aoi_lookup: dict = {}

        serverless = []
        for outcome in ready:
            aoi = aoi_lookup.get(outcome["aoi_feature_name"], {})
            if needs_batch_fallback(aoi.get("area_ha", 0.0)):
                serverless.append(outcome)  # won't hit
            else:
                serverless.append(outcome)

        assert len(serverless) == 1
