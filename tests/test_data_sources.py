"""Tests for IO LULC Annual and ALOS Forest/Non-Forest data sources (#607, #608)."""

from __future__ import annotations

from treesight.pipeline.eudr import (
    ALOS_FNF_CLASSES,
    IO_LULC_CLASSES,
    query_alos_fnf,
    query_lulc_annual,
)


class TestQueryLulcAnnual:
    def test_stub_returns_available(self):
        result = query_lulc_annual([10, -5, 11, -4], stub_mode=True)
        assert result["available"] is True
        assert result["collection"] == "io-lulc-annual-v02"

    def test_stub_contains_yearly_data(self):
        result = query_lulc_annual([10, -5, 11, -4], stub_mode=True)
        years = result["years"]
        assert len(years) >= 2
        for year_data in years.values():
            assert "dominant" in year_data
            assert "tree_pct" in year_data
            assert "class_breakdown" in year_data

    def test_stub_custom_years(self):
        result = query_lulc_annual([10, -5, 11, -4], years=[2020, 2021], stub_mode=True)
        assert set(result["years"].keys()) == {"2020", "2021"}

    def test_stub_trend_stable(self):
        result = query_lulc_annual([10, -5, 11, -4], stub_mode=True)
        assert result["tree_cover_trend"] == "stable"
        assert result["change_detected"] is False

    def test_io_lulc_classes_coverage(self):
        """All expected class codes are mapped."""
        assert 4 in IO_LULC_CLASSES  # Trees
        assert 7 in IO_LULC_CLASSES  # Crops
        assert 2 in IO_LULC_CLASSES  # Water


class TestQueryAlosFnf:
    def test_stub_returns_available(self):
        result = query_alos_fnf([10, -5, 11, -4], stub_mode=True)
        assert result["available"] is True
        assert result["collection"] == "alos-fnf-mosaic"

    def test_stub_contains_forest_pct(self):
        result = query_alos_fnf([10, -5, 11, -4], stub_mode=True)
        assert result["forest_pct"] > 0
        assert result["non_forest_pct"] >= 0
        assert result["water_pct"] >= 0
        assert result["source"] == "ALOS-2 PALSAR-2"

    def test_stub_has_classification_breakdown(self):
        result = query_alos_fnf([10, -5, 11, -4], stub_mode=True)
        classes = result["classification"]["classes"]
        assert len(classes) >= 2
        codes = {c["code"] for c in classes}
        assert 1 in codes  # Forest >90%

    def test_stub_dominant_class(self):
        result = query_alos_fnf([10, -5, 11, -4], stub_mode=True)
        assert result["dominant_class"] is not None

    def test_alos_fnf_classes_coverage(self):
        """All expected class codes are mapped."""
        assert 1 in ALOS_FNF_CLASSES  # Forest >90%
        assert 2 in ALOS_FNF_CLASSES  # Forest 10-90%
        assert 3 in ALOS_FNF_CLASSES  # Non-forest
        assert 4 in ALOS_FNF_CLASSES  # Water
