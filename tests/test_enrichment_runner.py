"""Tests for the enrichment runner's parallel execution paths."""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from treesight.pipeline.enrichment.runner import (
    _SAFE_MODE_ALL_SKIPS,
    _enrich_single_aoi,
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


@pytest.fixture(autouse=True)
def _block_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast if enrichment tests try to open real network sockets."""

    def _deny_network(*args, **kwargs):
        raise AssertionError("Network access is not allowed in enrichment runner tests.")

    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)


class TestMosaicNdviParallel:
    """Verify _run_mosaic_ndvi_phase parallelization correctness."""

    @pytest.fixture(autouse=True)
    def real_provider_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANOPEX_TEST_MODE", "0")

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
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
        mock_ndvi.side_effect = lambda bbox, start, end, geometry=None: {"mean": 0.5, "scene_id": f"s-{start}"}
        storage = MagicMock()
        results: dict = {}
        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}

        stats, raster_paths = _run_mosaic_ndvi_phase(
            BBOX,
            COORDS,
            frames,
            "proj",
            "ts",
            "out",
            storage,
            results,
            geometry=geometry,
        )

        assert len(stats) == 3
        assert len(raster_paths) == 3
        # search_ids should all be populated
        assert all(s is not None for s in results["search_ids"])
        # stats should all be populated
        assert all(s is not None for s in stats)
        assert all(call.kwargs["geometry"] == geometry for call in mock_ndvi.call_args_list)

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_frame_pools_use_configured_concurrency(self, mock_mosaic, mock_ndvi, monkeypatch):
        worker_counts: list[int | None] = []

        class TrackingPool(ThreadPoolExecutor):
            def __init__(self, max_workers=None, *args, **kwargs):
                worker_counts.append(max_workers)
                super().__init__(max_workers, *args, **kwargs)

        monkeypatch.setattr("treesight.pipeline.enrichment._phase_runners.DEFAULT_ENRICHMENT_FRAME_CONCURRENCY", 1)
        monkeypatch.setattr("treesight.pipeline.enrichment._phase_runners.ThreadPoolExecutor", TrackingPool)
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = {"mean": 0.5}

        _run_mosaic_ndvi_phase(
            BBOX,
            COORDS,
            [_make_frame(), _make_frame(season="summer")],
            "proj",
            "ts",
            "out",
            MagicMock(),
            {},
        )

        assert worker_counts == [1, 1]

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
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

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
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

        stats, _ = _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        # One should have succeeded, one should be None
        populated = [s for s in stats if s is not None]
        assert len(populated) >= 1

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_naip_frame_registers_both_collections(self, mock_mosaic, mock_ndvi):
        """NAIP frames register both NAIP and sentinel-2-l2a for NDVI."""
        frames = [_make_frame(collection="naip", is_naip=True)]
        sids = []
        mock_mosaic.side_effect = lambda coll, start, end, bbox, extra, cl: sids.append(coll) or f"sid-{coll}"
        mock_ndvi.return_value = {"mean": 0.5}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        assert "naip" in sids
        assert "sentinel-2-l2a" in sids
        # search_id should be NAIP, ndvi_search_id should be S2
        assert results["search_ids"][0] == "sid-naip"
        assert results["ndvi_search_ids"][0] == "sid-sentinel-2-l2a"

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_naip_rgb_falls_back_to_sentinel_when_naip_missing(self, mock_mosaic, mock_ndvi):
        """If NAIP has no RGB mosaic for a frame, Sentinel-2 should be used for display."""
        frames = [_make_frame(collection="naip", is_naip=True)]

        def _mosaic_side_effect(coll, start, end, bbox, extra, cl):
            if coll == "naip":
                return None
            return "sid-sentinel-2-l2a"

        mock_mosaic.side_effect = _mosaic_side_effect
        mock_ndvi.return_value = {"mean": 0.5}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        assert results["search_ids"][0] == "sid-sentinel-2-l2a"
        assert results["display_collections"][0] == "sentinel-2-l2a"
        assert frames[0]["display_collection"] == "sentinel-2-l2a"

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
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

    @patch("treesight.pipeline.enrichment._phase_runners.compute_landsat_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_landsat_unsuitable_rgb_still_registers_s2_ndvi(self, mock_mosaic, mock_landsat_ndvi):
        """Landsat frames with rgb_display_suitable=False must still register an S2 NDVI mosaic.

        Previously the Landsat fallback branch was missing, leaving ndvi_search_ids[idx]=None
        which disabled tile-based NDVI for that frame entirely.
        """
        frames = [
            {
                **_make_frame(collection="landsat-c2-l2", is_naip=False),
                "rgb_display_suitable": False,
                "preferred_layer": "ndvi",
            }
        ]
        mock_mosaic.return_value = "sid-sentinel-2-l2a"
        mock_landsat_ndvi.return_value = {"mean": 0.4}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        # RGB mosaic skipped — search_ids[0] must be None
        assert results["search_ids"][0] is None
        # But a Sentinel-2 NDVI mosaic must have been registered as fallback
        assert results["ndvi_search_ids"][0] == "sid-sentinel-2-l2a"
        mock_mosaic.assert_called_once()
        mock_landsat_ndvi.assert_called_once()

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
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

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
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

        stats, raster_paths = _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        storage.upload_bytes.assert_called_once()
        call_args = storage.upload_bytes.call_args
        assert "2025_winter.tif" in call_args[0][1]
        assert raster_paths[0] is not None
        # geotiff_bytes should be stripped from stats
        assert stats[0] is not None
        assert "geotiff_bytes" not in stats[0]

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_aoi_index_scopes_raster_path_to_avoid_cross_aoi_collision(self, mock_mosaic, mock_ndvi):
        """Two AOIs enriched under the same project_name/timestamp (the normal case
        for a multi-parcel submission) must never write their NDVI raster to the
        same blob path (#1425) — otherwise one AOI's change-detection can silently
        read another (unrelated) AOI's raster data.
        """
        frames_a = [_make_frame(year=2024, season="spring")]
        frames_b = [_make_frame(year=2024, season="spring")]
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = {"mean": 0.5, "geotiff_bytes": b"\x00TIFF"}
        storage = MagicMock()

        _, paths_a = _run_mosaic_ndvi_phase(BBOX, COORDS, frames_a, "proj", "ts", "out", storage, {}, aoi_index=0)
        _, paths_b = _run_mosaic_ndvi_phase(BBOX, COORDS, frames_b, "proj", "ts", "out", storage, {}, aoi_index=1)

        assert paths_a[0] != paths_b[0]

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_no_aoi_index_preserves_existing_path_shape(self, mock_mosaic, mock_ndvi):
        """The top-level/union enrichment call (single AOI or whole-submission
        path) never passes aoi_index — its raster path must stay exactly as
        before, unprefixed."""
        frames = [_make_frame(year=2025, season="winter")]
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = {"mean": 0.7, "geotiff_bytes": b"\x00TIFF"}
        storage = MagicMock()

        _, raster_paths = _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, {})

        assert raster_paths[0] == "enrichment/proj/ts/ndvi/2025_winter.tif"

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_empty_frame_plan_returns_empty(self, mock_mosaic, mock_ndvi):
        """An empty frame plan should return empty lists without error."""
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(BBOX, COORDS, [], "proj", "ts", "out", storage, results)

        assert stats == []
        assert raster_paths == []
        mock_mosaic.assert_not_called()
        mock_ndvi.assert_not_called()

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_does_not_use_unmasked_tile_fallback_when_cog_returns_none(self, mock_mosaic, mock_ndvi):
        """Tile statistics cannot substitute for plot-masked COG statistics."""
        frames = [_make_frame()]
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = None
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        assert stats[0] is None
        assert raster_paths[0] is None

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_no_mosaic_and_no_cog_returns_none_stat(self, mock_mosaic, mock_ndvi):
        """When mosaic registration and the COG path both fail, no tile fallback is possible."""
        frames = [_make_frame()]
        mock_mosaic.return_value = None
        mock_ndvi.return_value = None
        storage = MagicMock()
        results: dict = {}

        stats, raster_paths = _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results)

        assert stats[0] is None
        assert raster_paths[0] is None

    @patch("treesight.pipeline.enrichment._phase_runners.compute_ndvi")
    @patch("treesight.pipeline.enrichment._phase_runners.register_mosaic")
    def test_records_resource_accumulator_metrics(self, mock_mosaic, mock_ndvi):
        """The optional ResourceAccumulator must record mosaic/NDVI/S2 usage."""
        from treesight.pipeline.enrichment.resource_accumulator import ResourceAccumulator

        frames = [_make_frame(collection="sentinel-2-l2a")]
        mock_mosaic.return_value = "sid-1"
        mock_ndvi.return_value = {"mean": 0.5, "scene_id": "s-1"}
        storage = MagicMock()
        results: dict = {}
        acc = ResourceAccumulator()

        _run_mosaic_ndvi_phase(BBOX, COORDS, frames, "proj", "ts", "out", storage, results, acc=acc)

        acc_dict = acc.to_dict()
        assert acc_dict["mosaic_registrations"] == 1
        assert acc_dict["ndvi_computations"] == 1
        assert acc_dict["sentinel2_scenes_registered"] == 1
        assert "sentinel-2-l2a" in acc_dict["data_sources_queried"]
        assert acc_dict["api_calls"]["planetary_computer"] == 2


class TestPerAoiEnrichment:
    """Verify per-AOI enrichment fan-out in run_enrichment (#578)."""

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_enrichment_runs_per_aoi(self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change):
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
    def test_single_aoi_emits_canonical_per_aoi_entry(
        self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change
    ):
        """With 1 AOI, the manifest still exposes canonical per-AOI evidence."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        unscoped_path = "enrichment/test/20240101/ndvi/2024_spring.tif"
        mock_mosaic.return_value = ([{"mean": 0.42}], [unscoped_path])
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Solo Farm",
                "coords": [[-50, -10], [-50, -9], [-49, -9]],
                "area_ha": 50,
                "source_geometry_type": "polygon",
                "plot_area_ha": 49.5,
            },
        ]

        result = run_enrichment(
            coords=[[-50, -10], [-50, -9], [-49, -9]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert result["schema_version"] == "enrichment-manifest/v2"
        assert len(result["per_aoi_enrichment"]) == 1
        entry = result["per_aoi_enrichment"][0]
        assert entry["aoi_index"] == 0
        assert entry["name"] == "Solo Farm"
        assert entry["area_ha"] == 50
        assert entry["coords"] == per_aoi[0]["coords"]
        assert entry["source_geometry_type"] == "polygon"
        assert entry["plot_area_ha"] == 49.5
        assert entry["ndvi_raster_paths"] == [unscoped_path]
        assert "/aoi-0/" not in entry["ndvi_raster_paths"][0]

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_failure_does_not_abort(self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change):
        """If one AOI's enrichment fails, others still succeed."""

        def enrich_side_effect(entry, **kwargs):
            if entry.get("name") == "Farm B":
                raise RuntimeError("API limit hit")
            return {"name": entry.get("name", "")}

        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        per_aoi = [
            {"name": "Farm A", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 100},
            {"name": "Farm B", "coords": [[30, 1], [30, 2], [31, 2]], "area_ha": 200},
        ]

        with patch(
            "treesight.pipeline.enrichment.runner._enrich_single_aoi",
            side_effect=enrich_side_effect,
        ):
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
        errors = [r for r in result["per_aoi_enrichment"] if "error" in r]
        successes = [r for r in result["per_aoi_enrichment"] if "error" not in r]
        assert len(errors) == 1
        assert len(successes) == 1
        assert errors[0]["name"] == "Farm B"

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_uses_thread_pool(self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change):
        """Per-AOI loop uses ThreadPoolExecutor — not a plain serial for-loop (#863)."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        per_aoi = [{"name": f"Farm {i}", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 10} for i in range(4)]

        submitted: list[int] = []
        real_tpe = ThreadPoolExecutor

        class _TrackingTPE(real_tpe):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                submitted.append(kwargs.get("max_workers") or (args[0] if args else None))

        with patch("treesight.pipeline.enrichment.runner.ThreadPoolExecutor", _TrackingTPE):
            run_enrichment(
                coords=[[-50, -10], [-50, -9], [-49, -9]],
                project_name="test",
                timestamp="20240101",
                output_container="out",
                storage=storage,
                per_aoi_coords=per_aoi,
            )

        # At least one pool was created for the per-AOI fan-out
        assert len(submitted) >= 1

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_results_preserve_order(self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change):
        """Results list preserves submission order even when tasks complete out-of-order (#863)."""
        import threading

        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        lock = threading.Lock()
        started = 0
        overlap_observed = threading.Event()

        def plan_side_effect(*args, **kwargs):
            # Infer which AOI this call is for via centre coords
            return [{"start": "2024-01-01", "end": "2024-03-01"}]

        def slow_enrich(entry, **kwargs):
            nonlocal started
            with lock:
                started += 1
                if started >= 2:
                    overlap_observed.set()
            assert overlap_observed.wait(timeout=1), "Per-AOI tasks did not overlap; expected concurrent execution."
            idx = int(entry["name"].split()[-1])
            return {"name": entry["name"], "ndvi": idx}

        mock_plan.side_effect = plan_side_effect

        per_aoi = [{"name": f"Farm {i}", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 10} for i in range(3)]

        with patch("treesight.pipeline.enrichment.runner._enrich_single_aoi", side_effect=slow_enrich):
            result = run_enrichment(
                coords=[[-50, -10], [-50, -9], [-49, -9]],
                project_name="test",
                timestamp="20240101",
                output_container="out",
                storage=storage,
                per_aoi_coords=per_aoi,
            )

        enrichment = result["per_aoi_enrichment"]
        # Order must match submission regardless of completion order
        assert [r["name"] for r in enrichment] == ["Farm 0", "Farm 1", "Farm 2"]
        # Confirm at least two tasks overlapped in-flight
        assert overlap_observed.is_set()

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_per_aoi_concurrency_uses_default_constant(
        self, mock_plan, mock_weather, mock_flood, mock_mosaic, mock_change
    ):
        """Per-AOI pool is capped at min(DEFAULT_ENRICHMENT_CONCURRENCY, len(aois)) (#863)."""
        from treesight.constants import DEFAULT_ENRICHMENT_CONCURRENCY

        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        storage = MagicMock()

        per_aoi = [{"name": f"Farm {i}", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 10} for i in range(3)]

        seen_workers: list[int | None] = []

        class _CapturingTPE(ThreadPoolExecutor):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                seen_workers.append(kwargs.get("max_workers") or (args[0] if args else None))

        with patch("treesight.pipeline.enrichment.runner.ThreadPoolExecutor", _CapturingTPE):
            run_enrichment(
                coords=[[-50, -10], [-50, -9], [-49, -9]],
                project_name="test",
                timestamp="20240101",
                output_container="out",
                storage=storage,
                per_aoi_coords=per_aoi,
            )

        # Pool is capped: no more workers than AOIs, never exceeds the constant.
        expected = min(DEFAULT_ENRICHMENT_CONCURRENCY, len(per_aoi))
        assert expected in seen_workers


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

    def test_preserves_polygon_holes_without_duplicating_exterior(self):
        from blueprints.pipeline._helpers import _collect_per_aoi_coords

        exterior = [[-50, -10], [-50, -9], [-49, -9], [-50, -10]]
        hole = [[-49.8, -9.8], [-49.8, -9.6], [-49.6, -9.6], [-49.8, -9.8]]
        result = _collect_per_aoi_coords(
            [
                {
                    "feature_name": "Farm A",
                    "exterior_coords": exterior,
                    "interior_coords": [hole],
                    "area_ha": 100,
                }
            ]
        )

        assert result[0]["coords"] == exterior
        assert result[0]["interior_coords"] == [hole]
        assert "geometry" not in result[0]

    def test_activity_coords_flatten_source_exteriors_once(self):
        from blueprints.pipeline._payloads import _collect_per_aoi_enrichment_coords

        first = [[0, 0], [1, 0], [1, 1], [0, 0]]
        second = [[4, 4], [5, 4], [5, 5], [4, 4]]
        hole = [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3], [0.2, 0.2]]

        result = _collect_per_aoi_enrichment_coords(
            [
                {"coords": first, "interior_coords": [hole]},
                {"coords": second, "interior_coords": []},
            ]
        )

        assert result == [*first, *second]

    def test_claim_checked_entries_do_not_carry_large_rings(self):
        import json

        from blueprints.pipeline._payloads import _collect_per_aoi_coords
        from treesight.constants import PAYLOAD_OFFLOAD_THRESHOLD_BYTES

        ring = [[float(index), 0.0] for index in range(10_000)]
        entries = _collect_per_aoi_coords(
            [
                {
                    "feature_name": "Large plot",
                    "exterior_coords": ring,
                    "interior_coords": [ring],
                    "bbox": [0.0, 0.0, 10_000.0, 0.0],
                    "centroid": [5_000.0, 0.0],
                    "area_ha": 10.0,
                }
            ],
            aoi_refs=[{"ref": "claims/run/aoi-0.json", "aoi_claim_index": 0}],
        )

        assert entries[0]["aoi_ref"] == "claims/run/aoi-0.json"
        assert entries[0]["aoi_claim_index"] == 0
        assert "coords" not in entries[0]
        assert "interior_coords" not in entries[0]
        assert len(json.dumps(entries).encode("utf-8")) < PAYLOAD_OFFLOAD_THRESHOLD_BYTES

    def test_five_hundred_claim_refs_fit_durable_payload_budget(self):
        import json

        from blueprints.pipeline._payloads import _collect_per_aoi_coords
        from treesight.constants import PAYLOAD_OFFLOAD_THRESHOLD_BYTES

        aois = [
            {
                "feature_name": f"Farm {index}",
                "exterior_coords": [[float(index), 0.0], [float(index) + 1, 0.0], [float(index), 1.0]],
                "interior_coords": [],
                "area_ha": 1.0,
                "metadata": {"supplier_note": "large" * 100},
            }
            for index in range(500)
        ]
        aoi_refs = [
            {"ref": f"claims/run/aoi_{index}.json", "key": f"Farm {index}", "aoi_claim_index": index}
            for index in range(500)
        ]

        entries = _collect_per_aoi_coords(aois, aoi_refs=aoi_refs)

        assert all(set(entry) == {"aoi_ref", "aoi_claim_index"} for entry in entries)
        assert len(json.dumps(entries).encode("utf-8")) < PAYLOAD_OFFLOAD_THRESHOLD_BYTES

    def test_hydrates_polygon_rings_from_claim_ref(self):
        from blueprints.pipeline._payloads import _hydrate_per_aoi_enrichment_coords
        from treesight.storage.offload import PayloadOffloader

        exterior = [[0, 0], [1, 0], [1, 1], [0, 0]]
        hole = [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3], [0.2, 0.2]]
        aoi_data = {
            "feature_name": "Farm",
            "exterior_coords": exterior,
            "interior_coords": [hole],
        }
        with patch.object(PayloadOffloader, "load_claim", return_value=aoi_data) as load_claim:
            result = _hydrate_per_aoi_enrichment_coords(
                [{"name": "Farm", "aoi_ref": "claims/run/aoi-0.json"}],
                MagicMock(),
            )

        load_claim.assert_called_once_with("claims/run/aoi-0.json")
        assert result[0]["coords"] == exterior
        assert result[0]["interior_coords"] == [hole]

    def test_bbox_fallback_does_not_become_plot_geometry(self):
        from blueprints.pipeline._payloads import _hydrate_per_aoi_enrichment_coords
        from treesight.pipeline.enrichment.runner import _aoi_geometry_from_entry
        from treesight.storage.offload import PayloadOffloader

        fallback_ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        aoi_data = {
            "feature_name": "Empty",
            "exterior_coords": [],
            "interior_coords": [],
            "bbox": [0.0, 0.0, 1.0, 1.0],
        }
        with patch.object(PayloadOffloader, "load_claim", return_value=aoi_data):
            result = _hydrate_per_aoi_enrichment_coords(
                [{"name": "Empty", "aoi_ref": "claims/run/aoi-0.json", "coords": fallback_ring}],
                MagicMock(),
            )

        assert result[0]["coords"] == fallback_ring
        assert result[0]["interior_coords"] is None
        assert _aoi_geometry_from_entry(result[0]) is None

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


class TestCombineAoiGeometries:
    def test_kml_multipolygon_parts_form_union_geometry(self, multi_polygon_kml_bytes: bytes):
        from blueprints.pipeline._payloads import _collect_per_aoi_coords
        from treesight.geo import prepare_aoi
        from treesight.parsers.lxml_parser import parse_kml_lxml
        from treesight.pipeline.enrichment.runner import _combine_aoi_geometries

        features = parse_kml_lxml(multi_polygon_kml_bytes, source_file="multi.kml")
        aois = [prepare_aoi(feature).model_dump() for feature in features]
        per_aoi = _collect_per_aoi_coords(aois)

        geometry = _combine_aoi_geometries(per_aoi)

        assert len(per_aoi) == 2
        assert geometry == {
            "type": "MultiPolygon",
            "coordinates": [[feature.exterior_coords] for feature in features],
        }

    def test_combines_parcels_without_filling_the_space_between_them(self):
        from treesight.pipeline.enrichment.runner import _combine_aoi_geometries

        first_coords = [[0, 0], [1, 0], [1, 1], [0, 0]]
        second_coords = [[4, 4], [5, 4], [5, 5], [4, 4]]
        second_hole = [[4.2, 4.2], [4.3, 4.2], [4.3, 4.3], [4.2, 4.2]]

        result = _combine_aoi_geometries(
            [
                {"coords": first_coords, "interior_coords": []},
                {"coords": second_coords, "interior_coords": [second_hole]},
            ]
        )

        assert result == {
            "type": "MultiPolygon",
            "coordinates": [[first_coords], [second_coords, second_hole]],
        }

    def test_returns_unavailable_when_any_parcel_geometry_is_missing(self):
        from treesight.pipeline.enrichment.runner import _combine_aoi_geometries

        result = _combine_aoi_geometries([{"coords": [[0, 0], [1, 0], [1, 1], [0, 0]], "interior_coords": []}, {}])

        assert result is None


# ---------------------------------------------------------------------------
# Sub-step function tests (#574 — parallel enrichment fan-out)
# ---------------------------------------------------------------------------


class TestEnrichDataSources:
    """Verify enrich_data_sources returns weather/flood/fire results."""

    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_safe_mode_skips_external_data_sources(self, mock_plan, mock_weather, mock_flood, mock_eudr):
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-06-01"}]

        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_data_sources(COORDS, eudr_mode=True)

        assert result["safe_mode"] is True
        assert result["skipped"] == ["weather", "flood_fire", "eudr_datasets"]
        assert result["frame_plan"] == [{"start": "2024-01-01", "end": "2024-06-01"}]
        assert "center" in result
        mock_weather.assert_not_called()
        mock_flood.assert_not_called()
        mock_eudr.assert_not_called()

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_run_enrichment_safe_mode_preserves_single_aoi_manifest(
        self, mock_plan, mock_weather, mock_flood, mock_eudr, mock_mosaic, mock_change
    ):
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-06-01"}]
        mock_mosaic.return_value = ([{"mean": 0.42}], ["enrichment/p/t/ndvi/2024_spring.tif"])
        storage = MagicMock()

        with patch("treesight.config.SAFE_MODE", True):
            result = run_enrichment(
                COORDS,
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=storage,
                per_aoi_coords=[{"name": "Solo", "coords": COORDS, "area_ha": 1}],
                eudr_mode=True,
            )

        assert result["safe_mode"] is True
        assert result["schema_version"] == "enrichment-manifest/v2"
        assert len(result["per_aoi_enrichment"]) == 1
        assert result["per_aoi_enrichment"][0]["name"] == "Solo"
        assert result["per_aoi_enrichment"][0]["safe_mode"] is True
        assert result["per_aoi_enrichment"][0]["skipped"] == _SAFE_MODE_ALL_SKIPS
        mock_weather.assert_not_called()
        mock_flood.assert_not_called()
        mock_eudr.assert_not_called()
        mock_mosaic.assert_not_called()
        mock_change.assert_not_called()

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_run_enrichment_safe_mode_preserves_multi_aoi_manifest(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-06-01"}]
        storage = MagicMock()
        per_aoi = [
            {"name": "Farm A", "coords": [[-50, -10], [-50, -9], [-49, -9]], "area_ha": 100},
            {"name": "Farm B", "coords": [[30, 1], [30, 2], [31, 2]], "area_ha": 200},
        ]

        with patch("treesight.config.SAFE_MODE", True):
            result = run_enrichment(
                [[-50, -10], [30, 1]],
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=storage,
                per_aoi_coords=per_aoi,
            )

        assert result["safe_mode"] is True
        assert [entry["name"] for entry in result["per_aoi_enrichment"]] == ["Farm A", "Farm B"]
        mock_weather.assert_not_called()
        mock_flood.assert_not_called()
        mock_eudr.assert_not_called()
        mock_mosaic.assert_not_called()
        mock_change.assert_not_called()
        mock_enrich_aoi.assert_not_called()

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
    def test_safe_mode_skips_imagery(self, mock_plan, mock_mosaic, mock_change):
        mock_plan.return_value = [_make_frame()]
        storage = MagicMock()

        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_imagery(
                COORDS,
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=storage,
            )

        assert result["safe_mode"] is True
        assert result["skipped"] == ["mosaic", "ndvi", "change_detection"]
        mock_mosaic.assert_not_called()
        mock_change.assert_not_called()

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

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_safe_mode_skips_imagery_calls(self, mock_plan, mock_mosaic, mock_change):
        mock_plan.return_value = [_make_frame()]
        storage = MagicMock()
        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_imagery(
                COORDS,
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=storage,
            )

        assert result["safe_mode"] is True
        mock_mosaic.assert_not_called()
        mock_change.assert_not_called()


class TestEnrichSingleAoiStep:
    """Verify enrich_single_aoi_step wraps _enrich_single_aoi with error containment."""

    @patch("treesight.pipeline.enrichment.runner.build_frame_plan", return_value=[])
    def test_claim_checked_result_does_not_return_full_coordinates(self, _mock_frame_plan):
        coords = [[float(index), 0.0] for index in range(10_000)]
        result = _enrich_single_aoi(
            {"name": "large", "coords": coords, "interior_coords": []},
            date_start=None,
            date_end=None,
            cadence="maximum",
            max_history_years=None,
            eudr_mode=False,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=MagicMock(),
        )

        assert "coords" not in result
        assert len(str(result)) < 2_000

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    def test_safe_mode_returns_canonical_stub(self, mock_enrich):
        storage = MagicMock()

        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_single_aoi_step(
                {"name": "safe-aoi", "coords": [[1, 2], [1, 3], [2, 3]], "area_ha": 10},
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=storage,
                aoi_index=2,
            )

        assert result["aoi_index"] == 2
        assert result["name"] == "safe-aoi"
        assert result["safe_mode"] is True
        assert result["bbox"]
        assert result["center"]
        mock_enrich.assert_not_called()

    def test_safe_mode_uses_shared_skip_report(self):
        with patch("treesight.config.SAFE_MODE", True):
            result = _enrich_single_aoi(
                {"name": "safe-aoi", "coords": COORDS, "area_ha": 10},
                date_start=None,
                date_end=None,
                cadence="maximum",
                max_history_years=None,
                eudr_mode=False,
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=MagicMock(),
            )

        assert result["skipped"] == _SAFE_MODE_ALL_SKIPS

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

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_safe_mode_skips_external_calls(
        self, mock_plan, mock_weather, mock_flood, mock_eudr, mock_mosaic, mock_change
    ):
        mock_plan.return_value = [_make_frame()]
        storage = MagicMock()
        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_single_aoi_step(
                {"name": "safe-aoi", "coords": COORDS},
                project_name="p",
                timestamp="t",
                output_container="out",
                storage=storage,
            )

        assert result["safe_mode"] is True
        mock_weather.assert_not_called()
        mock_flood.assert_not_called()
        mock_eudr.assert_not_called()
        mock_mosaic.assert_not_called()
        mock_change.assert_not_called()


class TestEnrichFinalize:
    """Verify enrich_finalize merges results and stores manifest."""

    def test_multi_aoi_unavailable_weather_preserves_manifest(self):
        storage = MagicMock()
        per_aoi = [
            {"name": "a", "coords": [[1, 2]], "area_ha": 10},
            {"name": "b", "coords": [[3, 4]], "area_ha": 20},
        ]
        result = enrich_finalize(
            {"frame_plan": []},
            {},
            [{"weather_daily": None}, {"weather_daily": {"temperature": [20]}}],
            per_aoi_coords=per_aoi,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result["per_aoi_enrichment"][0]["weather_daily"] == {}
        assert result["per_aoi_enrichment"][1]["weather_daily"] == {"temperature": [20]}
        storage.upload_json.assert_called_once()

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

    def test_rebuilds_run_coords_from_hydrated_parcels(self):
        storage = MagicMock()
        first = [[0, 0], [1, 0], [1, 1], [0, 0]]
        second = [[4, 4], [5, 4], [5, 5], [4, 4]]

        result = enrich_finalize(
            {"bbox": [[0, 0], [5, 5]], "frame_plan": []},
            {},
            [],
            per_aoi_coords=[
                {"name": "A", "coords": first, "interior_coords": [], "area_ha": 1},
                {"name": "B", "coords": second, "interior_coords": [], "area_ha": 1},
            ],
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )

        assert result["coords"] == [*first, *second]

    def test_includes_per_aoi_results(self):
        storage = MagicMock()
        per_aoi = [
            {"name": "a", "coords": [[1, 2]], "area_ha": 10},
            {"name": "b", "coords": [[3, 4]], "area_ha": 20},
        ]
        per_aoi_results = [{"name": "a"}, {"name": "b", "error": "enrichment_failed"}]
        result = enrich_finalize(
            {"frame_plan": []},
            {},
            per_aoi_results,
            per_aoi_coords=per_aoi,
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert len(result["per_aoi_enrichment"]) == 2
        assert result["per_aoi_enrichment"][0]["aoi_index"] == 0
        assert result["per_aoi_enrichment"][1]["aoi_index"] == 1

    def test_single_aoi_finalize_projects_merged_top_level_evidence(self):
        storage = MagicMock()
        result = enrich_finalize(
            {
                "frame_plan": [{"start": "2024-01-01", "end": "2024-03-01"}],
                "coords": [[-50, -10], [-50, -9], [-49, -9]],
                "bbox": [[-50, -10], [-49, -9]],
                "center": {"lat": -9.5, "lon": -49.5},
                "weather_daily": [{"temp": 20}],
            },
            {
                "ndvi_stats": [{"mean": 0.42}],
                "ndvi_raster_paths": ["enrichment/p/t/ndvi/2024_spring.tif"],
            },
            [],
            per_aoi_coords=[
                {
                    "name": "Solo Farm",
                    "coords": [[-50, -10], [-50, -9], [-49, -9]],
                    "area_ha": 50,
                }
            ],
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )

        assert result["schema_version"] == "enrichment-manifest/v2"
        assert len(result["per_aoi_enrichment"]) == 1
        entry = result["per_aoi_enrichment"][0]
        assert entry["aoi_index"] == 0
        assert entry["name"] == "Solo Farm"
        assert entry["area_ha"] == 50
        assert entry["weather_daily"] == [{"temp": 20}]
        assert entry["ndvi_stats"] == [{"mean": 0.42}]
        assert entry["ndvi_raster_paths"] == ["enrichment/p/t/ndvi/2024_spring.tif"]
        assert "/aoi-0/" not in entry["ndvi_raster_paths"][0]

    def test_single_aoi_finalize_derives_geometry_from_per_aoi_coords(self):
        storage = MagicMock()
        coords = [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0], [-50.0, -10.0]]
        geometry = {
            "type": "Polygon",
            "coordinates": [
                coords,
                [[-49.8, -9.8], [-49.8, -9.7], [-49.7, -9.7], [-49.8, -9.8]],
            ],
        }
        result = enrich_finalize(
            {"safe_mode": True, "frame_plan": []},
            {"safe_mode": True},
            [],
            per_aoi_coords=[
                {"name": "Solo Farm", "coords": coords, "area_ha": 50, "interior_coords": geometry["coordinates"][1:]}
            ],
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )

        entry = result["per_aoi_enrichment"][0]
        assert entry["geometry"] == geometry
        assert entry["bbox"]
        assert entry["center"] == {"lat": -9.5, "lon": -49.5}
        assert entry["safe_mode"] is True
        assert entry["skipped"] == [
            "weather",
            "flood_fire",
            "eudr_datasets",
            "mosaic",
            "ndvi",
            "change_detection",
        ]

    @patch("treesight.pipeline.enrichment.determination.determine_deforestation_free")
    def test_eudr_mode_runs_determination(self, mock_det):
        mock_det.return_value = {"status": "compliant"}
        storage = MagicMock()
        result = enrich_finalize(
            {},
            {},
            [],
            per_aoi_coords=[],
            eudr_mode=True,
            date_start="2021-01-01",
            project_name="p",
            timestamp="t",
            output_container="out",
            storage=storage,
        )
        assert result["eudr_mode"] is True
        assert result["determination"] == {"status": "compliant"}


class TestIsMultiRegion:
    """Unit tests for _is_multi_region helper (#860)."""

    def test_same_location_is_not_multi_region(self):
        """AOIs all at the same centroid are not multi-region."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        aois = [
            {"coords": [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]]},
            {"coords": [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]]},
        ]
        assert not _is_multi_region(aois)

    def test_nearby_aois_within_threshold_not_multi_region(self):
        """AOIs within the same country (< 500 km apart) should not be multi-region."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        # Two AOIs ~100 km apart in Brazil
        aois = [
            {"coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]]},
            {"coords": [[-46.0, -23.0], [-46.0, -22.5], [-45.5, -22.5]]},
        ]
        assert not _is_multi_region(aois)

    def test_continent_spanning_aois_are_multi_region(self):
        """AOIs in Brazil and Indonesia are clearly multi-region (> 500 km)."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        aois = [
            {"coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]]},  # São Paulo
            {"coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]]},  # Jakarta
        ]
        assert _is_multi_region(aois)

    def test_africa_and_southeast_asia_multi_region(self):
        """AOIs in Côte d'Ivoire and Indonesia are multi-region."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        aois = [
            {"coords": [[-4.0, 5.0], [-4.0, 5.5], [-3.5, 5.5]]},  # Côte d'Ivoire
            {"coords": [[103.0, 1.0], [103.0, 1.5], [103.5, 1.5]]},  # Singapore area
        ]
        assert _is_multi_region(aois)

    def test_single_aoi_is_not_multi_region(self):
        """A single AOI should never trigger multi-region detection."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        aois = [{"coords": [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]]}]
        assert not _is_multi_region(aois)

    def test_empty_list_is_not_multi_region(self):
        """Empty AOI list should return False without error."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        assert not _is_multi_region([])

    def test_threshold_boundary_just_under(self):
        """Pair of AOIs just under 500 km apart should NOT be multi-region."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        # ~490 km north along same longitude from (0, 0)
        # 1 degree latitude ≈ 111.32 km, 490/111.32 ≈ 4.4 degrees
        aois = [
            {"coords": [[0.0, 0.0], [0.1, 0.0], [0.0, 0.1]]},
            {"coords": [[0.0, 4.3], [0.1, 4.3], [0.0, 4.4]]},
        ]
        assert not _is_multi_region(aois)

    def test_threshold_boundary_just_over(self):
        """Pair of AOIs just over 500 km apart SHOULD be multi-region."""
        from treesight.pipeline.enrichment.runner import _is_multi_region

        # ~560 km north (5 degrees latitude)
        aois = [
            {"coords": [[0.0, 0.0], [0.1, 0.0], [0.0, 0.1]]},
            {"coords": [[0.0, 5.0], [0.1, 5.0], [0.0, 5.1]]},
        ]
        assert _is_multi_region(aois)


class TestMultiRegionRunEnrichment:
    """Verify run_enrichment multi-region behaviour (#860)."""

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_single_region_no_flag(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Single-region runs do not set multi_region flag."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        # Two AOIs in the same country (~100 km apart)
        per_aoi = [
            {
                "name": "Farm A",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Farm B",
                "coords": [[-46.0, -23.0], [-46.0, -22.5], [-45.5, -22.5]],
                "area_ha": 200,
            },
        ]

        result = run_enrichment(
            coords=[[-47.0, -23.0], [-46.0, -23.0]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert result.get("multi_region") is not True
        # Union-level mosaic and change detection were called (not skipped)
        assert mock_mosaic.call_count >= 1
        assert mock_change.call_count >= 1

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_multi_region_sets_flag(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Multi-region runs set multi_region=True in results."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        # AOIs in Brazil and Indonesia
        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        result = run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert result.get("multi_region") is True

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_multi_region_skips_union_mosaic_and_change_detection(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Union mosaic/NDVI and change detection are skipped for multi-region runs."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        mock_mosaic.assert_not_called()
        mock_change.assert_not_called()

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_multi_region_still_runs_weather(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Weather phase still runs even for multi-region runs."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        mock_weather.assert_called_once()

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_multi_region_skips_union_eudr_phase(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Union-level EUDR phase is skipped for multi-region runs."""
        mock_plan.return_value = [{"start": "2021-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
            eudr_mode=True,
        )

        mock_eudr.assert_not_called()

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    @pytest.mark.parametrize("weather_daily", [None, {"temperature": [20]}, [{"temperature": 20}]])
    def test_multi_region_per_aoi_still_runs(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
        weather_daily,
    ):
        """Per-AOI enrichment still runs for multi-region submissions."""
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {
            "name": entry.get("name", ""),
            "weather_daily": weather_daily,
        }
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        result = run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert "per_aoi_enrichment" in result
        assert len(result["per_aoi_enrichment"]) == 2
        assert all(entry["weather_daily"] == (weather_daily or {}) for entry in result["per_aoi_enrichment"])

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_multi_region_results_dict_lacks_union_outputs(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Union-level outputs must be absent from the results dict for multi-region runs.

        Prevents regressions where skipped phases might still emit zeros or
        empty dicts that downstream consumers could mistake for real data.
        """
        mock_plan.return_value = [{"start": "2024-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        result = run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
        )

        assert result.get("multi_region") is True
        # Union-level imagery keys must be absent — not zeroed-out or empty-dict
        for key in (
            "search_ids",
            "ndvi_search_ids",
            "display_collections",
            "ndvi_stats",
            "ndvi_raster_paths",
            "change_detection",
        ):
            assert key not in result, (
                f"results['{key}'] must not be present for multi-region runs — "
                "downstream consumers must not see misleading union-level data"
            )

    @patch("treesight.pipeline.enrichment.runner._enrich_single_aoi")
    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_eudr_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_multi_region_eudr_skips_determination(
        self,
        mock_plan,
        mock_weather,
        mock_flood,
        mock_eudr,
        mock_mosaic,
        mock_change,
        mock_enrich_aoi,
    ):
        """Top-level EUDR determination must be absent for multi-region runs.

        With union-level change_detection absent, determine_deforestation_free()
        would return a misleading non-compliant result.  Per-AOI determinations
        in per_aoi_enrichment are the authoritative signal instead.
        """
        mock_plan.return_value = [{"start": "2021-01-01", "end": "2024-03-01"}]
        mock_mosaic.return_value = ([], [])
        mock_enrich_aoi.side_effect = lambda entry, **kw: {"name": entry.get("name", "")}
        storage = MagicMock()

        per_aoi = [
            {
                "name": "Brazil Farm",
                "coords": [[-47.0, -23.0], [-47.0, -22.5], [-46.5, -22.5]],
                "area_ha": 100,
            },
            {
                "name": "Jakarta Farm",
                "coords": [[107.0, -6.5], [107.0, -6.0], [107.5, -6.0]],
                "area_ha": 200,
            },
        ]

        result = run_enrichment(
            coords=[[-47.0, -23.0], [107.0, -6.5]],
            project_name="test",
            timestamp="20240101",
            output_container="out",
            storage=storage,
            per_aoi_coords=per_aoi,
            eudr_mode=True,
        )

        assert result.get("multi_region") is True
        assert result.get("eudr_mode") is True
        assert "determination" not in result, (
            "top-level determination must be absent for multi-region EUDR runs — "
            "union change_detection is missing so the result would be misleading"
        )
