"""Unit tests for pipeline run telemetry (#400)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from treesight.pipeline.telemetry import (
    _extract_enrichment_set,
    _haversine_km,
    _max_spread_km,
    build_stats_document,
)


class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert _haversine_km(0, 0, 0, 0) == 0.0

    def test_known_distance(self):
        # London (lon=-0.1276, lat=51.5074) to Paris (lon=2.3522, lat=48.8566) ≈ 340 km
        d = _haversine_km(-0.1276, 51.5074, 2.3522, 48.8566)
        assert 330 < d < 350


class TestMaxSpreadKm:
    def test_empty_returns_none(self):
        assert _max_spread_km([]) is None

    def test_single_centroid_returns_none(self):
        assert _max_spread_km([[0.0, 0.0]]) is None

    def test_two_centroids_returns_distance(self):
        result = _max_spread_km([[-0.1276, 51.5074], [2.3522, 48.8566]])
        assert result is not None
        assert 330 < result < 350

    def test_three_centroids_returns_max(self):
        c1 = [0.0, 0.0]
        c2 = [1.0, 0.0]
        c3 = [10.0, 0.0]
        result = _max_spread_km([c1, c2, c3])
        assert result is not None
        d_1_3 = _haversine_km(*c1, *c3)  # type: ignore[arg-type]
        assert abs(result - round(d_1_3, 3)) < 0.001


class TestExtractEnrichmentSet:
    def test_empty_enrichment_returns_empty(self):
        assert _extract_enrichment_set({}) == []

    def test_enrichment_with_manifest_but_no_known_keys_returns_generic(self):
        result = _extract_enrichment_set({"manifest_path": "s3://bucket/manifest.json"})
        assert result == ["enrichment"]

    def test_enrichment_with_ndvi_stats_key(self):
        """ndvi_stats/ndvi_raster_paths/ndvi_search_ids are the real keys
        treesight.pipeline.enrichment.runner writes, not "ndvi"."""
        result = _extract_enrichment_set({"manifest_path": "s3://bucket/m.json", "ndvi_stats": [{"scene_id": "s1"}]})
        assert "ndvi" in result

    def test_ndvi_stats_list_of_only_none_is_not_counted(self):
        """ndvi_stats is pre-sized with None placeholders for every frame —
        a non-empty list of Nones must not be mistaken for real NDVI data."""
        result = _extract_enrichment_set({"manifest_path": "s3://bucket/m.json", "ndvi_stats": [None, None]})
        assert result == ["enrichment"]

    def test_enrichment_with_weather_daily_key(self):
        result = _extract_enrichment_set(
            {"manifest_path": "s3://bucket/m.json", "weather_daily": {"dates": ["2026-01-01"]}}
        )
        assert "weather" in result

    def test_weather_daily_none_is_not_counted(self):
        result = _extract_enrichment_set({"manifest_path": "s3://bucket/m.json", "weather_daily": None})
        assert result == ["enrichment"]

    def test_enrichment_with_mosaic_search_ids_key(self):
        result = _extract_enrichment_set({"manifest_path": "s3://bucket/m.json", "search_ids": ["id-1"]})
        assert "mosaic" in result

    def test_enrichment_with_change_detection_key(self):
        result = _extract_enrichment_set(
            {
                "manifest_path": "s3://bucket/m.json",
                "change_detection": {"season_changes": [1]},
            }
        )
        assert "change_detection" in result

    def test_no_manifest_returns_empty(self):
        assert _extract_enrichment_set({"ndvi_stats": [{"scene_id": "s1"}]}) == []


class TestBuildStatsDocument:
    def _default_kwargs(self):
        return {
            "instance_id": "inst-123",
            "user_id": "user-abc",
            "tier": "pro",
            "aoi_count": 3,
            "aoi_area_by_name": {"field_a": 50.0, "field_b": 30.0, "field_c": 20.0},
            "aoi_centroids": [[10.0, 20.0], [11.0, 21.0], [12.0, 22.0]],
            "image_count": 7,
            "batch_used": False,
            "enrichment": {},
        }

    def test_document_id_matches_instance_id(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["id"] == "inst-123"
        assert doc["instance_id"] == "inst-123"

    def test_total_area_km2_is_sum_of_ha_divided_by_100(self):
        doc = build_stats_document(**self._default_kwargs())
        # 50 + 30 + 20 = 100 ha → 1.0 km²
        assert doc["total_area_km2"] == 1.0

    def test_max_spread_km_is_computed(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["max_spread_km"] is not None
        assert doc["max_spread_km"] > 0

    def test_user_id_partition_key(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["user_id"] == "user-abc"

    def test_tier_field(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["tier"] == "pro"

    def test_image_count(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["image_count"] == 7

    def test_batch_used_false(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["batch_used"] is False

    def test_batch_used_true(self):
        kwargs = self._default_kwargs()
        kwargs["batch_used"] = True
        doc = build_stats_document(**kwargs)
        assert doc["batch_used"] is True

    def test_status_completed(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["status"] == "completed"

    def test_empty_aoi_area_leaves_total_as_none(self):
        kwargs = self._default_kwargs()
        kwargs["aoi_area_by_name"] = {}
        doc = build_stats_document(**kwargs)
        assert doc["total_area_km2"] is None

    def test_no_centroids_leaves_spread_as_none(self):
        kwargs = self._default_kwargs()
        kwargs["aoi_centroids"] = []
        doc = build_stats_document(**kwargs)
        assert doc["max_spread_km"] is None

    def test_duration_computed_when_both_timestamps_provided(self):
        kwargs = self._default_kwargs()
        kwargs["started_at"] = "2026-08-08T10:00:00+00:00"
        kwargs["completed_at"] = "2026-08-08T10:01:30+00:00"
        doc = build_stats_document(**kwargs)
        assert doc["duration_s"] == 90.0

    def test_duration_none_when_started_at_missing(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["duration_s"] is None

    def test_timestamp_field_present(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["timestamp"]

    def test_enrichment_set_empty_when_no_manifest(self):
        doc = build_stats_document(**self._default_kwargs())
        assert doc["enrichment_set"] == []

    def test_required_schema_fields_all_present(self):
        doc = build_stats_document(**self._default_kwargs())
        required = {
            "id",
            "user_id",
            "instance_id",
            "timestamp",
            "status",
            "tier",
            "aoi_count",
            "total_area_km2",
            "max_spread_km",
            "enrichment_set",
            "image_count",
            "duration_s",
            "batch_used",
        }
        assert required.issubset(doc.keys())


class TestWritePipelineStatsActivity:
    """Integration-style tests for the write_pipeline_stats activity function."""

    def _make_payload(self, **overrides):
        base = {
            "instance_id": "inst-orch-1",
            "user_id": "u1",
            "tier": "free",
            "aoi_count": 1,
            "aoi_area_by_name": {"field": 10.0},
            "aoi_centroids": [[5.0, 10.0]],
            "image_count": 3,
            "batch_used": False,
            "enrichment": {},
            "status": "completed",
        }
        base.update(overrides)
        return base

    def test_skips_write_when_cosmos_unavailable(self):
        from blueprints.pipeline.activities import write_pipeline_stats

        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            result = write_pipeline_stats(self._make_payload())

        assert result["written"] is False
        assert result["reason"] == "cosmos_unavailable"

    def test_writes_document_when_cosmos_available(self):
        from blueprints.pipeline.activities import write_pipeline_stats

        mock_upsert = MagicMock(return_value={})
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.upsert_item", mock_upsert),
        ):
            result = write_pipeline_stats(self._make_payload())

        assert result["written"] is True
        assert result["instance_id"] == "inst-orch-1"
        mock_upsert.assert_called_once()
        container_name, doc = mock_upsert.call_args[0]
        assert container_name == "pipeline_stats"
        assert doc["id"] == "inst-orch-1"
        assert doc["user_id"] == "u1"
        assert doc["status"] == "completed"

    def test_never_raises_when_instance_id_missing(self):
        """The activity's contract is 'never raises' — a malformed payload
        must return {"written": False}, not propagate a KeyError as a
        Durable activity failure."""
        from blueprints.pipeline.activities import write_pipeline_stats

        payload = self._make_payload()
        del payload["instance_id"]

        with patch("treesight.storage.cosmos.cosmos_available", return_value=True):
            result = write_pipeline_stats(payload)

        assert result == {"written": False, "reason": "error"}

    def test_never_raises_on_cosmos_upsert_failure(self):
        from blueprints.pipeline.activities import write_pipeline_stats

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.upsert_item", side_effect=RuntimeError("boom")),
        ):
            result = write_pipeline_stats(self._make_payload())

        assert result == {"written": False, "reason": "error"}
