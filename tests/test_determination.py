"""Tests for deforestation-free determination (#603)."""

from __future__ import annotations

from treesight.pipeline.enrichment.determination import (
    determine_deforestation_free,
)


def _make_enrichment(
    *,
    loss_ha: float = 0.0,
    gain_ha: float = 0.5,
    loss_pct: float = 0.0,
    trajectory: str = "Stable",
    avg_delta: float = 0.01,
    comparisons: int = 3,
    season_changes: list | None = None,
    worldcover_available: bool = True,
    tree_pct: float = 40.0,
    wdpa_protected: bool = False,
    lulc_available: bool = False,
    lulc_change_detected: bool = False,
    lulc_trend: str = "stable",
    alos_available: bool = False,
    alos_forest_pct: float = 90.0,
) -> dict:
    """Build a minimal enrichment result dict for testing."""
    if season_changes is None:
        season_changes = [
            {
                "season": "summer",
                "year_from": 2021,
                "year_to": 2022,
                "label": "Summer 2021 → 2022",
                "loss_pct": loss_pct,
                "loss_ha": loss_ha,
                "gain_pct": 1.0,
                "gain_ha": gain_ha,
                "mean_delta": avg_delta,
            }
        ]
    result: dict = {
        "change_detection": {
            "summary": {
                "comparisons": comparisons,
                "total_loss_ha": loss_ha,
                "total_gain_ha": gain_ha,
                "avg_mean_delta": avg_delta,
                "trajectory": trajectory,
            },
            "season_changes": season_changes,
        },
    }
    if worldcover_available:
        result["worldcover"] = {
            "available": True,
            "land_cover": {
                "dominant_class": "Tree cover",
                "classes": [
                    {"code": 10, "label": "Tree cover", "pixel_count": 60, "area_pct": tree_pct},
                    {
                        "code": 40,
                        "label": "Cropland",
                        "pixel_count": 40,
                        "area_pct": 100 - tree_pct,
                    },
                ],
            },
        }
    result["wdpa"] = {
        "checked": True,
        "is_protected": wdpa_protected,
    }
    if lulc_available:
        result["lulc_annual"] = {
            "available": True,
            "collection": "io-lulc-annual-v02",
            "change_detected": lulc_change_detected,
            "tree_cover_trend": lulc_trend,
            "years": {"2020": {}, "2021": {}, "2022": {}},
        }
    if alos_available:
        result["alos_fnf"] = {
            "available": True,
            "collection": "alos-fnf-mosaic",
            "year": 2020,
            "forest_pct": alos_forest_pct,
            "dominant_class": "Forest (>90% canopy)",
            "source": "ALOS-2 PALSAR-2",
        }
    return result


class TestDeforestationDetermination:
    def test_clean_parcel_is_deforestation_free(self):
        enrichment = _make_enrichment()
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is True
        assert det["confidence"] == "high"
        assert det["flags"] == []

    def test_significant_loss_flags(self):
        enrichment = _make_enrichment(loss_pct=8.0, loss_ha=2.5)
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert any("Vegetation loss" in f for f in det["flags"])

    def test_declining_trajectory_flags(self):
        enrichment = _make_enrichment(trajectory="Declining", avg_delta=-0.06)
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert any("declining" in f.lower() for f in det["flags"])

    def test_wdpa_protected_area_flags(self):
        enrichment = _make_enrichment(wdpa_protected=True)
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert any("WDPA" in f for f in det["flags"])

    def test_no_data_returns_low_confidence(self):
        enrichment = _make_enrichment(comparisons=0, season_changes=[])
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert det["confidence"] == "low"

    def test_loss_below_threshold_passes(self):
        enrichment = _make_enrichment(loss_pct=3.0, loss_ha=0.5)
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is True

    def test_loss_pct_above_but_ha_below_passes(self):
        """Small absolute area shouldn't trigger even with high percentage."""
        enrichment = _make_enrichment(loss_pct=10.0, loss_ha=0.3)
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is True

    def test_custom_thresholds(self):
        enrichment = _make_enrichment(loss_pct=3.0, loss_ha=2.0)
        det = determine_deforestation_free(
            enrichment, loss_pct_threshold=2.0, loss_ha_threshold=0.5
        )
        assert det["deforestation_free"] is False

    def test_evidence_contains_change_detection(self):
        enrichment = _make_enrichment()
        det = determine_deforestation_free(enrichment)
        ev = det["evidence"]
        assert "change_detection" in ev
        assert ev["change_detection"]["trajectory"] == "Stable"
        assert ev["change_detection"]["comparisons"] == 3

    def test_evidence_contains_worldcover(self):
        enrichment = _make_enrichment(tree_pct=65.0)
        det = determine_deforestation_free(enrichment)
        assert det["evidence"]["worldcover"]["tree_cover_pct"] == 65.0

    def test_evidence_contains_wdpa(self):
        enrichment = _make_enrichment(wdpa_protected=False)
        det = determine_deforestation_free(enrichment)
        assert det["evidence"]["wdpa"]["checked"] is True
        assert det["evidence"]["wdpa"]["is_protected"] is False

    def test_missing_worldcover_handled(self):
        enrichment = _make_enrichment()
        del enrichment["worldcover"]
        det = determine_deforestation_free(enrichment)
        assert det["evidence"]["worldcover"]["available"] is False

    def test_multiple_flags_medium_or_high_confidence(self):
        enrichment = _make_enrichment(
            loss_pct=8.0,
            loss_ha=2.0,
            trajectory="Declining",
            avg_delta=-0.08,
            wdpa_protected=True,
        )
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert len(det["flags"]) >= 3
        assert det["confidence"] == "high"

    def test_lulc_change_detected_flags(self):
        enrichment = _make_enrichment(lulc_available=True, lulc_change_detected=True)
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert any("IO LULC" in f and "change" in f for f in det["flags"])

    def test_lulc_declining_trend_flags(self):
        enrichment = _make_enrichment(lulc_available=True, lulc_trend="declining")
        det = determine_deforestation_free(enrichment)
        assert det["deforestation_free"] is False
        assert any("declining" in f.lower() for f in det["flags"])

    def test_lulc_evidence_recorded(self):
        enrichment = _make_enrichment(lulc_available=True)
        det = determine_deforestation_free(enrichment)
        assert det["evidence"]["lulc_annual"]["tree_cover_trend"] == "stable"
        assert det["evidence"]["lulc_annual"]["years_available"] == 3

    def test_alos_evidence_recorded(self):
        enrichment = _make_enrichment(alos_available=True, alos_forest_pct=92.5)
        det = determine_deforestation_free(enrichment)
        assert det["evidence"]["alos_fnf"]["forest_pct"] == 92.5
        assert det["evidence"]["alos_fnf"]["source"] == "ALOS-2 PALSAR-2"

    def test_alos_missing_handled(self):
        enrichment = _make_enrichment()  # no alos
        det = determine_deforestation_free(enrichment)
        assert det["evidence"]["alos_fnf"]["available"] is False
