"""Tests for per-AOI quantitative metrics module."""

from __future__ import annotations

import pytest

from treesight.pipeline.enrichment.aoi_metrics import (
    classify_ndvi,
    compute_aoi_metrics,
    compute_multi_aoi_summary,
    compute_ndvi_trend,
)

# ── Fixtures ────────────────────────────────────────────────


def _make_aoi_data(
    name: str = "Block A",
    index: int = 0,
    area_ha: float = 12.3,
    perimeter_km: float = 1.4,
    centroid: list[float] | None = None,
    bbox: list[float] | None = None,
) -> dict:
    return {
        "feature_name": name,
        "feature_index": index,
        "area_ha": area_ha,
        "perimeter_km": perimeter_km,
        "centroid": centroid or [36.805, -1.305],
        "bbox": bbox or [36.8, -1.31, 36.81, -1.3],
    }


def _make_ndvi_stats(means: list[float | None]) -> list[dict | None]:
    """Generate a list of NDVI stat dicts from mean values."""
    stats: list[dict | None] = []
    for m in means:
        if m is None:
            stats.append(None)
        else:
            stats.append(
                {
                    "mean": m,
                    "min": m - 0.1,
                    "max": m + 0.1,
                    "std": 0.05,
                    "median": m,
                    "valid_pixels": 10000,
                    "cloud_cover": 5.0,
                    "scene_id": "S2A_123",
                    "datetime": "2024-06-01",
                }
            )
    return stats


# ── classify_ndvi ────────────────────────────────────────────


class TestClassifyNdvi:
    def test_bare_soil(self):
        assert classify_ndvi(0.05) == "bare_soil"

    def test_sparse_vegetation(self):
        assert classify_ndvi(0.15) == "sparse_vegetation"

    def test_moderate_vegetation(self):
        assert classify_ndvi(0.30) == "moderate_vegetation"

    def test_healthy_vegetation(self):
        assert classify_ndvi(0.50) == "healthy_vegetation"

    def test_very_healthy_vegetation(self):
        assert classify_ndvi(0.70) == "very_healthy_vegetation"

    def test_dense_vegetation(self):
        assert classify_ndvi(0.85) == "dense_vegetation"

    def test_boundary_values(self):
        assert classify_ndvi(0.1) == "sparse_vegetation"
        assert classify_ndvi(0.2) == "moderate_vegetation"
        assert classify_ndvi(0.4) == "healthy_vegetation"
        assert classify_ndvi(0.6) == "very_healthy_vegetation"
        assert classify_ndvi(0.8) == "dense_vegetation"

    def test_zero(self):
        assert classify_ndvi(0.0) == "bare_soil"

    def test_negative(self):
        assert classify_ndvi(-0.1) == "bare_soil"


# ── compute_ndvi_trend ───────────────────────────────────────


class TestComputeNdviTrend:
    def test_insufficient_data_empty(self):
        result = compute_ndvi_trend([])
        assert result["direction"] == "insufficient_data"
        assert result["observations"] == 0

    def test_insufficient_data_single(self):
        stats = _make_ndvi_stats([0.5])
        result = compute_ndvi_trend(stats)
        assert result["direction"] == "insufficient_data"
        assert result["observations"] == 1
        assert result["latest_mean"] == pytest.approx(0.5)

    def test_improving_trend(self):
        stats = _make_ndvi_stats([0.3, 0.35, 0.4, 0.45, 0.5])
        result = compute_ndvi_trend(stats)
        assert result["direction"] == "improving"
        assert result["slope_per_frame"] > 0
        assert result["overall_change"] > 0
        assert result["overall_change_pct"] > 0

    def test_declining_trend(self):
        stats = _make_ndvi_stats([0.5, 0.45, 0.4, 0.35, 0.3])
        result = compute_ndvi_trend(stats)
        assert result["direction"] == "declining"
        assert result["slope_per_frame"] < 0
        assert result["overall_change"] < 0

    def test_stable_trend(self):
        stats = _make_ndvi_stats([0.5, 0.501, 0.499, 0.5, 0.501])
        result = compute_ndvi_trend(stats)
        assert result["direction"] == "stable"
        assert abs(result["slope_per_frame"]) < 0.002

    def test_handles_none_gaps(self):
        stats = _make_ndvi_stats([0.3, None, 0.4, None, 0.5])
        result = compute_ndvi_trend(stats)
        assert result["observations"] == 3
        assert result["direction"] == "improving"

    def test_all_none_is_insufficient(self):
        stats = _make_ndvi_stats([None, None, None])
        result = compute_ndvi_trend(stats)
        assert result["direction"] == "insufficient_data"
        assert result["observations"] == 0

    def test_max_consecutive_drop(self):
        stats = _make_ndvi_stats([0.5, 0.45, 0.2, 0.3])
        result = compute_ndvi_trend(stats)
        assert result["max_consecutive_drop"] == pytest.approx(0.25, abs=0.001)

    def test_health_class_from_latest(self):
        stats = _make_ndvi_stats([0.3, 0.5, 0.7])
        result = compute_ndvi_trend(stats)
        assert result["health_class"] == classify_ndvi(0.7)

    def test_coefficient_of_variation(self):
        stats = _make_ndvi_stats([0.5, 0.5, 0.5])
        result = compute_ndvi_trend(stats)
        assert result["coefficient_of_variation"] == 0.0


# ── compute_aoi_metrics ─────────────────────────────────────


class TestComputeAoiMetrics:
    def test_basic_geometry(self):
        aoi = _make_aoi_data(area_ha=100.0, perimeter_km=4.0)
        result = compute_aoi_metrics(aoi, _make_ndvi_stats([0.5, 0.5]))
        geom = result["geometry"]
        assert geom["area_ha"] == 100.0
        assert geom["area_km2"] == 1.0
        assert geom["perimeter_km"] == 4.0
        assert 0 < geom["compactness"] <= 1.0

    def test_compactness_circle_vs_strip(self):
        # A square ~1km on a side: perimeter = 4km, area = 100 ha
        square = _make_aoi_data(area_ha=100.0, perimeter_km=4.0)
        result_square = compute_aoi_metrics(square, _make_ndvi_stats([0.5]))

        # A very elongated strip: same area, much longer perimeter
        strip = _make_aoi_data(area_ha=100.0, perimeter_km=20.2)
        result_strip = compute_aoi_metrics(strip, _make_ndvi_stats([0.5]))

        assert result_square["geometry"]["compactness"] > result_strip["geometry"]["compactness"]

    def test_zero_area_compactness(self):
        aoi = _make_aoi_data(area_ha=0.0, perimeter_km=0.0)
        result = compute_aoi_metrics(aoi, [])
        assert result["geometry"]["compactness"] == 0.0

    def test_bbox_dimensions(self):
        # bbox spanning ~1.1km in each direction near equator
        aoi = _make_aoi_data(bbox=[36.8, -1.31, 36.81, -1.3])
        result = compute_aoi_metrics(aoi, [])
        geom = result["geometry"]
        assert geom["bbox_width_km"] > 0
        assert geom["bbox_height_km"] > 0
        # Roughly 1.1 km
        assert 0.5 < geom["bbox_width_km"] < 2.0
        assert 0.5 < geom["bbox_height_km"] < 2.0

    def test_vegetation_section_present(self):
        aoi = _make_aoi_data()
        result = compute_aoi_metrics(aoi, _make_ndvi_stats([0.4, 0.5]))
        assert "vegetation" in result
        assert result["vegetation"]["direction"] in ("stable", "improving", "declining")

    def test_latest_ndvi_detail(self):
        stats = _make_ndvi_stats([0.3, 0.5])
        aoi = _make_aoi_data()
        result = compute_aoi_metrics(aoi, stats)
        detail = result["vegetation"]["latest_detail"]
        assert detail["mean"] == pytest.approx(0.5)
        assert detail["valid_pixels"] == 10000

    def test_no_ndvi_data(self):
        aoi = _make_aoi_data()
        result = compute_aoi_metrics(aoi, [])
        assert result["vegetation"]["direction"] == "insufficient_data"
        assert "latest_detail" not in result["vegetation"]

    def test_change_detection_present(self):
        aoi = _make_aoi_data()
        change = {
            "season_changes": [
                {"loss_ha": 2.0, "gain_ha": 1.0, "season": "summer", "year_a": 2022, "year_b": 2023}
            ],
            "summary": {"comparisons": 1, "trajectory": "declining"},
        }
        result = compute_aoi_metrics(aoi, [], change_detection=change)
        assert result["change"]["comparisons"] == 1
        assert result["change"]["total_loss_ha"] == 2.0
        assert result["change"]["total_gain_ha"] == 1.0
        assert result["change"]["net_change_ha"] == -1.0

    def test_no_change_detection(self):
        aoi = _make_aoi_data()
        result = compute_aoi_metrics(aoi, [])
        assert result["change"]["comparisons"] == 0

    def test_weather_summary(self):
        aoi = _make_aoi_data()
        weather = {"temp": [20.0, 22.0, 25.0], "precip": [0.0, 5.0, 10.0]}
        result = compute_aoi_metrics(aoi, [], weather_daily=weather)
        w = result["weather"]
        assert w["observation_days"] == 3
        assert w["temp_mean_c"] == pytest.approx(22.3, abs=0.1)
        assert w["precip_total_mm"] == 15.0
        assert w["precip_days"] == 2  # 5.0 and 10.0 > 0.1

    def test_no_weather(self):
        aoi = _make_aoi_data()
        result = compute_aoi_metrics(aoi, [])
        assert result["weather"]["observation_days"] == 0

    def test_feature_name_preserved(self):
        aoi = _make_aoi_data(name="Orchard Block C")
        result = compute_aoi_metrics(aoi, [])
        assert result["feature_name"] == "Orchard Block C"
        assert result["feature_index"] == 0


# ── compute_multi_aoi_summary ───────────────────────────────


class TestComputeMultiAoiSummary:
    def test_empty_list(self):
        result = compute_multi_aoi_summary([])
        assert result["aoi_count"] == 0

    def test_single_aoi(self):
        metrics = [
            compute_aoi_metrics(
                _make_aoi_data(area_ha=50.0, perimeter_km=3.0),
                _make_ndvi_stats([0.5]),
            )
        ]
        result = compute_multi_aoi_summary(metrics)
        assert result["aoi_count"] == 1
        assert result["total_area_ha"] == 50.0

    def test_multiple_aois_area_sums(self):
        metrics = [
            compute_aoi_metrics(
                _make_aoi_data(name="A", area_ha=50.0, perimeter_km=3.0),
                _make_ndvi_stats([0.5]),
            ),
            compute_aoi_metrics(
                _make_aoi_data(name="B", index=1, area_ha=30.0, perimeter_km=2.2),
                _make_ndvi_stats([0.7]),
            ),
        ]
        result = compute_multi_aoi_summary(metrics)
        assert result["aoi_count"] == 2
        assert result["total_area_ha"] == 80.0
        assert result["total_perimeter_km"] == pytest.approx(5.2, abs=0.01)

    def test_weighted_ndvi(self):
        """Weighted mean NDVI should favour the larger AOI."""
        metrics = [
            compute_aoi_metrics(
                _make_aoi_data(name="Large", area_ha=100.0, perimeter_km=4.0),
                _make_ndvi_stats([0.6]),
            ),
            compute_aoi_metrics(
                _make_aoi_data(name="Small", index=1, area_ha=10.0, perimeter_km=1.3),
                _make_ndvi_stats([0.2]),
            ),
        ]
        result = compute_multi_aoi_summary(metrics)
        # 100*0.6 + 10*0.2 = 62 / 110 ≈ 0.5636
        assert result["weighted_mean_ndvi"] == pytest.approx(0.5636, abs=0.01)

    def test_health_distribution(self):
        metrics = [
            compute_aoi_metrics(
                _make_aoi_data(name="Healthy", area_ha=50.0, perimeter_km=3.0),
                _make_ndvi_stats([0.7]),
            ),
            compute_aoi_metrics(
                _make_aoi_data(name="Bare", index=1, area_ha=50.0, perimeter_km=3.0),
                _make_ndvi_stats([0.05]),
            ),
        ]
        result = compute_multi_aoi_summary(metrics)
        dist = result["health_distribution"]
        assert dist.get("very_healthy_vegetation", 0) == 1
        assert dist.get("bare_soil", 0) == 1

    def test_change_aggregation(self):
        change = {
            "season_changes": [
                {"loss_ha": 3.0, "gain_ha": 1.0, "season": "summer", "year_a": 2022, "year_b": 2023}
            ],
            "summary": {"trajectory": "declining"},
        }
        metrics = [
            compute_aoi_metrics(
                _make_aoi_data(name="A", area_ha=50.0, perimeter_km=3.0),
                [],
                change_detection=change,
            ),
            compute_aoi_metrics(
                _make_aoi_data(name="B", index=1, area_ha=50.0, perimeter_km=3.0),
                [],
                change_detection=change,
            ),
        ]
        result = compute_multi_aoi_summary(metrics)
        assert result["total_loss_ha"] == 6.0
        assert result["total_gain_ha"] == 2.0
        assert result["net_change_ha"] == -4.0

    def test_no_ndvi_data_weighted_none(self):
        metrics = [
            compute_aoi_metrics(
                _make_aoi_data(area_ha=50.0, perimeter_km=3.0),
                [],
            ),
        ]
        result = compute_multi_aoi_summary(metrics)
        assert result["weighted_mean_ndvi"] is None
