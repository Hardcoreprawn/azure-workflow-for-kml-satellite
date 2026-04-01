"""Tests for pipeline modules — orchestrator helpers (§3)."""

from __future__ import annotations

from blueprints.pipeline.history import _parse_history_limit, _parse_history_offset
from treesight.pipeline.orchestrator import (
    build_pipeline_summary,
    derive_project_context,
    get_batch_config,
)


class TestDeriveProjectContext:
    def test_extracts_stem(self):
        ctx = derive_project_context("uploads/my-farm.kml")
        assert ctx["project_name"] == "my-farm"

    def test_timestamp_format(self):
        ctx = derive_project_context("test.kml")
        assert "T" in ctx["timestamp"]
        assert ctx["timestamp"].endswith("Z")

    def test_nested_path(self):
        ctx = derive_project_context("a/b/c/orchard.kml")
        assert ctx["project_name"] == "orchard"


class TestGetBatchConfig:
    def test_defaults(self):
        cfg = get_batch_config({})
        assert cfg["poll_batch_size"] == 10
        assert cfg["download_batch_size"] == 10
        assert cfg["post_process_batch_size"] == 10

    def test_overrides(self):
        cfg = get_batch_config(
            {
                "poll_batch_size": 5,
                "download_batch_size": "20",
                "post_process_batch_size": 3.9,
            }
        )
        assert cfg["poll_batch_size"] == 5
        assert cfg["download_batch_size"] == 20
        assert cfg["post_process_batch_size"] == 3


class TestBuildPipelineSummary:
    def test_completed_summary(self):
        result = build_pipeline_summary(
            instance_id="inst-1",
            blob_name="test.kml",
            blob_url="https://storage/kml-input/test.kml",
            ingestion={
                "feature_count": 2,
                "aoi_count": 2,
                "metadata_count": 2,
                "metadata_results": [],
            },
            acquisition={"ready_count": 2, "failed_count": 0, "imagery_outcomes": []},
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [],
                "pp_completed": 2,
                "pp_clipped": 2,
                "pp_reprojected": 1,
                "pp_failed": 0,
                "post_process_results": [],
            },
        )
        assert result["status"] == "completed"
        assert result["feature_count"] == 2
        assert result["imagery_ready"] == 2

    def test_partial_summary(self):
        result = build_pipeline_summary(
            instance_id="inst-2",
            blob_name="test.kml",
            blob_url="",
            ingestion={
                "feature_count": 3,
                "aoi_count": 3,
                "metadata_count": 3,
                "metadata_results": [],
            },
            acquisition={"ready_count": 2, "failed_count": 1, "imagery_outcomes": []},
            fulfilment={
                "downloads_completed": 2,
                "downloads_succeeded": 2,
                "downloads_failed": 0,
                "download_results": [],
                "pp_completed": 2,
                "pp_clipped": 1,
                "pp_reprojected": 0,
                "pp_failed": 0,
                "post_process_results": [],
            },
        )
        assert result["status"] == "partial_imagery"


class TestParseHistoryLimit:
    def test_valid_limit(self):
        assert _parse_history_limit("5") == 5

    def test_empty_returns_default(self):
        assert _parse_history_limit("") == 8

    def test_clamps_to_max(self):
        assert _parse_history_limit("100") == 20

    def test_clamps_to_min(self):
        assert _parse_history_limit("0") == 1

    def test_non_numeric(self):
        assert _parse_history_limit("abc") == 8


class TestParseHistoryOffset:
    def test_valid_offset(self):
        assert _parse_history_offset("10") == 10

    def test_empty_returns_zero(self):
        assert _parse_history_offset("") == 0

    def test_negative_clamps_to_zero(self):
        assert _parse_history_offset("-5") == 0

    def test_clamps_to_max(self):
        assert _parse_history_offset("9999") == 200

    def test_non_numeric(self):
        assert _parse_history_offset("abc") == 0
