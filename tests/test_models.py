"""Tests for Pydantic domain models — Feature, AOI, BlobEvent, ImageryFilters, outcomes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from treesight.models.aoi import AOI
from treesight.models.blob_event import BlobEvent
from treesight.models.feature import Feature
from treesight.models.imagery import ImageryFilters, SearchResult
from treesight.models.outcomes import (
    DownloadResult,
    ImageryOutcome,
    PipelineSummary,
)

# ---------------------------------------------------------------------------
# Feature
# ---------------------------------------------------------------------------


class TestFeature:
    def test_create_minimal(self):
        f = Feature(name="Test")
        assert f.name == "Test"
        assert f.crs == "EPSG:4326"
        assert f.vertex_count == 0
        assert f.has_holes is False

    def test_computed_vertex_count(self, sample_feature: Feature):
        assert sample_feature.vertex_count == 5

    def test_computed_has_holes_false(self, sample_feature: Feature):
        assert sample_feature.has_holes is False

    def test_computed_has_holes_true(self):
        f = Feature(
            name="WithHoles",
            exterior_coords=[[0, 0], [1, 0], [1, 1], [0, 0]],
            interior_coords=[[[0.2, 0.2], [0.3, 0.2], [0.3, 0.3], [0.2, 0.2]]],
        )
        assert f.has_holes is True

    def test_model_dump_roundtrip(self, sample_feature: Feature):
        d = sample_feature.model_dump()
        assert isinstance(d, dict)
        assert d["name"] == "Block A - Fuji Apple"
        assert "vertex_count" in d
        assert "has_holes" in d

        restored = Feature.model_validate(d)
        assert restored.name == sample_feature.name
        assert restored.exterior_coords == sample_feature.exterior_coords

    def test_metadata_preserved(self, sample_feature: Feature):
        assert sample_feature.metadata["crop"] == "apple"
        assert sample_feature.metadata["variety"] == "fuji"


# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------


class TestAOI:
    def test_create_minimal(self):
        aoi = AOI(feature_name="Test AOI")
        assert aoi.feature_name == "Test AOI"
        assert aoi.buffer_m == 100.0
        assert aoi.crs == "EPSG:4326"
        assert aoi.bbox == [0.0, 0.0, 0.0, 0.0]

    def test_model_dump_roundtrip(self, sample_aoi: AOI):
        d = sample_aoi.model_dump()
        restored = AOI.model_validate(d)
        assert restored.feature_name == sample_aoi.feature_name
        assert restored.area_ha == pytest.approx(12.3)
        assert restored.centroid == [36.805, -1.305]

    def test_area_warning_empty_by_default(self):
        aoi = AOI(feature_name="Small")
        assert aoi.area_warning == ""


# ---------------------------------------------------------------------------
# BlobEvent
# ---------------------------------------------------------------------------


class TestBlobEvent:
    def test_create_from_dict(self, sample_blob_event_dict: dict):
        be = BlobEvent.model_validate(sample_blob_event_dict)
        assert be.blob_name == "uploads/farm.kml"
        assert be.content_length == 4096

    def test_tenant_id_default_container(self, sample_blob_event_dict: dict):
        be = BlobEvent.model_validate(sample_blob_event_dict)
        assert be.tenant_id == ""

    def test_tenant_id_tenant_container(self, tenant_blob_event_dict: dict):
        be = BlobEvent.model_validate(tenant_blob_event_dict)
        assert be.tenant_id == "acme"

    def test_output_container_default(self, sample_blob_event_dict: dict):
        be = BlobEvent.model_validate(sample_blob_event_dict)
        assert be.output_container == "kml-output"

    def test_output_container_tenant(self, tenant_blob_event_dict: dict):
        be = BlobEvent.model_validate(tenant_blob_event_dict)
        assert be.output_container == "acme-output"

    def test_model_dump_includes_computed(self, sample_blob_event_dict: dict):
        be = BlobEvent.model_validate(sample_blob_event_dict)
        d = be.model_dump()
        assert "tenant_id" in d
        assert "output_container" in d

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            BlobEvent(blob_url="x", container_name="x")  # missing other required fields


# ---------------------------------------------------------------------------
# ImageryFilters
# ---------------------------------------------------------------------------


class TestImageryFilters:
    def test_defaults(self):
        f = ImageryFilters()
        assert f.max_cloud_cover_pct == 20.0
        assert f.max_off_nadir_deg == 30.0

    def test_cloud_cover_bounds(self):
        with pytest.raises(ValidationError):
            ImageryFilters(max_cloud_cover_pct=-1)
        with pytest.raises(ValidationError):
            ImageryFilters(max_cloud_cover_pct=101)

    def test_off_nadir_bounds(self):
        with pytest.raises(ValidationError):
            ImageryFilters(max_off_nadir_deg=-5)
        with pytest.raises(ValidationError):
            ImageryFilters(max_off_nadir_deg=50)

    def test_date_end_before_start_raises(self):
        with pytest.raises(ValidationError, match="date_end must be >= date_start"):
            ImageryFilters(
                date_start=datetime(2025, 6, 1, tzinfo=UTC),
                date_end=datetime(2025, 1, 1, tzinfo=UTC),
            )

    def test_date_end_after_start_ok(self):
        f = ImageryFilters(
            date_start=datetime(2025, 1, 1, tzinfo=UTC),
            date_end=datetime(2025, 6, 1, tzinfo=UTC),
        )
        assert f.date_end > f.date_start

    def test_max_resolution_gte_min(self):
        with pytest.raises(ValidationError, match="max_resolution_m must be >= min_resolution_m"):
            ImageryFilters(min_resolution_m=1.0, max_resolution_m=0.5)

    def test_model_dump_roundtrip(self):
        f = ImageryFilters(max_cloud_cover_pct=15.0, collections=["sentinel-2-l2a"])
        d = f.model_dump()
        restored = ImageryFilters.model_validate(d)
        assert restored.max_cloud_cover_pct == 15.0
        assert restored.collections == ["sentinel-2-l2a"]


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_valid_search_result(self):
        sr = SearchResult(
            scene_id="S2B_test",
            provider="planetary_computer",
            acquisition_date=datetime(2025, 1, 15, tzinfo=UTC),
            cloud_cover_pct=8.5,
            spatial_resolution_m=10.0,
            off_nadir_deg=5.0,
            crs="EPSG:32637",
            bbox=[36.0, -2.0, 37.0, -1.0],
        )
        assert sr.scene_id == "S2B_test"

    def test_empty_scene_id_rejected(self):
        with pytest.raises(ValidationError):
            SearchResult(
                scene_id="",
                provider="pc",
                acquisition_date=datetime.now(UTC),
                cloud_cover_pct=0,
                spatial_resolution_m=10,
                off_nadir_deg=0,
                crs="EPSG:4326",
                bbox=[0, 0, 1, 1],
            )


# ---------------------------------------------------------------------------
# Outcome models
# ---------------------------------------------------------------------------


class TestImageryOutcome:
    def test_defaults(self):
        o = ImageryOutcome()
        assert o.state == ""
        assert o.error == ""

    def test_model_dump_roundtrip(self):
        o = ImageryOutcome(state="ready", order_id="ord-1", provider="pc")
        d = o.model_dump()
        restored = ImageryOutcome.model_validate(d)
        assert restored.state == "ready"
        assert restored.order_id == "ord-1"


class TestDownloadResult:
    def test_model_dump(self):
        dr = DownloadResult(
            order_id="ord-1",
            scene_id="scene-1",
            provider="pc",
            blob_path="imagery/raw/test.tif",
            container="kml-output",
            size_bytes=1024,
        )
        d = dr.model_dump()
        assert d["blob_path"] == "imagery/raw/test.tif"


class TestPipelineSummary:
    def test_compute_status_completed(self):
        s = PipelineSummary(
            instance_id="inst-1",
            feature_count=2,
            aoi_count=2,
            imagery_ready=2,
            imagery_failed=0,
            downloads_completed=2,
            downloads_succeeded=2,
            downloads_failed=0,
            post_process_failed=0,
        )
        s.compute_status()
        assert s.status == "completed"

    def test_compute_status_partial_imagery_failure(self):
        s = PipelineSummary(
            instance_id="inst-1",
            feature_count=2,
            imagery_ready=1,
            imagery_failed=1,
            downloads_completed=1,
            downloads_succeeded=1,
        )
        s.compute_status()
        assert s.status == "partial_imagery"

    def test_compute_status_partial_download_failure(self):
        s = PipelineSummary(
            instance_id="inst-1",
            feature_count=2,
            imagery_ready=2,
            imagery_failed=0,
            downloads_completed=2,
            downloads_succeeded=1,
            downloads_failed=1,
        )
        s.compute_status()
        assert s.status == "partial_imagery"

    def test_compute_status_partial_pp_failure(self):
        s = PipelineSummary(
            instance_id="inst-1",
            feature_count=2,
            imagery_ready=2,
            imagery_failed=0,
            downloads_completed=2,
            downloads_succeeded=2,
            downloads_failed=0,
            post_process_failed=1,
        )
        s.compute_status()
        assert s.status == "partial_imagery"

    def test_message_contains_counts(self):
        s = PipelineSummary(
            instance_id="inst-1",
            feature_count=3,
            aoi_count=3,
            imagery_ready=2,
            imagery_failed=1,
        )
        s.compute_status()
        assert "3 feature(s)" in s.message
        assert "ready=2" in s.message
        assert "failed=1" in s.message

    def test_artifacts_from_results(self):
        s = PipelineSummary(
            instance_id="inst-1",
            metadata_results=[
                {"metadata_path": "metadata/farm/ts/block_a.json"},
            ],
            download_results=[
                {"blob_path": "imagery/raw/farm/ts/block_a/scene1.tif"},
            ],
            post_process_results=[
                {"clipped_blob_path": "imagery/clipped/farm/ts/block_a/scene1.tif"},
            ],
        )
        arts = s.artifacts
        assert arts["metadataPaths"] == ["metadata/farm/ts/block_a.json"]
        assert arts["rawImageryPaths"] == ["imagery/raw/farm/ts/block_a/scene1.tif"]
        assert arts["clippedImageryPaths"] == ["imagery/clipped/farm/ts/block_a/scene1.tif"]
