"""GeoJSON export builders — standard and EUDR per-parcel (M4 §4.6)."""

from typing import Any

from treesight.pipeline.enrichment.determination import as_screening_determination


def _build_geojson(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection from the enrichment manifest.

    The AOI polygon becomes the geometry; NDVI stats, weather, and frame
    metadata are stored as Feature properties.
    """
    coords = manifest.get("coords", [])
    frame_plan = manifest.get("frame_plan", [])
    ndvi_stats = manifest.get("ndvi_stats", [])
    weather_monthly = manifest.get("weather_monthly")
    change_detection = manifest.get("change_detection", {})

    # Build per-frame features (each frame = one temporal observation)
    features: list[dict[str, Any]] = []
    for i, frame in enumerate(frame_plan):
        ndvi = ndvi_stats[i] if i < len(ndvi_stats) else None
        props: dict[str, Any] = {
            "frame_index": i,
            "label": frame.get("label", ""),
            "year": frame.get("year"),
            "season": frame.get("season", ""),
            "start_date": frame.get("start", ""),
            "end_date": frame.get("end", ""),
            "collection": frame.get("collection", ""),
            "is_naip": frame.get("is_naip", False),
            "provenance": frame.get("provenance", {}),
        }
        if ndvi:
            props["ndvi_mean"] = ndvi.get("mean")
            props["ndvi_min"] = ndvi.get("min")
            props["ndvi_max"] = ndvi.get("max")
            props["ndvi_std"] = ndvi.get("std")
            props["ndvi_scene_id"] = ndvi.get("scene_id")

        # Close polygon ring if needed
        ring = list(coords)
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [ring],
            },
            "properties": props,
        }
        features.append(feature)

    # Summary feature with change-detection & weather data
    summary_props: dict[str, Any] = {
        "type": "summary",
        "enriched_at": manifest.get("enriched_at", ""),
        "enrichment_duration_seconds": manifest.get("enrichment_duration_seconds"),
    }
    if weather_monthly:
        summary_props["weather_monthly"] = weather_monthly
    if change_detection.get("summary"):
        summary_props["change_detection_summary"] = change_detection["summary"]

    center = manifest.get("center", {})
    if center:
        summary_feature: dict[str, Any] = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [center.get("lon", 0), center.get("lat", 0)],
            },
            "properties": summary_props,
        }
        features.append(summary_feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _toplevel_as_single_aoi(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a single-element per-AOI list from top-level manifest evidence.

    Used as fallback when ``per_aoi_enrichment`` is empty (single-parcel runs).
    Returns an empty list if the manifest has no usable evidence.
    """
    if not manifest.get("determination") and not manifest.get("coords"):
        return []
    return [
        {
            "name": manifest.get("feature_name", ""),
            "coords": manifest.get("coords", []),
            "center": manifest.get("center", {}),
            "area_ha": manifest.get("area_ha", 0.0),
            "determination": manifest.get("determination", {}),
            "worldcover": manifest.get("worldcover", {}),
            "wdpa": manifest.get("wdpa", {}),
            "ndvi_stats": manifest.get("ndvi_stats", []),
            "change_detection": manifest.get("change_detection", {}),
        }
    ]


def _build_eudr_geojson(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a per-parcel GeoJSON FeatureCollection with EUDR evidence.

    Each AOI in ``per_aoi_enrichment`` becomes a Feature with EUDR-specific
    properties: determination status, WorldCover baseline, WDPA overlap,
    NDVI summary, and change trajectory.

    For single-parcel runs (no ``per_aoi_enrichment``), falls back to
    top-level manifest evidence.
    """
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if not per_aoi:
        per_aoi = _toplevel_as_single_aoi(manifest)

    features: list[dict[str, Any]] = []
    for aoi in per_aoi:
        props: dict[str, Any] = {"parcel_name": aoi.get("name", "")}

        if "error" in aoi:
            props["error"] = aoi["error"]
            features.append({"type": "Feature", "geometry": None, "properties": props})
            continue

        props["area_ha"] = aoi.get("area_ha", 0.0)
        center = aoi.get("center", {})
        props["center_lat"] = center.get("lat")
        props["center_lon"] = center.get("lon")

        # Screening result
        determination = as_screening_determination(aoi.get("determination"))
        props["determination_status"] = determination.screening_outcome
        props["determination_confidence"] = determination.confidence
        props["determination_flags"] = list(determination.flags)

        # WorldCover baseline
        wc = aoi.get("worldcover", {})
        if wc.get("available"):
            lc = wc.get("land_cover", {})
            props["worldcover_dominant"] = lc.get("dominant_class", "")
            classes = {c["code"]: c for c in lc.get("classes", [])}
            props["worldcover_tree_pct"] = classes.get(10, {}).get("area_pct", 0.0)
        else:
            props["worldcover_dominant"] = ""
            props["worldcover_tree_pct"] = None

        # WDPA
        wdpa = aoi.get("wdpa", {})
        props["wdpa_checked"] = wdpa.get("checked", False)
        props["wdpa_is_protected"] = wdpa.get("is_protected", False)

        # NDVI summary
        ndvi_stats = aoi.get("ndvi_stats", [])
        valid = [s for s in ndvi_stats if s and s.get("mean") is not None]
        if valid:
            props["ndvi_latest_mean"] = valid[-1]["mean"]
            props["ndvi_observations"] = len(valid)
        else:
            props["ndvi_latest_mean"] = None
            props["ndvi_observations"] = 0

        # Change detection
        cd = aoi.get("change_detection", {})
        summary = cd.get("summary", {})
        props["change_trajectory"] = summary.get("trajectory", "unknown")
        props["change_comparisons"] = summary.get("comparisons", 0)

        # Build polygon geometry
        coords = aoi.get("coords", [])
        ring = list(coords)
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])

        geometry: dict[str, Any] | None = {"type": "Polygon", "coordinates": [ring]} if ring else None

        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    return {"type": "FeatureCollection", "features": features}
