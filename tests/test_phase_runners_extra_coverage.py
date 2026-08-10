"""Direct unit coverage for the per-data-source enrichment phase runners.

_run_weather_phase / _run_flood_fire_phase / _run_eudr_phase /
_run_landsat_baseline / _run_change_detection_phase / _run_aoi_metrics_phase
are pure functions extracted from runner.py (#1292), but every existing
end-to-end test of run_enrichment() mocks these phase functions wholesale
(see tests/test_enrichment_runner.py), so their real bodies were never
directly exercised. Closes the gap exposed by the #1292 extraction.
"""

from __future__ import annotations

from unittest.mock import patch

from treesight.pipeline.enrichment._phase_runners import (
    _run_aoi_metrics_phase,
    _run_change_detection_phase,
    _run_eudr_phase,
    _run_flood_fire_phase,
    _run_landsat_baseline,
    _run_weather_phase,
)
from treesight.pipeline.enrichment.resource_accumulator import ResourceAccumulator

BBOX = [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0]]


class TestWeatherPhase:
    @patch("treesight.pipeline.enrichment._phase_runners.aggregate_weather_monthly")
    @patch("treesight.pipeline.enrichment._phase_runners.fetch_weather")
    def test_weather_available_populates_results_and_accumulator(self, mock_fetch, mock_agg):
        mock_fetch.return_value = {"dates": ["2024-01-01", "2024-01-02"]}
        mock_agg.return_value = {"2024-01": {"tmean": 20.0}}
        results: dict = {}
        acc = ResourceAccumulator()

        _run_weather_phase(-10.0, -50.0, "2024-01-01", "2024-06-01", results, acc=acc)

        assert results["weather_daily"] == mock_fetch.return_value
        assert results["weather_monthly"] == mock_agg.return_value
        assert acc.to_dict()["api_calls"]["open_meteo"] == 1
        assert "open-meteo" in acc.to_dict()["data_sources_queried"]

    @patch("treesight.pipeline.enrichment._phase_runners.fetch_weather")
    def test_weather_unavailable_sets_none(self, mock_fetch):
        mock_fetch.return_value = None
        results: dict = {}

        _run_weather_phase(-10.0, -50.0, "2024-01-01", "2024-06-01", results)

        assert results["weather_daily"] is None
        assert results["weather_monthly"] is None


class TestFloodFirePhase:
    @patch("treesight.pipeline.enrichment._phase_runners.fetch_fire_hotspots")
    @patch("treesight.pipeline.enrichment._phase_runners.fetch_flood_events")
    def test_populates_results_and_accumulator(self, mock_flood, mock_fire):
        mock_flood.return_value = {"source": "gfd", "count": 2}
        mock_fire.return_value = {"source": "firms", "count": 5}
        results: dict = {}
        acc = ResourceAccumulator()

        _run_flood_fire_phase(BBOX, -10.0, -50.0, results, acc=acc)

        assert results["flood_events"] == mock_flood.return_value
        assert results["fire_hotspots"] == mock_fire.return_value
        acc_dict = acc.to_dict()
        assert acc_dict["api_calls"] == {"gfd": 1, "firms": 1}
        assert set(acc_dict["data_sources_queried"]) == {"gfd-flood", "firms-fire"}


class TestLandsatBaseline:
    @patch("treesight.pipeline.enrichment.ndvi.compute_landsat_ndvi")
    def test_no_scenes_available(self, mock_ndvi):
        mock_ndvi.return_value = None
        results: dict = {}

        _run_landsat_baseline(BBOX[0] + BBOX[2], results)

        assert results["landsat_baseline"]["available"] is False
        assert results["landsat_baseline"]["scenes"] == []

    @patch("treesight.pipeline.enrichment.ndvi.compute_landsat_ndvi")
    def test_scenes_available_strips_raster_bytes(self, mock_ndvi):
        mock_ndvi.return_value = {"mean": 0.4, "geotiff_bytes": b"raw"}
        results: dict = {}

        _run_landsat_baseline(BBOX[0] + BBOX[2], results)

        assert results["landsat_baseline"]["available"] is True
        assert "geotiff_bytes" not in results["landsat_baseline"]["scenes"][0]


class TestEudrPhase:
    @patch("treesight.pipeline.enrichment.ndvi.compute_landsat_ndvi")
    @patch("treesight.pipeline.eudr.query_alos_fnf")
    @patch("treesight.pipeline.eudr.query_lulc_annual")
    @patch("treesight.pipeline.eudr.check_wdpa_overlap")
    @patch("treesight.pipeline.eudr.query_worldcover")
    def test_populates_all_datasets_and_accumulator(
        self, mock_worldcover, mock_wdpa, mock_lulc, mock_alos, mock_landsat
    ):
        mock_worldcover.return_value = {"available": True}
        mock_wdpa.return_value = {"checked": True, "is_protected": False}
        mock_lulc.return_value = {"available": True}
        mock_alos.return_value = {"available": True}
        mock_landsat.return_value = {"mean": 0.5, "geotiff_bytes": b"raw"}
        results: dict = {}
        acc = ResourceAccumulator()

        _run_eudr_phase(BBOX, -10.0, -50.0, results, acc=acc)

        assert results["worldcover"] == mock_worldcover.return_value
        assert results["wdpa"] == mock_wdpa.return_value
        assert results["lulc_annual"] == mock_lulc.return_value
        assert results["alos_fnf"] == mock_alos.return_value
        assert results["landsat_baseline"]["available"] is True

        acc_dict = acc.to_dict()
        assert acc_dict["api_calls"] == {
            "worldcover": 1,
            "wdpa": 1,
            "lulc": 1,
            "alos": 1,
        }
        assert "landsat-c2-l2" in acc_dict["data_sources_queried"]
        # _run_landsat_baseline samples 2 windows (2013-2014, 2015-2016).
        assert acc_dict["landsat_scenes_sampled"] == 2


class TestChangeDetectionPhase:
    @patch("treesight.pipeline.enrichment._phase_runners.detect_changes")
    def test_with_rasters_records_comparisons(self, mock_detect):
        mock_detect.return_value = {"summary": {"comparisons": 3, "trajectory": "improving"}}
        results: dict = {}
        acc = ResourceAccumulator()

        _run_change_detection_phase(
            [{"year": 2024}],
            ["raster/path.tif", None],
            "output",
            "proj",
            "ts",
            storage=None,
            results=results,
            acc=acc,
        )

        assert results["change_detection"] == mock_detect.return_value
        assert acc.to_dict()["change_detection_comparisons"] == 3

    def test_without_rasters_skips_detection(self):
        results: dict = {}

        _run_change_detection_phase(
            [{"year": 2024}],
            [None, None],
            "output",
            "proj",
            "ts",
            storage=None,
            results=results,
        )

        assert results["change_detection"] == {"season_changes": [], "summary": {}}


class TestAoiMetricsPhase:
    @patch("treesight.pipeline.enrichment._phase_runners.compute_multi_aoi_summary")
    @patch("treesight.pipeline.enrichment._phase_runners.compute_aoi_metrics")
    def test_computes_per_aoi_and_summary_metrics(self, mock_metrics, mock_summary):
        mock_metrics.side_effect = lambda **kwargs: {"name": kwargs["aoi_data"]["feature_name"]}
        mock_summary.return_value = {"combined": True}
        results: dict = {"weather_daily": None, "change_detection": None}

        _run_aoi_metrics_phase(
            [{"feature_name": "A"}, {"feature_name": "B"}],
            [{"mean": 0.5}],
            results,
        )

        assert len(results["per_aoi_metrics"]) == 2
        assert all(m["ndvi_data_scope"] == "union" for m in results["per_aoi_metrics"])
        assert results["multi_aoi_summary"] == {"combined": True}
