"""Raster-level NDVI change detection between time periods (#85).

Compares stored NDVI GeoTIFFs from the enrichment pipeline to quantify
vegetation change — both per-pixel (difference maps) and aggregated
(area of significant gain/loss in hectares).
"""

from __future__ import annotations

import io
import logging
from typing import Any

from treesight.log import log_phase

logger = logging.getLogger(__name__)


def compute_change_map(
    raster_a_bytes: bytes,
    raster_b_bytes: bytes,
    loss_threshold: float = -0.1,
    gain_threshold: float = 0.1,
) -> dict[str, Any] | None:
    """Compute per-pixel NDVI change between two rasters.

    Parameters
    ----------
    raster_a_bytes : bytes
        Earlier NDVI GeoTIFF (baseline).
    raster_b_bytes : bytes
        Later NDVI GeoTIFF (comparison).
    loss_threshold : float
        NDVI decrease below this value counted as "significant loss".
    gain_threshold : float
        NDVI increase above this value counted as "significant gain".

    Returns
    -------
    dict or None
        Change metrics: ``{"mean_delta", "loss_ha", "gain_ha",
        "stable_ha", "total_ha", "loss_pct", "gain_pct",
        "change_geotiff_bytes"}`` on success; None on error.
    """
    import numpy as np
    import rasterio

    try:
        with rasterio.open(io.BytesIO(raster_a_bytes)) as src_a:
            ndvi_a = src_a.read(1)
            profile_a = src_a.profile.copy()
            res_a = src_a.res  # (pixel_width_m, pixel_height_m)

        with rasterio.open(io.BytesIO(raster_b_bytes)) as src_b:
            ndvi_b = src_b.read(1)

        # Ensure same shape — trim to overlap
        min_h = min(ndvi_a.shape[0], ndvi_b.shape[0])
        min_w = min(ndvi_a.shape[1], ndvi_b.shape[1])
        ndvi_a = ndvi_a[:min_h, :min_w]
        ndvi_b = ndvi_b[:min_h, :min_w]

        # Both must have valid (non-NaN) pixels
        valid = np.isfinite(ndvi_a) & np.isfinite(ndvi_b)
        if not np.any(valid):
            return None

        # Pixel-level change: positive = greening, negative = browning
        delta = np.where(valid, ndvi_b - ndvi_a, np.nan)

        valid_deltas = delta[valid]
        pixel_area_m2 = abs(res_a[0] * res_a[1])
        pixel_area_ha = pixel_area_m2 / 10_000  # 1 ha = 10,000 m²

        loss_mask = valid_deltas < loss_threshold
        gain_mask = valid_deltas > gain_threshold
        stable_mask = ~loss_mask & ~gain_mask

        n_valid = int(np.sum(valid))
        n_loss = int(np.sum(loss_mask))
        n_gain = int(np.sum(gain_mask))
        n_stable = int(np.sum(stable_mask))

        result: dict[str, Any] = {
            "mean_delta": round(float(np.mean(valid_deltas)), 4),
            "median_delta": round(float(np.median(valid_deltas)), 4),
            "std_delta": round(float(np.std(valid_deltas)), 4),
            "min_delta": round(float(np.min(valid_deltas)), 4),
            "max_delta": round(float(np.max(valid_deltas)), 4),
            "loss_ha": round(n_loss * pixel_area_ha, 2),
            "gain_ha": round(n_gain * pixel_area_ha, 2),
            "stable_ha": round(n_stable * pixel_area_ha, 2),
            "total_ha": round(n_valid * pixel_area_ha, 2),
            "loss_pct": round(n_loss / n_valid * 100, 1) if n_valid else 0.0,
            "gain_pct": round(n_gain / n_valid * 100, 1) if n_valid else 0.0,
            "valid_pixels": n_valid,
        }

        # Write change map as GeoTIFF
        buf = io.BytesIO()
        write_profile = profile_a.copy()
        write_profile.update(
            count=1,
            dtype="float32",
            nodata=np.nan,
            height=min_h,
            width=min_w,
            compress="deflate",
        )
        with rasterio.open(buf, "w", **write_profile) as dst:
            dst.write(delta[np.newaxis, :, :])

        result["change_geotiff_bytes"] = buf.getvalue()
        return result

    except Exception as exc:
        logger.warning("Change map computation failed: %s", exc)
        return None


def detect_changes(
    frame_plan: list[dict[str, Any]],
    ndvi_raster_paths: list[str | None],
    output_container: str,
    project_name: str,
    timestamp: str,
    storage: Any,
) -> dict[str, Any]:
    """Run change detection across stored NDVI rasters.

    Compares same-season rasters year-over-year (e.g. Summer 2022 vs
    Summer 2023) to produce change metrics and diff maps.

    Parameters
    ----------
    frame_plan : list[dict]
        Frame metadata with ``year``, ``season``, ``label`` keys.
    ndvi_raster_paths : list[str | None]
        Blob paths for each frame's NDVI GeoTIFF (None if unavailable).
    output_container : str
        Blob container for storing change maps.
    project_name, timestamp : str
        For building output blob paths.
    storage : BlobStorageClient
        Storage client.

    Returns
    -------
    dict
        ``{"season_changes": [...], "summary": {...}}``.
    """
    log_phase("change_detection", "start", frames=len(frame_plan))

    # Group frames by season with their raster paths
    season_groups: dict[str, list[tuple[int, int, str]]] = {}
    for i, f in enumerate(frame_plan):
        raster_path = ndvi_raster_paths[i] if i < len(ndvi_raster_paths) else None
        if raster_path and f.get("season") and f.get("year"):
            season = f["season"]
            season_groups.setdefault(season, []).append((int(f["year"]), i, raster_path))

    # Sort each season group by year
    for group in season_groups.values():
        group.sort(key=lambda x: x[0])

    season_changes: list[dict[str, Any]] = []
    all_deltas: list[float] = []
    total_loss_ha = 0.0
    total_gain_ha = 0.0

    for season, frames in sorted(season_groups.items()):
        if len(frames) < 2:
            continue

        # Compare consecutive years within same season
        for j in range(1, len(frames)):
            year_a, _idx_a, path_a = frames[j - 1]
            year_b, _idx_b, path_b = frames[j]

            try:
                raster_a = storage.download_bytes(output_container, path_a)
                raster_b = storage.download_bytes(output_container, path_b)
            except Exception as exc:
                logger.warning(
                    "Failed to load rasters for %s %d→%d: %s",
                    season,
                    year_a,
                    year_b,
                    exc,
                )
                continue

            change = compute_change_map(raster_a, raster_b)
            if change is None:
                continue

            # Store change map GeoTIFF
            change_geotiff = change.pop("change_geotiff_bytes", None)
            change_path = None
            if change_geotiff:
                change_path = (
                    f"enrichment/{project_name}/{timestamp}"
                    f"/change/{season}_{year_a}_to_{year_b}.tif"
                )
                storage.upload_bytes(
                    output_container,
                    change_path,
                    change_geotiff,
                    content_type="image/tiff",
                )

            entry = {
                "season": season,
                "year_from": year_a,
                "year_to": year_b,
                "label": f"{season.capitalize()} {year_a} → {year_b}",
                "change_map_path": change_path,
                **change,
            }
            season_changes.append(entry)
            all_deltas.append(change["mean_delta"])
            total_loss_ha += change["loss_ha"]
            total_gain_ha += change["gain_ha"]

    # Overall summary
    summary: dict[str, Any] = {
        "comparisons": len(season_changes),
        "total_loss_ha": round(total_loss_ha, 2),
        "total_gain_ha": round(total_gain_ha, 2),
    }

    if all_deltas:
        avg_delta = sum(all_deltas) / len(all_deltas)
        summary["avg_mean_delta"] = round(avg_delta, 4)
        summary["trajectory"] = (
            "Improving" if avg_delta > 0.02 else "Declining" if avg_delta < -0.02 else "Stable"
        )
    else:
        summary["avg_mean_delta"] = None
        summary["trajectory"] = "Insufficient data"

    log_phase(
        "change_detection",
        "done",
        comparisons=summary["comparisons"],
        trajectory=summary.get("trajectory"),
    )

    return {"season_changes": season_changes, "summary": summary}
