"""Tests for the enrichment runner's parallel execution paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from treesight.pipeline.enrichment.runner import (
    _run_mosaic_ndvi_phase,
    enrich_data_sources,
    enrich_finalize,
    enrich_imagery,
    enrich_single_aoi_step,
    run_enrichment,
)


def _make_frame(
    year: int = 2024,
    season: str = "spring",
    collection: str = "sentinel-2-l2a",
    is_naip: bool = False,
) -> dict:
    return {
        "year": year,
        "season": season,
        "collection": collection,
        "is_naip": is_naip,
        "start": "2024-03-01",
        "end": "2024-06-01",
    }


BBOX = [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0]]
COORDS = [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]]


class TestMosaicNdviParallel:
    """Verify _run_mosaic_ndvi_phase parallelization correctness."""

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_results_at_correct_indices(self, mock_mosaic, mock_ndvi):
        """Each frame's result must land at its original index, not arrival order."""
        frames = [
            _make_frame(year=2024, season="spring"),
            _make_frame(year=2024, season="summer"),
            _make_frame(year=2024, season="autumn"),
        ]
        # Each mosaic call returns a unique search ID
        mock_mosaic.side_effect = lambda coll, start, end, bbox, extra, cl: f"sid-{start}-{coll}"
        # Each NDVI call returns stats keyed by year+season for traceability
        mock_ndvi.side_effect = lambda bbox, start, end: {"mean": 0.5, "scene_id": f"s-{start}"}
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(
            BBOX, COORDS, frames, "proj", "ts", "out", storage, results
        )

        assert len(stats) == 3
        assert len(raster_paths) == 3
        # search_ids should all be populated
        assert all(s is not None for s in results["search_ids"])
        # stats should all be populated
        assert all(s is not None for s in stats)

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_mosaic_failure_does_not_abort_others(self, mock_mosaic, mock_ndvi):
        """If one mosaic registration raises, other frames still succeed."""
        frames = [
            _make_frame(year=2024, season="spring"),
            _make_frame(year=2024, season="summer"),
            _make_frame(year=2024, season="autumn"),
        ]
        call_count = 0

        def _mosaic_side_effect(coll, start, end, bbox, extra, cl):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("PC API down")
            return f"sid-{call_count}"

        mock_mosaic.side_effect = _mosaic_side_effect
        mock_ndvi.return_value = {"mean": 0.5}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        # At least 2 of 3 search_ids should be populated (one frame failed)
        populated = [s for s in results["search_ids"] if s is not None]
        assert len(populated) >= 2

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_ndvi_failure_does_not_abort_others(self, mock_mosaic, mock_ndvi):
        """If one NDVI computation raises, other frames still succeed."""
        frames = [
            _make_frame(year=2024, season="spring"),
            _make_frame(year=2024, season="summer"),
        ]
        mock_mosaic.return_value = "sid-1"
        call_count = 0

        def _ndvi_side_effect(bbox, start, end):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("STAC search failed")
            return {"mean": 0.6}

        mock_ndvi.side_effect = _ndvi_side_effect
        storage = MagicMock()
        results: dict = {}

        stats, _ = _run_mosaic_ndvi_phase(
            BBOX, COORDS, frames, "proj", "ts", "out", storage, results
        )

        # One should have succeeded, one should be None
        populated = [s for s in stats if s is not None]
        assert len(populated) >= 1

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_naip_frame_registers_both_collections(self, mock_mosaic, mock_ndvi):
        """NAIP frames register both NAIP and sentinel-2-l2a for NDVI."""
        frames = [_make_frame(collection="naip", is_naip=True)]
        sids = []
        mock_mosaic.side_effect = lambda coll, start, end, bbox, extra, cl: (
            sids.append(coll) or f"sid-{coll}"
        )
        mock_ndvi.return_value = {"mean": 0.5}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        assert "naip" in sids
        assert "sentinel-2-l2a" in sids
        # search_id should be NAIP, ndvi_search_id should be S2
        assert results["search_ids"][0] == "sid-naip"
        assert results["ndvi_search_ids"][0] == "sid-sentinel-2-l2a"

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_skips_visual_registration_when_rgb_is_unsuitable(self, mock_mosaic, mock_ndvi):
        """Tiny coarse frames should skip RGB mosaic registration but keep NDVI search."""
        frames = [
            {
                **_make_frame(collection="sentinel-2-l2a", is_naip=False),
                "rgb_display_suitable": False,
                "preferred_layer": "ndvi",
            }
        ]
        mock_mosaic.return_value = "sid-sentinel-2-l2a"
        mock_ndvi.return_value = {"mean": 0.5}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        mock_mosaic.assert_called_once()
        assert results["search_ids"][0] is None
        assert results["ndvi_search_ids"][0] == "sid-sentinel-2-l2a"

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_frame_plan_records_normalized_provenance(self, mock_mosaic, mock_ndvi):
        """Each frame should carry a normalized provenance bundle for viewer/export use."""
        frames = [_make_frame(collection="sentinel-2-l2a", is_naip=False)]
        mock_mosaic.return_value = "sid-sentinel-2-l2a"
        mock_ndvi.return_value = {
            "mean": 0.5,
            "scene_id": "S2A_123",
            "cloud_cover": 8.5,
            "datetime": "2024-03-17T10:20:00Z",
        }
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        provenance = frames[0].get("provenance")
        assert provenance is not None
        assert provenance["collection"] == "sentinel-2-l2a"
        assert provenance["display_search_id"] == "sid-sentinel-2-l2a"
        assert provenance["ndvi_scene_id"] == "S2A_123"
        assert provenance["resolution_m"] == 10.0

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_cog_result_with_geotiff_uploads_raster(self, mock_mosaic, mock_ndvi):
        """When compute_ndvi returns geotiff_bytes, the raster is uploaded."""
        frames = [_make_frame(year=2025, season="winter")]
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = {
            "mean": 0.7,
            "scene_id": "S2A_123",
            "geotiff_bytes": b"\x00TIFF",
        }
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(
            BBOX, COORDS, frames, "proj", "ts", "out", storage, results
        )

        storage.upload_bytes.assert_called_once()
        call_args = storage.upload_bytes.call_args
        assert "2025_winter.tif" in call_args[0][1]
        assert raster_paths[0] is not None
        # geotiff_bytes should be stripped from stats
        assert stats[0] is not None
        assert "geotiff_bytes" not in stats[0]

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_empty_frame_plan_returns_empty(self, mock_mosaic, mock_ndvi):
        """An empty frame plan should return empty lists without error."""
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(
            BBOX, COORDS, [], "proj", "ts", "out", storage, results
        )

        assert stats == []
        assert raster_paths == []
        mock_mosaic.assert_not_called()
        mock_ndvi.assert_not_called()

    @patch("treesight.pipeline.enrichment.runner.fetch_ndvi_stat")
    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_fallback_to_tile_when_cog_returns_none(self, mock_mosaic, mock_ndvi, mock_fetch_stat):
        """When compute_ndvi returns None, fall back to tile-based fetch_ndvi_stat."""
        frames = [_make_frame()]
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = None
        mock_fetch_stat.return_value = {"mean": 0.4}
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(
            BBOX, COORDS, frames, "proj", "ts", "out", storage, results
        )

        mock_fetch_stat.assert_called_once()
        assert stats[0] == {"mean": 0.4}
        assert raster_paths[0] is None


class TestPerAoiEnrichment:
    """Verify per-AOI enrichment fan-out in run_enrichment (#578)."""

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_enrichment_runs_per_aoi(
        self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change
    ):
        """With per_aoi_coords containing 2+ AOIs, each gets its own enrichment."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        per_aoi = [
            {"name": "Farm A", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 100},
            {"name": "Farm B", "coords": [[30, 1], [30, 2], [31, 2]], "area_ha": 200},
        ]

        result = run_enrichment(
            coords=[[-50, -10], [30, 1]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert "per_aoi_enrichment" in result
        assert len(result["per_aoi_enrichment"]) == 2
        assert result["per_aoi_enrichment"][0]["name"] == "Farm A"
        assert result["per_aoi_enrichment"][1]["name"] == "Farm B"

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_single_aoi_skips_per_aoi(
        self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change
    ):
        """With only 1 AOI, per-AOI enrichment is not triggered."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        per_aoi = [
            {"name": "Solo Farm", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 50},
        ]

        result = run_enrichment(
            coords=[[-50, -10], [-50, -9], [-49, -9]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert "per_aoi_enrichment" not in result

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_failure_does_not_abort(
        self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change
    ):
        """If one AOI's enrichment fails, others still succeed."""
        call_count = 0

        def plan_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:  # 3rd call is 2nd per-AOI (1 main + 2 per-AOI)
                raise RuntimeError("API limit hit")
            return [{"start": "2024-01-01", "end": "2024-03-01"}]

        mock_plan.side_effect = plan_side_effect
        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        per_aoi = [
            {"name": "Farm A", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 100},
            {"name": "Farm B", "coords": [[30, 1], [30, 2], [31, 2]], "area_ha": 200},
        ]

        result = run_enrichment(
            coords=[[-50, -10], [30, 1]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert "per_aoi_enrichment" in result
        assert len(result["per_aoi_enrichment"]) == 2
        # One succeeded, one failed
        errors = [r for r in result["per_aoi_enrichment"] if "error" in r]
        successes = [r for r in result["per_aoi_enrichment"] if "error" not in r]
        assert len(errors) == 1
        assert len(successes) == 1
        assert errors[0]["name"] == "Farm B"


class TestCollectPerAoiCoords:
    """Test _collect_per_aoi_coords helper (#578)."""

    def test_extracts_from_exterior_coords(self):
        from blueprints.pipeline._helpers import _collect_per_aoi_coords

        aois = [
            {
                "feature_name": "Farm A",
                "exterior_coords": [[-50, -10], [-50, -9], [-49, -9]],
                "area_ha": 100,
            },
            {
                "feature_name": "Farm B",
                "exterior_coords": [[30, 1], [30, 2], [31, 2]],
                "area_ha": 200,
            },
        ]
        result = _collect_per_aoi_coords(aois)
        assert len(result) == 2
        assert result[0]["name"] == "Farm A"
        assert result[0]["coords"] == [[-50, -10], [-50, -9], [-49, -9]]
        assert result[1]["area_ha"] == 200

    def test_falls_back_to_bbox(self):
        from blueprints.pipeline._helpers import _collect_per_aoi_coords

        aois = [{"feature_name": "Box", "bbox": [-50, -10, -49, -9], "area_ha": 50}]
        result = _collect_per_aoi_coords(aois)
        assert len(result) == 1
        assert len(result[0]["coords"]) == 5  # bbox → closed ring

    def test_skips_aois_without_coords(self):
        from blueprints.pipeline._helpers import _collect_per_aoi_coords

        aois = [
            {"feature_name": "Good", "exterior_coords": [[1, 2], [3, 4]]},
            {"feature_name": "Empty"},
        ]
        result = _collect_per_aoi_coords(aois)
        assert len(result) == 1
        assert result[0]["name"] == "Good"


# ---------------------------------------------------------------------------
# Sub-step function tests (#574 — parallel enrichment fan-out)
# ---------------------------------------------------------------------------


class TestEnrichDataSources:
    """Verify enrich_data_sources returns weather/flood/fire results."""

    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_returns_frame_plan_and_center(self, mock_plan, mock_weather, mock_flood):
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-06-01"}]
        result = enrich_data_sources(COORDS)
        assert "frame_plan" in result
        assert "center" in result
        assert "bbox" in result
        mock_weather.assert_called_once()
        mock_flood.assert_called_once()

    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_returns_early_on_empty_frame_plan(self, mock_plan):
        mock_plan.return_value = []
        result = enrich_data_sources(COORDS)
        assert result["frame_plan"] == []
        assert "enriched_at" in result

    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_eudr_mode_runs_eudr_phase(self, mock_plan, mock_weather, mock_flood, mock_eudr):
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-06-01"}]
        result = enrich_data_sources(COORDS, eudr_mode=True)
        mock_eudr.assert_called_once()
        assert result.get("eudr_mode") is True


class TestEnrichImagery:
    """Verify enrich_imagery returns mosaic/NDVI/change-detection results."""

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_runs_mosaic_and_change_detection(self, mock_plan, mock_mosaic, mock_change):
        mock_plan.return_value = [_make_frame()]
        mock_mosaic.return_value = ({}, {})
        storage = MagicMock()
        result = enrich_imagery(
            COORDS,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        mock_mosaic.assert_called_once()
        mock_change.assert_called_once()
        assert isinstance(result, dict)

    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_empty_frame_plan_returns_empty(self, mock_plan):
        mock_plan.return_value = []
        storage = MagicMock()
        result = enrich_imagery(
            COORDS,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result == {}

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_returns_annotated_frame_plan_for_finalize(self, mock_plan, mock_mosaic, mock_change):
        frame_plan = [_make_frame()]
        mock_plan.return_value = frame_plan

        def annotate_frame(*args, **kwargs):
            frame_plan[0]["label"] = "Spring 2024"
            frame_plan[0]["provenance"] = {"ndvi_scene_id": "S2A_123"}
            return ({}, {})

        mock_mosaic.side_effect = annotate_frame
        storage = MagicMock()

        result = enrich_imagery(
            COORDS,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )

        assert result["frame_plan"][0]["label"] == "Spring 2024"
        assert result["frame_plan"][0]["provenance"]["ndvi_scene_id"] == "S2A_123"


class TestEnrichSingleAoiStep:
    """Verify enrich_single_aoi_step wraps _enrich_single_aoi with error containment."""

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    def test_returns_aoi_result(self, mock_inner):
        mock_inner.return_value = {"name": "forest-a", "ndvi": 0.7}
        storage = MagicMock()
        result = enrich_single_aoi_step(
            {"name": "forest-a", "coords": [[1, 2]]},
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result["name"] == "forest-a"
        assert "error" not in result

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    def test_contains_error_on_failure(self, mock_inner):
        mock_inner.side_effect = RuntimeError("boom")
        storage = MagicMock()
        result = enrich_single_aoi_step(
            {"name": "bad-aoi", "coords": [[1, 2]]},
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result["error"] == "enrichment_failed"
        assert result["name"] == "bad-aoi"


class TestEnrichFinalize:
    """Verify enrich_finalize merges results and stores manifest."""

    def test_merges_data_sources_and_imagery(self):
        storage = MagicMock()
        result = enrich_finalize(
            {"weather": {"temp": 20}, "frame_plan": []},
            {"ndvi": {"mean": 0.5}},
            [],
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result["weather"] == {"temp": 20}
        assert result["ndvi"] == {"mean": 0.5}
        assert "enriched_at" in result
        assert "manifest_path" in result
        storage.upload_json.assert_called_once()

    def test_includes_per_aoi_results(self):
        storage = MagicMock()
        per_aoi = [{"name": "a"}, {"name": "b", "error": "enrichment_failed"}]
        result = enrich_finalize(
            {"frame_plan": []},
            {},
            per_aoi,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert len(result["per_aoi_enrichment"]) == 2

    @patch("treesight.pipeline.enrichment.determination.determine_deforestation_free")
    def test_eudr_mode_runs_determination(self, mock_det):
        mock_det.return_value = {"status": "compliant"}
        storage = MagicMock()
        result = enrich_finalize(
            {},
            {},
            [],
            eudr_mode=True,
            date_start="2021-01-01",
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result["eudr_mode"] is True
        assert result["determination"] == {"status": "compliant"}
