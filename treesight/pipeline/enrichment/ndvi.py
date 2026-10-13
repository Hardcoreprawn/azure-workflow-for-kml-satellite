"""NDVI computation from Sentinel-2 COGs and PC tile sampling.

Design decision: Sentinel-2 L2A is the sole NDVI source.  NAIP is used only
for high-resolution visual context (before/after comparison).  NAIP imagery
may be 3-band (RGB) in some states/years; if NAIP NDVI is added later, the
caller must verify that the scene has ≥4 bands (RGBN) before computing.

Two approaches available:
- ``compute_ndvi``: proper band-math from B04/B08 COGs via rasterio (accurate,
  produces GeoTIFFs for downstream change detection)
- ``fetch_ndvi_stat``: lightweight PC tile-based sampling via PNG parsing (fast,
  used for enrichment timeline overview)
"""

from __future__ import annotations

import io
import logging
import math
import struct
import zlib
from itertools import islice, pairwise
from typing import Any, cast

import httpx

from treesight.constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    MAX_NDVI_SCENE_CANDIDATES,
    MAX_RASTER_GEOMETRY_DENSIFICATION_DEPTH,
    MIN_VALID_NDVI_COVERAGE_FRACTION,
    MIN_VALID_NDVI_PIXELS,
    RASTER_GEOMETRY_DENSIFICATION_TOLERANCE_PIXELS,
)
from treesight.geo import transform_bbox
from treesight.log import log_phase
from treesight.pipeline.enrichment.mosaic import PC_API

logger = logging.getLogger(__name__)

# ── Optional Rust acceleration ────────────────────────────────
try:
    import treesight_rs as _rs
except ImportError:  # pragma: no cover — Rust extension not installed
    _rs = None  # type: ignore[assignment]

# ── STAC search helper ────────────────────────────────────────

STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _find_best_s2_scene(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 20.0,
    *,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Search ordered Sentinel-2 candidates for one covering the full AOI.

    Returns a dict with ``{"B04": url, "B08": url, "scene_id": ..., ...}``
    plus an optional ``"SCL"`` key when the Scene Classification Layer is
    available, or None if nothing suitable was found.
    """
    import planetary_computer
    from pystac_client import Client

    catalog = Client.open(STAC_API, modifier=planetary_computer.sign_inplace)
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{date_start}/{date_end}",
        query={"eo:cloud_cover": {"lte": max_cloud}},
        sortby=[{"field": "eo:cloud_cover", "direction": "asc"}],
    )

    for item in islice(search.items(), MAX_NDVI_SCENE_CANDIDATES):
        b04 = item.assets.get("B04")
        b08 = item.assets.get("B08")
        scl = item.assets.get("SCL")
        if not b04 or not b08 or not scl:
            continue
        if geometry is not None:
            asset_hrefs = [
                (b04.href, "reflectance", None),
                (b08.href, "reflectance", b04.href),
                (scl.href, "scl", b04.href),
            ]
            try:
                if not all(
                    _cog_asset_covers_geometry(href, geometry, asset_kind=asset_kind, reference_url=reference_url)
                    for href, asset_kind, reference_url in asset_hrefs
                ):
                    continue
            except Exception:
                logger.warning("Could not verify full AOI coverage for S2 item %s", item.id, exc_info=True)
                continue

        result: dict[str, Any] = {
            "scene_id": item.id,
            "B04": b04.href,
            "B08": b08.href,
            "cloud_cover": item.properties.get("eo:cloud_cover", 0.0),
            "datetime": item.properties.get("datetime", ""),
            "crs": f"EPSG:{item.properties.get('proj:epsg', 32632)}",
        }
        result["SCL"] = scl.href
        return result
    return None


# ── COG-based NDVI computation ────────────────────────────────

# SCL (Scene Classification Layer) valid pixel classes for NDVI.
# See: https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview
VALID_SCL_CLASSES = (
    2,  # Dark area pixels
    4,  # Vegetation
    5,  # Bare soils
    6,  # Water (optional — valid surface, NDVI ≈ −0.1 to 0)
)


def _raster_geometry_mask(
    geometry: dict[str, Any],
    profile: dict[str, Any],
    shape: tuple[int, int],
) -> Any:
    """Rasterize densified EPSG:4326 plot geometry on a band's native grid."""
    from rasterio.features import geometry_mask

    raster_crs = profile.get("crs")
    transform = profile.get("transform")
    if raster_crs is None or transform is None:
        raise ValueError("Raster profile is missing CRS or transform")

    raster_geometry = _project_geometry_to_raster_crs(geometry, profile)
    return geometry_mask(
        [raster_geometry],
        out_shape=shape,
        transform=transform,
        all_touched=False,
        invert=True,
    )


def _project_geometry_to_raster_crs(geometry: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    from pyproj import Transformer

    raster_crs = profile.get("crs")
    transform = profile.get("transform")
    if raster_crs is None or transform is None:
        raise ValueError("Raster profile is missing CRS or transform")

    pixel_width = math.hypot(transform.a, transform.d)
    pixel_height = math.hypot(transform.b, transform.e)
    if min(pixel_width, pixel_height) <= 0:
        raise ValueError("Raster profile has invalid pixel size")
    tolerance = min(pixel_width, pixel_height) * RASTER_GEOMETRY_DENSIFICATION_TOLERANCE_PIXELS
    transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)):
        raise ValueError("Raster geometry is missing coordinates")
    if geometry_type == "Polygon":
        projected_coordinates = [_densified_project_ring(ring, transformer, tolerance) for ring in coordinates]
    elif geometry_type == "MultiPolygon":
        projected_coordinates = [
            [_densified_project_ring(ring, transformer, tolerance) for ring in polygon] for polygon in coordinates
        ]
    else:
        raise ValueError(f"Unsupported raster geometry type: {geometry_type}")
    return {"type": geometry_type, "coordinates": projected_coordinates}


def _densified_project_ring(
    coordinates: list[list[float]],
    transformer: Any,
    tolerance: float,
) -> list[tuple[float, float]]:
    if len(coordinates) < 2:
        return [transformer.transform(*point) for point in coordinates]

    projected_ring = [transformer.transform(*coordinates[0])]
    for left, right in pairwise(coordinates):
        left_xy = transformer.transform(*left)
        right_xy = transformer.transform(*right)
        pending = [(left, right, left_xy, right_xy, 0)]
        while pending:
            segment_left, segment_right, left_projected, right_projected, depth = pending.pop()
            fractions = (0.25, 0.5, 0.75)
            sample_errors = []
            for fraction in fractions:
                source_sample = [
                    segment_left[axis] + (segment_right[axis] - segment_left[axis]) * fraction for axis in (0, 1)
                ]
                projected_sample = transformer.transform(*source_sample)
                chord_sample = tuple(
                    left_projected[axis] + (right_projected[axis] - left_projected[axis]) * fraction for axis in (0, 1)
                )
                sample_errors.append(math.dist(projected_sample, chord_sample))

            if max(sample_errors) <= tolerance:
                projected_ring.append(right_projected)
                continue
            if depth >= MAX_RASTER_GEOMETRY_DENSIFICATION_DEPTH:
                raise ValueError("Projected geometry edge did not meet pixel tolerance")

            midpoint = [(segment_left[axis] + segment_right[axis]) / 2 for axis in (0, 1)]
            midpoint_projected = transformer.transform(*midpoint)
            pending.append((midpoint, segment_right, midpoint_projected, right_projected, depth + 1))
            pending.append((segment_left, midpoint, left_projected, midpoint_projected, depth + 1))

    return projected_ring


def compute_ndvi(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 20.0,
    *,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Compute NDVI from Sentinel-2 B04/B08 COGs for the given bbox and date range.

    Uses COG windowed reads (HTTP range requests) to fetch only the pixels
    covering the bounding box.  Calculates ``(B08 − B04) / (B08 + B04)``
    and returns statistics plus the NDVI raster as GeoTIFF bytes.

    Parameters
    ----------
    bbox : list[float]
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.
    date_start, date_end : str
        ISO date strings for the search window.
    max_cloud : float
        Maximum cloud cover percentage.

    Returns
    -------
    dict or None
        ``{"mean", "min", "max", "std", "median", "valid_pixels",
        "total_pixels", "scene_id", "cloud_cover", "datetime",
        "scl_applied", "scl_masked_pixels", "geotiff_bytes"}`` on success;
        None if geometry or in-plot pixels are unavailable, or no scene is found.
    """
    if geometry is None:
        log_phase("ndvi", "geometry_unavailable")
        return None

    import numpy as np
    import rasterio

    log_phase("ndvi", "search_start", bbox=bbox, window=f"{date_start}/{date_end}")

    scene = _find_best_s2_scene(bbox, date_start, date_end, max_cloud, geometry=geometry)
    if not scene:
        log_phase("ndvi", "no_scene_found")
        return None

    log_phase(
        "ndvi",
        "reading_bands",
        scene_id=scene["scene_id"],
        cloud_cover=scene["cloud_cover"],
    )

    try:
        # Read B04 (Red) windowed to bbox
        b04_data, b04_profile = _cog_band_read(scene["B04"], bbox)
        # Read B08 (NIR) windowed to bbox
        b08_data, b08_profile = _cog_band_read(scene["B08"], bbox)

        if not _raster_covers_geometry(geometry, b04_profile) or not _raster_covers_geometry(geometry, b08_profile):
            log_phase("ndvi", "source_scene_does_not_cover_geometry", scene_id=scene["scene_id"])
            return None

        b08_data = _reproject_to_grid(b08_data, b08_profile, b04_profile, b04_data.shape, categorical=False)

        # Read SCL band for pixel-level cloud masking (20 m → resample to 10 m)
        scl_mask = None
        scl_masked_count = 0
        if not scene.get("SCL"):
            log_phase("ndvi", "scl_unavailable", scene_id=scene["scene_id"])
            return None
        try:
            scl_data, scl_profile = _cog_band_read(scene["SCL"], bbox)
            if not _raster_covers_geometry(geometry, scl_profile):
                log_phase("ndvi", "scl_scene_does_not_cover_geometry", scene_id=scene["scene_id"])
                return None
            scl_mask = _reproject_to_grid(scl_data, scl_profile, b04_profile, b04_data.shape, categorical=True)
            log_phase("ndvi", "scl_loaded", scene_id=scene["scene_id"])
        except Exception as scl_exc:
            logger.warning("SCL read failed for %s: %s", scene["scene_id"], scl_exc)
            return None

        plot_mask = _raster_geometry_mask(geometry, b04_profile, b04_data.shape)
        source_coverage = _source_coverage_on_grid(b04_profile, b04_profile, b04_data.shape)
        source_coverage &= _source_coverage_on_grid(b08_profile, b04_profile, b04_data.shape)
        source_coverage &= _source_coverage_on_grid(scl_profile, b04_profile, b04_data.shape)
        source_coverage &= scl_mask != 0
        if np.any(plot_mask & ~source_coverage):
            log_phase("ndvi", "source_pixels_do_not_cover_geometry", scene_id=scene["scene_id"])
            return None

        # Convert to float for band math
        red = b04_data.astype(np.float32)
        nir = b08_data.astype(np.float32)

        if _rs is not None:
            # Rust-accelerated NDVI: parallel SIMD band math
            ndvi, valid_mask = _rs.compute_ndvi_array(red, nir)
            valid_mask_before_scl = valid_mask.copy()

            # Apply SCL mask via Rust (in-place)
            if scl_mask is not None:
                _rs.apply_scl_mask(
                    valid_mask,
                    scl_mask.astype(np.uint8),
                    list(VALID_SCL_CLASSES),
                )
        else:
            # Pure-Python fallback
            denom = nir + red
            with np.errstate(invalid="ignore", divide="ignore"):
                ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
            valid_mask = (b04_data > 0) & (b08_data > 0) & np.isfinite(ndvi)
            valid_mask_before_scl = valid_mask.copy()
            if scl_mask is not None:
                scl_valid = np.isin(scl_mask, VALID_SCL_CLASSES)
                valid_mask = valid_mask & scl_valid

        geometry_masked_count = int(np.count_nonzero(~plot_mask))
        if scl_mask is not None:
            scl_valid = np.isin(scl_mask, VALID_SCL_CLASSES)
            scl_masked_count = int(np.count_nonzero(valid_mask_before_scl & plot_mask & ~scl_valid))
        valid_mask = valid_mask & plot_mask

        valid_pixels = ndvi[valid_mask]
        total_pixels = int(np.count_nonzero(plot_mask))
        valid_coverage = len(valid_pixels) / total_pixels if total_pixels else 0.0

        if len(valid_pixels) < MIN_VALID_NDVI_PIXELS or valid_coverage < MIN_VALID_NDVI_COVERAGE_FRACTION:
            log_phase(
                "ndvi",
                "insufficient_in_plot_pixels",
                scene_id=scene["scene_id"],
                valid_pixels=len(valid_pixels),
                total_pixels=total_pixels,
                valid_coverage=valid_coverage,
                minimum_valid_pixels=MIN_VALID_NDVI_PIXELS,
                minimum_valid_coverage=MIN_VALID_NDVI_COVERAGE_FRACTION,
            )
            return None

        stats = {
            "mean": round(float(np.mean(valid_pixels)), 4),
            "min": round(float(np.min(valid_pixels)), 4),
            "max": round(float(np.max(valid_pixels)), 4),
            "std": round(float(np.std(valid_pixels)), 4),
            "median": round(float(np.median(valid_pixels)), 4),
            "valid_pixels": len(valid_pixels),
            "total_pixels": total_pixels,
            "scl_masked_pixels": scl_masked_count,
            "scl_applied": scl_mask is not None,
            "geometry_mask_applied": True,
            "geometry_masked_pixels": geometry_masked_count,
            "geometry_mask_method": "pixel-center",
            "aoi_geometry_type": geometry.get("type", "unknown"),
            "scene_id": scene["scene_id"],
            "cloud_cover": scene["cloud_cover"],
            "datetime": scene["datetime"],
        }

        # Write NDVI raster as single-band float32 GeoTIFF
        # Apply valid_mask so change detection only compares clean surface pixels
        # (cloud/shadow/snow/nodata pixels are set to NaN)
        ndvi_masked = np.where(valid_mask, ndvi, np.nan)
        buf = io.BytesIO()
        profile = b04_profile.copy()
        profile.pop("_source_bounds", None)
        profile.pop("_source_valid_mask", None)
        profile.update(
            count=1,
            dtype="float32",
            nodata=np.nan,
            height=ndvi.shape[0],
            width=ndvi.shape[1],
            compress="deflate",
        )
        with rasterio.open(buf, "w", **profile) as dst:
            dst.write(ndvi_masked[np.newaxis, :, :])

        stats["geotiff_bytes"] = buf.getvalue()

        log_phase(
            "ndvi",
            "compute_done",
            scene_id=scene["scene_id"],
            mean=stats["mean"],
            valid_pixels=stats["valid_pixels"],
            raster_kb=len(stats["geotiff_bytes"]) // 1024,
        )
        return stats

    except Exception as exc:
        logger.warning("NDVI computation failed for %s: %s", scene.get("scene_id"), exc)
        return None


# ── Landsat NDVI for historical baseline (#609) ──────────────

# Landsat QA_PIXEL bits to exclude (Collection 2 Level 2).
# Bits 0-5 mark fill, dilated cloud, cirrus, cloud, shadow, and snow.
_LANDSAT_QA_INVALID_MASK = 0b00111111
_LANDSAT_QA_FILL_FLAG = 1 << 0
_LANDSAT_QA_WARP_NODATA = 0xFFFF
_LANDSAT_SR_SCALE = 0.0000275
_LANDSAT_SR_OFFSET = -0.2


def _find_best_landsat_scene(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 30.0,
    *,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Search ordered Landsat C2 L2 candidates for one covering the full AOI."""
    import planetary_computer
    from pystac_client import Client

    catalog = Client.open(STAC_API, modifier=planetary_computer.sign_inplace)
    search = catalog.search(
        collections=["landsat-c2-l2"],
        bbox=bbox,
        datetime=f"{date_start}/{date_end}",
        query={"eo:cloud_cover": {"lte": max_cloud}},
        sortby=[{"field": "eo:cloud_cover", "direction": "asc"}],
    )

    for item in islice(search.items(), MAX_NDVI_SCENE_CANDIDATES):
        red = item.assets.get("red")
        nir = item.assets.get("nir08")
        qa = item.assets.get("qa_pixel")
        if not red or not nir or not qa:
            continue
        if geometry is not None:
            asset_hrefs = [
                (red.href, "reflectance", None),
                (nir.href, "reflectance", red.href),
                (qa.href, "landsat_qa", red.href),
            ]
            try:
                if not all(
                    _cog_asset_covers_geometry(href, geometry, asset_kind=asset_kind, reference_url=reference_url)
                    for href, asset_kind, reference_url in asset_hrefs
                ):
                    continue
            except Exception:
                logger.warning("Could not verify full AOI coverage for Landsat item %s", item.id, exc_info=True)
                continue

        result: dict[str, Any] = {
            "scene_id": item.id,
            "red": red.href,
            "nir": nir.href,
            "cloud_cover": item.properties.get("eo:cloud_cover", 0.0),
            "datetime": item.properties.get("datetime", ""),
            "crs": f"EPSG:{item.properties.get('proj:epsg', 32632)}",
        }
        result["qa_pixel"] = qa.href
        return result
    return None


def compute_landsat_ndvi(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 30.0,
    *,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Compute NDVI from Landsat C2 L2 Red/NIR08 COGs.

    Mirrors ``compute_ndvi`` but uses Landsat band names and QA_PIXEL
    for cloud masking instead of Sentinel-2 SCL.

    Parameters
    ----------
    bbox : list[float]
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.
    date_start, date_end : str
        ISO date strings for the search window.
    max_cloud : float
        Maximum cloud cover percentage (higher default for Landsat).

    Returns
    -------
    dict or None
        Same structure as ``compute_ndvi`` on success; None if no scene.
    """
    if geometry is None:
        log_phase("ndvi", "landsat_geometry_unavailable")
        return None

    import numpy as np
    import rasterio

    log_phase(
        "ndvi",
        "landsat_search_start",
        bbox=bbox,
        window=f"{date_start}/{date_end}",
    )

    scene = _find_best_landsat_scene(bbox, date_start, date_end, max_cloud, geometry=geometry)
    if not scene:
        log_phase("ndvi", "landsat_no_scene")
        return None
    if not scene.get("qa_pixel"):
        log_phase("ndvi", "landsat_qa_unavailable", scene_id=scene["scene_id"])
        return None

    log_phase(
        "ndvi",
        "landsat_reading_bands",
        scene_id=scene["scene_id"],
        cloud_cover=scene["cloud_cover"],
    )

    try:
        red_data, red_profile = _cog_band_read(scene["red"], bbox)
        nir_data, nir_profile = _cog_band_read(scene["nir"], bbox)

        if not _raster_covers_geometry(geometry, red_profile) or not _raster_covers_geometry(geometry, nir_profile):
            log_phase("ndvi", "landsat_source_scene_does_not_cover_geometry", scene_id=scene["scene_id"])
            return None

        nir_data = _reproject_to_grid(nir_data, nir_profile, red_profile, red_data.shape, categorical=False)
        source_coverage = _source_coverage_on_grid(red_profile, red_profile, red_data.shape)
        source_coverage &= _source_coverage_on_grid(nir_profile, red_profile, red_data.shape)

        # QA_PIXEL cloud masking
        qa_mask = None
        qa_masked_count = 0
        try:
            qa_data, qa_profile = _cog_band_read(scene["qa_pixel"], bbox)
            if not _raster_covers_geometry(geometry, qa_profile):
                log_phase("ndvi", "landsat_qa_does_not_cover_geometry", scene_id=scene["scene_id"])
                return None
            qa_data = _reproject_to_grid(
                qa_data,
                qa_profile,
                red_profile,
                red_data.shape,
                categorical=True,
                destination_nodata=_LANDSAT_QA_WARP_NODATA,
            )
            source_coverage &= _source_coverage_on_grid(qa_profile, red_profile, red_data.shape)
            source_coverage &= (qa_data.astype(np.uint16) & _LANDSAT_QA_FILL_FLAG) == 0
            qa_mask = (qa_data.astype(np.uint16) & _LANDSAT_QA_INVALID_MASK) == 0
        except Exception:
            logger.warning("Landsat QA_PIXEL read failed for %s", scene["scene_id"], exc_info=True)
            return None

        plot_mask = _raster_geometry_mask(geometry, red_profile, red_data.shape)
        if np.any(plot_mask & ~source_coverage):
            log_phase("ndvi", "landsat_source_pixels_do_not_cover_geometry", scene_id=scene["scene_id"])
            return None

        red = red_data.astype(np.float32) * _LANDSAT_SR_SCALE + _LANDSAT_SR_OFFSET
        nir = nir_data.astype(np.float32) * _LANDSAT_SR_SCALE + _LANDSAT_SR_OFFSET

        denom = nir + red
        with np.errstate(invalid="ignore", divide="ignore"):
            ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
        valid_mask = (red_data > 0) & (nir_data > 0) & np.isfinite(ndvi) & (ndvi >= -1.0) & (ndvi <= 1.0)
        valid_mask_before_qa = valid_mask.copy()

        if qa_mask is not None:
            valid_mask = valid_mask & qa_mask

        geometry_masked_count = int(np.count_nonzero(~plot_mask))
        if qa_mask is not None:
            qa_masked_count = int(np.count_nonzero(valid_mask_before_qa & plot_mask & ~qa_mask))
        valid_mask = valid_mask & plot_mask

        valid_pixels = ndvi[valid_mask]
        total_pixels = int(np.count_nonzero(plot_mask))
        valid_coverage = len(valid_pixels) / total_pixels if total_pixels else 0.0
        if len(valid_pixels) < MIN_VALID_NDVI_PIXELS or valid_coverage < MIN_VALID_NDVI_COVERAGE_FRACTION:
            log_phase(
                "ndvi",
                "landsat_insufficient_in_plot_pixels",
                scene_id=scene["scene_id"],
                valid_pixels=len(valid_pixels),
                total_pixels=total_pixels,
                valid_coverage=valid_coverage,
                minimum_valid_pixels=MIN_VALID_NDVI_PIXELS,
                minimum_valid_coverage=MIN_VALID_NDVI_COVERAGE_FRACTION,
            )
            return None

        ndvi_masked = np.where(valid_mask, ndvi, np.nan)
        buf = io.BytesIO()
        profile = red_profile.copy()
        profile.pop("_source_bounds", None)
        profile.pop("_source_valid_mask", None)
        profile.update(
            count=1,
            dtype="float32",
            nodata=np.nan,
            height=ndvi.shape[0],
            width=ndvi.shape[1],
            compress="deflate",
        )
        with rasterio.open(buf, "w", **profile) as dst:
            dst.write(ndvi_masked[np.newaxis, :, :])

        stats = {
            "mean": round(float(np.mean(valid_pixels)), 4),
            "min": round(float(np.min(valid_pixels)), 4),
            "max": round(float(np.max(valid_pixels)), 4),
            "std": round(float(np.std(valid_pixels)), 4),
            "median": round(float(np.median(valid_pixels)), 4),
            "valid_pixels": len(valid_pixels),
            "total_pixels": total_pixels,
            "qa_masked_pixels": qa_masked_count,
            "qa_applied": qa_mask is not None,
            "geometry_mask_applied": True,
            "geometry_masked_pixels": geometry_masked_count,
            "geometry_mask_method": "pixel-center",
            "aoi_geometry_type": geometry.get("type", "unknown"),
            "scene_id": scene["scene_id"],
            "cloud_cover": scene["cloud_cover"],
            "datetime": scene["datetime"],
            "source": "landsat-c2-l2",
            "geotiff_bytes": buf.getvalue(),
        }

        log_phase(
            "ndvi",
            "landsat_compute_done",
            scene_id=scene["scene_id"],
            mean=stats["mean"],
            valid_pixels=stats["valid_pixels"],
        )
        return stats

    except Exception as exc:
        logger.warning("Landsat NDVI failed for %s: %s", scene.get("scene_id"), exc)
        return None


def _cog_band_read(
    url: str,
    bbox: list[float],
) -> tuple[Any, dict[str, Any]]:
    """Read a single band from a COG, windowed to bbox.

    Returns (2d_array, profile_dict).
    """
    import rasterio
    from rasterio.windows import from_bounds as window_from_bounds

    with rasterio.open(url) as src:
        src_bbox = transform_bbox(bbox, "EPSG:4326", str(src.crs))
        # Rasterio's Window runtime has offsets/lengths missing from its stubs.
        window = cast(Any, window_from_bounds(*src_bbox, transform=src.transform))
        col_start = math.floor(window.col_off)
        row_start = math.floor(window.row_off)
        col_end = math.ceil(window.col_off + window.width)
        row_end = math.ceil(window.row_off + window.height)
        window = rasterio.windows.Window(
            col_start,
            row_start,
            col_end - col_start,
            row_end - row_start,
        )
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        data = src.read(1, window=window)
        profile = {
            "driver": "GTiff",
            "crs": src.crs,
            "transform": src.window_transform(window),
            "nodata": src.nodata,
            "_source_bounds": tuple(src.bounds),
            "_source_valid_mask": cast(Any, src).read_masks(1, window=window).astype(bool),
        }
    return data, profile


def _reproject_to_grid(
    data: Any,
    source_profile: dict[str, Any],
    target_profile: dict[str, Any],
    target_shape: tuple[int, int],
    *,
    categorical: bool,
    destination_nodata: int | float = 0,
) -> Any:
    import numpy as np
    from rasterio.warp import Resampling, reproject

    source_crs = source_profile.get("crs")
    source_transform = source_profile.get("transform")
    target_crs = target_profile.get("crs")
    target_transform = target_profile.get("transform")
    if any(value is None for value in (source_crs, source_transform, target_crs, target_transform)):
        raise ValueError("Raster profile is missing CRS or transform")

    destination_dtype = data.dtype if categorical else np.float32
    destination = np.full(target_shape, destination_nodata, dtype=destination_dtype)
    resampling: Resampling = Resampling.nearest if categorical else Resampling.bilinear
    reproject(
        source=data,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=source_profile.get("nodata"),
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=destination_nodata,
        resampling=resampling,
    )
    return destination


def _source_coverage_on_grid(
    source_profile: dict[str, Any],
    target_profile: dict[str, Any],
    target_shape: tuple[int, int],
) -> Any:
    import numpy as np

    source_valid_mask = source_profile.get("_source_valid_mask")
    if source_valid_mask is None:
        return np.ones(target_shape, dtype=bool)

    mask_profile = {**source_profile, "nodata": None}
    aligned_mask = _reproject_to_grid(
        source_valid_mask.astype(np.uint8),
        mask_profile,
        target_profile,
        target_shape,
        categorical=True,
        destination_nodata=0,
    )
    return aligned_mask.astype(bool)


def _raster_covers_geometry(geometry: dict[str, Any], profile: dict[str, Any]) -> bool:
    from shapely.geometry import box, shape

    source_bounds = profile.get("_source_bounds")
    if source_bounds is None:
        return False
    projected = shape(_project_geometry_to_raster_crs(geometry, profile))
    transform = profile["transform"]
    pixel_size = max(abs(transform.a), abs(transform.e))
    coverage_bounds = box(*source_bounds).buffer(pixel_size * 1e-6)
    return coverage_bounds.covers(projected)


def _cog_asset_covers_geometry(
    url: str,
    geometry: dict[str, Any],
    *,
    asset_kind: str,
    reference_url: str | None = None,
) -> bool:
    import numpy as np
    from shapely.geometry import shape

    geometry_bounds = list(shape(geometry).bounds)
    data, source_profile = _cog_band_read(url, geometry_bounds)
    if not _raster_covers_geometry(geometry, source_profile):
        return False

    target_data = data
    target_profile = source_profile
    if reference_url is not None:
        target_data, target_profile = _cog_band_read(reference_url, geometry_bounds)
        if not _raster_covers_geometry(geometry, target_profile):
            return False

    source_coverage = source_profile["_source_valid_mask"].copy()
    if asset_kind == "reflectance":
        source_coverage &= data > 0
    elif asset_kind == "scl":
        source_coverage &= data != 0
    elif asset_kind == "landsat_qa":
        source_coverage &= (data.astype(np.uint16) & _LANDSAT_QA_FILL_FLAG) == 0
    else:
        raise ValueError(f"Unsupported raster asset kind: {asset_kind}")

    if reference_url is not None:
        source_coverage = _reproject_to_grid(
            source_coverage.astype(np.uint8),
            {**source_profile, "nodata": None},
            target_profile,
            target_data.shape,
            categorical=True,
        ).astype(bool)

    plot_mask = _raster_geometry_mask(geometry, target_profile, target_data.shape)
    return bool(np.all(source_coverage[plot_mask]))


def _resample_scl(
    scl_data: Any,
    target_shape: tuple[int, int],
) -> Any:
    """Resample SCL (20 m) to target shape (10 m) via nearest-neighbour.

    SCL is categorical — interpolation would produce invalid class values.
    Uses numpy index mapping instead of scipy to avoid an extra dependency.
    """
    import numpy as np

    if scl_data.shape == target_shape:
        return scl_data

    # Map target pixel centres to source indices and round to nearest (true NN).
    row_scale = scl_data.shape[0] / target_shape[0]
    col_scale = scl_data.shape[1] / target_shape[1]
    row_coords = (np.arange(target_shape[0]) + 0.5) * row_scale - 0.5
    col_coords = (np.arange(target_shape[1]) + 0.5) * col_scale - 0.5
    row_idx = np.rint(row_coords).astype(int)
    col_idx = np.rint(col_coords).astype(int)
    np.clip(row_idx, 0, scl_data.shape[0] - 1, out=row_idx)
    np.clip(col_idx, 0, scl_data.shape[1] - 1, out=col_idx)
    return scl_data[np.ix_(row_idx, col_idx)]


def fetch_ndvi_stat(
    search_id: str,
    coords: list[list[float]],
    client: httpx.Client | None = None,
) -> dict[str, float] | None:
    """Sample NDVI from a single PC tile at z12 — mirrors frontend logic.

    Uses the PC statistics endpoint instead of pixel-level tile parsing,
    which avoids needing Pillow/PIL.
    """
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    lat = (min(lats) + max(lats)) / 2
    lon = (min(lons) + max(lons)) / 2

    z = 12
    n = 2**z
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)

    # Use the tile info endpoint to get statistics without downloading pixels
    url = (
        f"{PC_API}/mosaic/tiles/{search_id}"
        f"/WebMercatorQuad/{z}/{x}/{y}@1x"
        f"?collection=sentinel-2-l2a&assets=B08&assets=B04"
        f"&expression=(B08_b1-B04_b1)/(B08_b1%2BB04_b1)"
        f"&rescale=-0.2,0.8&nodata=0&format=png"
    )
    _owns_client = client is None
    http = client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS, trust_env=False)
    try:
        r = http.get(url)
        if r.status_code != 200:
            return None

        # Parse PNG pixel data directly using struct/zlib (no PIL needed)
        png_data = r.content
        ndvi_values = _extract_red_channel_from_png(png_data)
        if not ndvi_values:
            return None

        # Map red channel (0-255) back to NDVI range (-0.2 to 0.8)
        mapped = [-0.2 + (v / 255) * 1.0 for v in ndvi_values]
        mean_v = sum(mapped) / len(mapped)
        return {
            "mean": round(mean_v, 3),
            "min": round(min(mapped), 3),
            "max": round(max(mapped), 3),
        }
    except Exception as exc:
        logger.warning("NDVI stat fetch failed for %s: %s", search_id, exc)
        return None
    finally:
        if _owns_client:
            http.close()


def _extract_red_channel_from_png(png_bytes: bytes) -> list[int]:
    """Extract non-transparent red channel values from a PNG without PIL.

    Handles RGBA 8-bit PNGs (the format PC returns for expression tiles).

    **Limitations** (manual PNG decoder — no Pillow dependency):
    - Only 8-bit RGB (colour type 2) and 8-bit RGBA (colour type 6) are
      supported.  Palette (type 3), greyscale (type 0/4), and 16-bit
      images will be rejected.
    - Interlaced (Adam7) PNGs are NOT handled; the decompressed scanline
      layout assumed here is non-interlaced only.
    - All five PNG filter types (None/Sub/Up/Average/Paeth) are
      implemented, but edge-cases in corrupted streams may produce
      incorrect pixel values rather than raising.
    """
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return []

    # Parse IHDR
    pos = 8
    width = height = bit_depth = color_type = 0
    raw_idat = b""

    while pos < len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        chunk_type = png_bytes[pos + 4 : pos + 8]
        chunk_data = png_bytes[pos + 8 : pos + 8 + chunk_len]

        if chunk_type == b"IHDR":
            width = struct.unpack(">I", chunk_data[0:4])[0]
            height = struct.unpack(">I", chunk_data[4:8])[0]
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
        elif chunk_type == b"IDAT":
            raw_idat += chunk_data
        elif chunk_type == b"IEND":
            break

        pos += 12 + chunk_len  # 4 len + 4 type + data + 4 crc

    if not width or not height:
        return []

    if bit_depth != 8:
        logger.warning(
            "Unsupported PNG bit depth %d (only 8-bit supported); returning empty",
            bit_depth,
        )
        return []

    # Determine bytes per pixel
    if color_type == 6:  # RGBA
        bpp = 4
    elif color_type == 2:  # RGB
        bpp = 3
    else:
        logger.warning(
            "Unsupported PNG colour type %d (only RGB=2 and RGBA=6 supported); "
            "palette, greyscale, and interlaced images are not handled",
            color_type,
        )
        return []

    try:
        decompressed: bytes = zlib.decompress(raw_idat)
    except zlib.error:
        return []

    # Undo PNG filtering (simplified — handles filter type 0 and 1)
    stride = 1 + width * bpp
    if len(decompressed) < stride * height:
        return []

    red_values: list[int] = []
    prev_row = bytearray(width * bpp)

    for row in range(height):
        row_start = row * stride
        filter_type = cast(int, decompressed[row_start])
        raw = bytearray(decompressed[row_start + 1 : row_start + stride])

        if filter_type == 1:  # Sub
            for i in range(bpp, len(raw)):
                raw[i] = (raw[i] + raw[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(len(raw)):
                raw[i] = (raw[i] + prev_row[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(len(raw)):
                left = raw[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                raw[i] = (raw[i] + (left + up) // 2) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(len(raw)):
                left = raw[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                raw[i] = (raw[i] + _paeth_predictor(left, up, up_left)) & 0xFF

        # Extract red channel for non-transparent pixels
        for px in range(width):
            offset = px * bpp
            r_val = raw[offset]
            alpha = raw[offset + 3] if bpp == 4 else 255
            if alpha > 0:
                red_values.append(r_val)

        prev_row = raw

    return red_values


def _paeth_predictor(a: int, b: int, c: int) -> int:
    """PNG Paeth predictor filter."""
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    return c
