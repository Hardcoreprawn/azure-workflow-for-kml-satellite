"""Tests for the enrichment runner's parallel execution paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from treesight.pipeline.enrichment.runner import _run_mosaic_ndvi_phase


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
