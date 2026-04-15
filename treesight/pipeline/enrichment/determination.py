"""Deforestation-free determination per AOI (#603).

Evaluates enrichment results to produce a binary deforestation-free
determination and structured evidence summary for EUDR compliance.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Thresholds for the algorithmic determination.
# A parcel is "deforestation-free" when ALL conditions hold:
#   1. No significant NDVI-based vegetation loss (loss_pct < threshold)
#   2. No declining trajectory in change detection
# These are conservative defaults; operators can override per-run.
LOSS_PCT_THRESHOLD = 5.0  # % of area showing significant NDVI loss
LOSS_HA_THRESHOLD = 1.0  # minimum hectares of loss to flag
NDVI_DECLINE_THRESHOLD = -0.05  # mean NDVI delta below this = declining


def _assess_change_detection(
    enrichment: dict[str, Any],
    flags: list[str],
    evidence: dict[str, Any],
    *,
    loss_pct_threshold: float,
    loss_ha_threshold: float,
    ndvi_decline_threshold: float,
) -> dict[str, Any]:
    """Assess change detection signals and populate flags/evidence."""
    change = enrichment.get("change_detection", {})
    summary = change.get("summary", {})
    season_changes = change.get("season_changes", [])

    trajectory = summary.get("trajectory", "Insufficient data")
    avg_delta = summary.get("avg_mean_delta")

    evidence["change_detection"] = {
        "trajectory": trajectory,
        "total_loss_ha": summary.get("total_loss_ha", 0.0),
        "total_gain_ha": summary.get("total_gain_ha", 0.0),
        "comparisons": summary.get("comparisons", 0),
        "avg_mean_delta": avg_delta,
    }

    for sc in season_changes:
        loss_pct_val = sc.get("loss_pct", 0)
        loss_ha_val = sc.get("loss_ha", 0)
        if loss_pct_val >= loss_pct_threshold and loss_ha_val >= loss_ha_threshold:
            flags.append(
                f"Vegetation loss {sc['loss_pct']:.1f}% "
                f"({sc['loss_ha']:.1f} ha) in {sc.get('label', '?')}"
            )

    if trajectory == "Declining":
        flags.append("Overall NDVI trajectory is declining")

    if avg_delta is not None and avg_delta < ndvi_decline_threshold:
        flags.append(
            f"Mean NDVI delta {avg_delta:+.4f} below threshold ({ndvi_decline_threshold:+.4f})"
        )

    return summary


def _assess_supplementary_layers(
    enrichment: dict[str, Any],
    flags: list[str],
    evidence: dict[str, Any],
) -> None:
    """Assess WorldCover, WDPA, IO LULC, and ALOS FNF layers."""
    # WorldCover baseline
    worldcover = enrichment.get("worldcover", {})
    if worldcover.get("available"):
        lc = worldcover.get("land_cover", {})
        classes = {c["code"]: c for c in lc.get("classes", [])}
        tree_pct = classes.get(10, {}).get("area_pct", 0.0)
        evidence["worldcover"] = {
            "dominant_class": lc.get("dominant_class"),
            "tree_cover_pct": tree_pct,
        }
    else:
        evidence["worldcover"] = {"available": False}

    # WDPA protected area
    wdpa = enrichment.get("wdpa", {})
    if wdpa.get("is_protected"):
        flags.append("Overlaps a WDPA protected area")
    evidence["wdpa"] = {
        "checked": wdpa.get("checked", False),
        "is_protected": wdpa.get("is_protected", False),
    }

    # IO Annual LULC (#607)
    lulc = enrichment.get("lulc_annual", {})
    if lulc.get("available"):
        evidence["lulc_annual"] = {
            "tree_cover_trend": lulc.get("tree_cover_trend"),
            "change_detected": lulc.get("change_detected", False),
            "years_available": len(lulc.get("years", {})),
        }
        if lulc.get("change_detected"):
            flags.append("IO LULC detected significant land-cover change")
        if lulc.get("tree_cover_trend") == "declining":
            flags.append("IO LULC tree cover trend is declining")
    else:
        evidence["lulc_annual"] = {"available": False}

    # ALOS Forest/Non-Forest (#608)
    alos = enrichment.get("alos_fnf", {})
    if alos.get("available"):
        evidence["alos_fnf"] = {
            "year": alos.get("year"),
            "forest_pct": alos.get("forest_pct", 0.0),
            "dominant_class": alos.get("dominant_class"),
            "source": alos.get("source"),
        }
    else:
        evidence["alos_fnf"] = {"available": False}

    # Landsat historical baseline (#609)
    landsat = enrichment.get("landsat_baseline", {})
    if landsat.get("available"):
        scenes = landsat.get("scenes", [])
        mean_ndvi = round(sum(s["mean"] for s in scenes) / len(scenes), 4) if scenes else None
        evidence["landsat_baseline"] = {
            "scenes": len(scenes),
            "mean_ndvi": mean_ndvi,
            "source": landsat.get("source"),
        }
    else:
        evidence["landsat_baseline"] = {"available": False}


def determine_deforestation_free(
    enrichment: dict[str, Any],
    *,
    loss_pct_threshold: float = LOSS_PCT_THRESHOLD,
    loss_ha_threshold: float = LOSS_HA_THRESHOLD,
    ndvi_decline_threshold: float = NDVI_DECLINE_THRESHOLD,
) -> dict[str, Any]:
    """Evaluate a single AOI's enrichment data for deforestation.

    Parameters
    ----------
    enrichment : dict
        The per-AOI enrichment result dict (from ``_enrich_single_aoi``
        or the main ``run_enrichment`` result).
    loss_pct_threshold : float
        Maximum vegetation loss percentage before flagging.
    loss_ha_threshold : float
        Minimum loss hectares to be considered significant.
    ndvi_decline_threshold : float
        Mean NDVI delta below this value counts as declining.

    Returns
    -------
    dict
        ``{"deforestation_free": bool, "confidence": str,
          "flags": list[str], "evidence": dict}``
    """
    flags: list[str] = []
    evidence: dict[str, Any] = {}

    summary = _assess_change_detection(
        enrichment,
        flags,
        evidence,
        loss_pct_threshold=loss_pct_threshold,
        loss_ha_threshold=loss_ha_threshold,
        ndvi_decline_threshold=ndvi_decline_threshold,
    )

    _assess_supplementary_layers(enrichment, flags, evidence)

    # ── Determination ─────────────────────────────────────────
    has_data = summary.get("comparisons", 0) > 0
    deforestation_free = has_data and len(flags) == 0

    if not has_data:
        confidence = "low"
    elif flags:
        confidence = "medium" if len(flags) == 1 else "high"
    else:
        confidence = "high"

    return {
        "deforestation_free": deforestation_free,
        "confidence": confidence,
        "flags": flags,
        "evidence": evidence,
    }
