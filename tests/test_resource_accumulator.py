"""Tests for ResourceAccumulator — tracks resource consumption across enrichment phases."""

from __future__ import annotations

from treesight.pipeline.enrichment.resource_accumulator import ResourceAccumulator


class TestResourceAccumulatorInit:
    """ResourceAccumulator starts with empty state."""

    def test_empty_accumulator_has_zero_counts(self):
        acc = ResourceAccumulator()
        result = acc.to_dict()
        assert result["data_sources_queried"] == []
        assert result["api_calls"] == {}
        assert result["phase_durations"] == {}
        assert result["sentinel2_scenes_registered"] == 0
        assert result["landsat_scenes_sampled"] == 0
        assert result["ndvi_computations"] == 0
        assert result["change_detection_comparisons"] == 0
        assert result["mosaic_registrations"] == 0
        assert result["per_aoi_enrichments"] == 0


class TestAddSource:
    """add_source tracks unique data sources queried."""

    def test_adds_source(self):
        acc = ResourceAccumulator()
        acc.add_source("open-meteo")
        assert "open-meteo" in acc.to_dict()["data_sources_queried"]

    def test_deduplicates_sources(self):
        acc = ResourceAccumulator()
        acc.add_source("open-meteo")
        acc.add_source("open-meteo")
        assert acc.to_dict()["data_sources_queried"].count("open-meteo") == 1

    def test_preserves_insertion_order(self):
        acc = ResourceAccumulator()
        acc.add_source("open-meteo")
        acc.add_source("gfd-flood")
        acc.add_source("firms-fire")
        assert acc.to_dict()["data_sources_queried"] == [
            "open-meteo",
            "gfd-flood",
            "firms-fire",
        ]


class TestAddApiCall:
    """add_api_call counts calls per service."""

    def test_increments_count(self):
        acc = ResourceAccumulator()
        acc.add_api_call("open_meteo")
        acc.add_api_call("open_meteo")
        assert acc.to_dict()["api_calls"]["open_meteo"] == 2

    def test_defaults_increment_to_one(self):
        acc = ResourceAccumulator()
        acc.add_api_call("firms")
        assert acc.to_dict()["api_calls"]["firms"] == 1

    def test_custom_increment(self):
        acc = ResourceAccumulator()
        acc.add_api_call("planetary_computer", count=12)
        assert acc.to_dict()["api_calls"]["planetary_computer"] == 12


class TestRecordPhaseDuration:
    """record_phase_duration tracks how long each phase took."""

    def test_records_duration(self):
        acc = ResourceAccumulator()
        acc.record_phase_duration("weather", 2.1)
        assert acc.to_dict()["phase_durations"]["weather"] == 2.1

    def test_rounds_to_one_decimal(self):
        acc = ResourceAccumulator()
        acc.record_phase_duration("flood_fire", 3.456)
        assert acc.to_dict()["phase_durations"]["flood_fire"] == 3.5


class TestCounterIncrements:
    """Direct counter increments for scenes, NDVI, etc."""

    def test_increment_sentinel2(self):
        acc = ResourceAccumulator()
        acc.increment("sentinel2_scenes_registered", 12)
        assert acc.to_dict()["sentinel2_scenes_registered"] == 12

    def test_increment_landsat(self):
        acc = ResourceAccumulator()
        acc.increment("landsat_scenes_sampled", 4)
        assert acc.to_dict()["landsat_scenes_sampled"] == 4

    def test_increment_ndvi(self):
        acc = ResourceAccumulator()
        acc.increment("ndvi_computations", 6)
        assert acc.to_dict()["ndvi_computations"] == 6

    def test_increment_change_detection(self):
        acc = ResourceAccumulator()
        acc.increment("change_detection_comparisons", 3)
        assert acc.to_dict()["change_detection_comparisons"] == 3

    def test_increment_mosaic(self):
        acc = ResourceAccumulator()
        acc.increment("mosaic_registrations", 12)
        assert acc.to_dict()["mosaic_registrations"] == 12

    def test_increment_per_aoi(self):
        acc = ResourceAccumulator()
        acc.increment("per_aoi_enrichments", 8)
        assert acc.to_dict()["per_aoi_enrichments"] == 8

    def test_rejects_unknown_counter(self):
        acc = ResourceAccumulator()
        import pytest

        with pytest.raises(ValueError, match="Unknown counter"):
            acc.increment("unknown_field", 1)

    def test_additive_increments(self):
        acc = ResourceAccumulator()
        acc.increment("ndvi_computations", 3)
        acc.increment("ndvi_computations", 4)
        assert acc.to_dict()["ndvi_computations"] == 7


class TestMerge:
    """merge combines two accumulators (for parallel sub-step fan-out)."""

    def test_merges_sources(self):
        a = ResourceAccumulator()
        a.add_source("open-meteo")
        b = ResourceAccumulator()
        b.add_source("gfd-flood")
        b.add_source("open-meteo")  # duplicate
        a.merge(b)
        result = a.to_dict()
        assert sorted(result["data_sources_queried"]) == ["gfd-flood", "open-meteo"]

    def test_merges_api_calls(self):
        a = ResourceAccumulator()
        a.add_api_call("open_meteo", count=1)
        b = ResourceAccumulator()
        b.add_api_call("open_meteo", count=2)
        b.add_api_call("firms", count=1)
        a.merge(b)
        result = a.to_dict()
        assert result["api_calls"]["open_meteo"] == 3
        assert result["api_calls"]["firms"] == 1

    def test_merges_counters(self):
        a = ResourceAccumulator()
        a.increment("ndvi_computations", 6)
        b = ResourceAccumulator()
        b.increment("ndvi_computations", 4)
        b.increment("mosaic_registrations", 12)
        a.merge(b)
        result = a.to_dict()
        assert result["ndvi_computations"] == 10
        assert result["mosaic_registrations"] == 12

    def test_merges_phase_durations(self):
        a = ResourceAccumulator()
        a.record_phase_duration("weather", 2.1)
        b = ResourceAccumulator()
        b.record_phase_duration("mosaic_ndvi", 18.7)
        a.merge(b)
        result = a.to_dict()
        assert result["phase_durations"]["weather"] == 2.1
        assert result["phase_durations"]["mosaic_ndvi"] == 18.7

    def test_merge_phase_duration_conflict_takes_max(self):
        """If both have the same phase, take the longer duration."""
        a = ResourceAccumulator()
        a.record_phase_duration("weather", 2.1)
        b = ResourceAccumulator()
        b.record_phase_duration("weather", 3.5)
        a.merge(b)
        assert a.to_dict()["phase_durations"]["weather"] == 3.5


class TestToDict:
    """to_dict returns a clean serializable dictionary."""

    def test_roundtrip_populated(self):
        acc = ResourceAccumulator()
        acc.add_source("open-meteo")
        acc.add_source("firms-fire")
        acc.add_api_call("open_meteo")
        acc.add_api_call("firms")
        acc.increment("sentinel2_scenes_registered", 12)
        acc.increment("ndvi_computations", 12)
        acc.increment("change_detection_comparisons", 6)
        acc.increment("mosaic_registrations", 12)
        acc.increment("per_aoi_enrichments", 8)
        acc.record_phase_duration("weather", 2.1)
        acc.record_phase_duration("flood_fire", 3.4)
        result = acc.to_dict()

        assert isinstance(result, dict)
        assert result["data_sources_queried"] == ["open-meteo", "firms-fire"]
        assert result["api_calls"] == {"open_meteo": 1, "firms": 1}
        assert result["sentinel2_scenes_registered"] == 12
        assert result["ndvi_computations"] == 12
        assert result["change_detection_comparisons"] == 6
        assert result["mosaic_registrations"] == 12
        assert result["per_aoi_enrichments"] == 8
        assert result["phase_durations"] == {"weather": 2.1, "flood_fire": 3.4}


class TestFromDict:
    """from_dict reconstructs an accumulator from a serialized dict."""

    def test_roundtrip(self):
        acc = ResourceAccumulator()
        acc.add_source("open-meteo")
        acc.add_api_call("open_meteo", count=3)
        acc.increment("sentinel2_scenes_registered", 5)
        acc.record_phase_duration("weather", 2.1)
        data = acc.to_dict()
        restored = ResourceAccumulator.from_dict(data)
        assert restored.to_dict() == data

    def test_empty_dict(self):
        restored = ResourceAccumulator.from_dict({})
        result = restored.to_dict()
        assert result["data_sources_queried"] == []
        assert result["api_calls"] == {}
        assert result["sentinel2_scenes_registered"] == 0


class TestEstimateCostPence:
    """estimate_cost_pence returns indicative platform cost."""

    def test_empty_accumulator_zero(self):
        acc = ResourceAccumulator()
        assert acc.estimate_cost_pence() == 0.0

    def test_counters_contribute(self):
        acc = ResourceAccumulator()
        acc.increment("sentinel2_scenes_registered", 10)
        cost = acc.estimate_cost_pence()
        assert cost > 0

    def test_api_calls_contribute(self):
        acc = ResourceAccumulator()
        acc.add_api_call("open_meteo", count=100)
        cost = acc.estimate_cost_pence()
        assert cost > 0

    def test_known_values(self):
        """Verify exact cost for a known resource profile."""
        acc = ResourceAccumulator()
        acc.increment("sentinel2_scenes_registered", 10)  # 10 * 0.2 = 2.0
        acc.increment("ndvi_computations", 10)  # 10 * 0.05 = 0.5
        acc.add_api_call("open_meteo", count=10)  # 10 * 0.01 = 0.1
        assert acc.estimate_cost_pence() == 2.6
