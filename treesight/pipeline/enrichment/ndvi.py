"""NDVI computation from Landsat/Sentinel COGs and PC tile sampling.

Design decision: NDVI is multi-sensor and selected per planned frame, not
Sentinel-2-only. The current frame plan uses Landsat C2 L2 for 2013-2017 and
Sentinel-2 L2A from 2018 onward. The frame's sensor is preferred, and the
runner tries the other supported multispectral COG source if that computation
returns no result. NAIP currently supplies visual context only. A future NAIP
NDVI path must verify red and NIR bands (at least four bands, RGBN) and
suitable radiometry; 3-band RGB cannot produce NDVI.

The current frame plan has no Landsat/Sentinel overlap frames: Landsat ends in
2017 and Sentinel-2 starts in 2018. Do not interpret that sensor transition as
a direct NDVI change without an overlap period or harmonized calibration. Keep
the analysis source distinct from the display source in per-frame provenance.

Three paths are available:
- ``compute_ndvi``: Sentinel-2 B04/B08 band math via rasterio.
- ``compute_landsat_ndvi``: Landsat C2 L2 red/NIR band math via rasterio.
- ``fetch_ndvi_stat``: lightweight PC tile sampling via PNG parsing for timeline overview.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import zlib
from typing import Any, cast

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from treesight.geo import transform_bbox
from treesight.log import log_phase
from treesight.models.geometry import PolygonGeometry
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
) -> dict[str, Any] | None:
    """Search STAC for the least-cloudy Sentinel-2 L2A scene in a window.

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
        max_items=1,
        sortby=[{"field": "eo:cloud_cover", "direction": "asc"}],
    )

    items = list(search.items())
    if not items:
        return None

    item = items[0]
    b04 = item.assets.get("B04")
    b08 = item.assets.get("B08")
    scl = item.assets.get("SCL")
    if not b04 or not b08:
        logger.warning("S2 item %s missing B04/B08 assets", item.id)
        return None

    result: dict[str, Any] = {
        "scene_id": item.id,
        "B04": b04.href,
        "B08": b08.href,
        "cloud_cover": item.properties.get("eo:cloud_cover", 0.0),
        "datetime": item.properties.get("datetime", ""),
        "crs": f"EPSG:{item.properties.get('proj:epsg', 32632)}",
    }
    if scl:
        result["SCL"] = scl.href
    return result


# ── COG-based NDVI computation ────────────────────────────────

# SCL (Scene Classification Layer) valid pixel classes for NDVI.
# See: https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview
VALID_SCL_CLASSES = (
    4,  # Vegetation
    5,  # Bare soils
    6,  # Water
)


def compute_ndvi(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 20.0,
    *,
    geometry: PolygonGeometry | None = None,
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
    geometry : PolygonGeometry or None
        Exact source plot geometry. Without it, plot-level statistics are
        unavailable rather than inferred from the bounding box.

    An available, readable SCL asset is required. If cloud classification
    cannot be applied, the result is explicitly unavailable.

    Returns
    -------
    dict or None
        ``{"mean", "min", "max", "std", "median", "valid_pixels",
        "total_pixels", "grid_pixels", "scene_id", "cloud_cover",
        "datetime", "scl_applied", "scl_masked_pixels", "geotiff_bytes"}``
        on success. ``total_pixels`` counts pixel centres inside the plot;
        ``grid_pixels`` counts the full raster window.
        None if no scene found.
    """
    import numpy as np
    import rasterio

    if geometry is None:
        return {"available": False, "unavailable_reason": "geometry_unavailable"}

    log_phase("ndvi", "search_start", bbox=bbox, window=f"{date_start}/{date_end}")

    scene = _find_best_s2_scene(bbox, date_start, date_end, max_cloud)
    if not scene:
        log_phase("ndvi", "no_scene_found")
        return None
    if not scene.get("SCL"):
        return {"available": False, "unavailable_reason": "cloud_mask_unavailable"}

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

        if not _same_grid(b04_data, b04_profile, b08_data, b08_profile):
            return {"available": False, "unavailable_reason": "misaligned_band_grids"}

        scl_masked_count = 0
        try:
            scl_data, scl_profile = _cog_band_read(scene["SCL"], bbox)
            scl_mask = _resample_categorical(
                scl_data,
                scl_profile,
                b04_profile,
                b04_data.shape,
                source_nodata=0,
            )
            log_phase("ndvi", "scl_loaded", scene_id=scene["scene_id"])
        except Exception as scl_exc:
            logger.warning("SCL read failed for %s: %s", scene["scene_id"], scl_exc)
            return {"available": False, "unavailable_reason": "cloud_mask_unavailable"}

        # Convert to float for band math
        red = b04_data.astype(np.float32)
        nir = b08_data.astype(np.float32)

        if _rs is not None:
            # Rust-accelerated NDVI: parallel SIMD band math
            ndvi, valid_mask = _rs.compute_ndvi_array(red, nir)
        else:
            # Pure-Python fallback
            denom = nir + red
            with np.errstate(invalid="ignore", divide="ignore"):
                ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
            valid_mask = (b04_data > 0) & (b08_data > 0) & np.isfinite(ndvi)
        geometry_mask = _geometry_mask(geometry, ndvi.shape, b04_profile)
        if geometry_mask is None:
            return {"available": False, "unavailable_reason": "plot_not_fully_covered"}
        geometry_pixels = int(np.sum(geometry_mask))
        scl_valid = np.isin(scl_mask, VALID_SCL_CLASSES)
        scl_masked_count = int(np.sum(valid_mask & ~scl_valid & geometry_mask))
        valid_mask &= scl_valid
        valid_mask &= geometry_mask
        valid_pixels = ndvi[valid_mask]

        if len(valid_pixels) == 0:
            log_phase("ndvi", "no_valid_pixels", scene_id=scene["scene_id"])
            return {
                "available": False,
                "unavailable_reason": "insufficient_in_plot_pixels",
                "valid_pixels": 0,
                "geometry_pixels": geometry_pixels,
                "total_pixels": geometry_pixels,
                "grid_pixels": int(ndvi.size),
                "geometry_masked_pixels": int(ndvi.size) - geometry_pixels,
                "geometry_mask_applied": True,
                "geometry_mask_method": "pixel_center",
            }

        stats = {
            "source": "sentinel-2-l2a",
            "available": True,
            "mean": round(float(np.mean(valid_pixels)), 4),
            "min": round(float(np.min(valid_pixels)), 4),
            "max": round(float(np.max(valid_pixels)), 4),
            "std": round(float(np.std(valid_pixels)), 4),
            "median": round(float(np.median(valid_pixels)), 4),
            "valid_pixels": len(valid_pixels),
            "total_pixels": geometry_pixels,
            "grid_pixels": int(ndvi.size),
            "scl_masked_pixels": scl_masked_count,
            "scl_applied": scl_mask is not None,
            "geometry_pixels": geometry_pixels,
            "geometry_masked_pixels": int(ndvi.size) - geometry_pixels,
            "geometry_mask_applied": True,
            "geometry_mask_method": "pixel_center",
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

# Landsat QA_PIXEL bit flags (Collection 2 Level 2).
# Bit 1 = dilated cloud, Bit 3 = cloud, Bit 4 = cloud shadow, Bit 5 = snow.
_LANDSAT_QA_CLEAR_MASK = 0b00111111  # fill, dilated cloud, cirrus, cloud, shadow, snow


def _find_best_landsat_scene(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 30.0,
) -> dict[str, Any] | None:
    """Search for the least-cloudy Landsat C2 L2 scene in a date window."""
    import planetary_computer
    from pystac_client import Client

    catalog = Client.open(STAC_API, modifier=planetary_computer.sign_inplace)
    search = catalog.search(
        collections=["landsat-c2-l2"],
        bbox=bbox,
        datetime=f"{date_start}/{date_end}",
        query={"eo:cloud_cover": {"lte": max_cloud}},
        max_items=1,
        sortby=[{"field": "eo:cloud_cover", "direction": "asc"}],
    )

    items = list(search.items())
    if not items:
        return None

    item = items[0]
    # Landsat 8/9: B4=Red, B5=NIR (OLI)
    red = item.assets.get("red")
    nir = item.assets.get("nir08")
    qa = item.assets.get("qa_pixel")
    if not red or not nir:
        logger.warning("Landsat item %s missing red/nir08 assets", item.id)
        return None

    result: dict[str, Any] = {
        "scene_id": item.id,
        "red": red.href,
        "nir": nir.href,
        "cloud_cover": item.properties.get("eo:cloud_cover", 0.0),
        "datetime": item.properties.get("datetime", ""),
        "crs": f"EPSG:{item.properties.get('proj:epsg', 32632)}",
    }
    red_calibration = _asset_reflectance_calibration(red)
    nir_calibration = _asset_reflectance_calibration(nir)
    if red_calibration is not None and nir_calibration is not None:
        result.update(
            red_scale=red_calibration[0],
            red_offset=red_calibration[1],
            nir_scale=nir_calibration[0],
            nir_offset=nir_calibration[1],
        )
    else:
        logger.warning("Landsat item %s is missing reflectance calibration metadata", item.id)
    if qa:
        result["qa_pixel"] = qa.href
    return result


def _asset_reflectance_calibration(asset: Any) -> tuple[float, float] | None:
    """Read scale and offset from one Planetary Computer raster band."""
    bands = asset.extra_fields.get("raster:bands")
    if not isinstance(bands, list) or not bands or not isinstance(bands[0], dict):
        return None

    scale = bands[0].get("scale")
    offset = bands[0].get("offset")
    if (
        not isinstance(scale, (int, float))
        or not isinstance(offset, (int, float))
        or not math.isfinite(scale)
        or not math.isfinite(offset)
    ):
        return None
    return float(scale), float(offset)


def compute_landsat_ndvi(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 30.0,
    *,
    geometry: PolygonGeometry | None = None,
) -> dict[str, Any] | None:
    """Compute NDVI from Landsat C2 L2 Red/NIR08 COGs.

    Mirrors ``compute_ndvi`` but uses Landsat band names, STAC raster-band
    scale/offset metadata, and QA_PIXEL for cloud masking instead of SCL.

    Parameters
    ----------
    bbox : list[float]
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.
    date_start, date_end : str
        ISO date strings for the search window.
    max_cloud : float
        Maximum cloud cover percentage (higher default for Landsat).
    geometry : PolygonGeometry or None
        Exact source plot geometry. Without it, plot-level statistics are
        unavailable rather than inferred from the bounding box.

    Returns
    -------
    dict or None
        Same structure as ``compute_ndvi`` on success; None if no scene.
    """
    import numpy as np
    import rasterio

    if geometry is None:
        return {"available": False, "unavailable_reason": "geometry_unavailable"}

    log_phase(
        "ndvi",
        "landsat_search_start",
        bbox=bbox,
        window=f"{date_start}/{date_end}",
    )

    scene = _find_best_landsat_scene(bbox, date_start, date_end, max_cloud)
    if not scene:
        log_phase("ndvi", "landsat_no_scene")
        return None

    log_phase(
        "ndvi",
        "landsat_reading_bands",
        scene_id=scene["scene_id"],
        cloud_cover=scene["cloud_cover"],
    )

    if not scene.get("qa_pixel"):
        return {"available": False, "unavailable_reason": "qa_mask_unavailable"}
    calibration = (
        scene.get("red_scale"),
        scene.get("red_offset"),
        scene.get("nir_scale"),
        scene.get("nir_offset"),
    )
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in calibration):
        return {
            "available": False,
            "unavailable_reason": "reflectance_calibration_unavailable",
        }

    try:
        red_data, red_profile = _cog_band_read(scene["red"], bbox)
        nir_data, nir_profile = _cog_band_read(scene["nir"], bbox)

        if not _same_grid(red_data, red_profile, nir_data, nir_profile):
            return {"available": False, "unavailable_reason": "misaligned_band_grids"}

        qa_masked_count = 0
        try:
            qa_data, qa_profile = _cog_band_read(scene["qa_pixel"], bbox)
            qa_data = _resample_categorical(qa_data, qa_profile, red_profile, red_data.shape)
        except Exception as qa_exc:
            logger.warning("Landsat QA_PIXEL read failed for %s: %s", scene["scene_id"], qa_exc)
            return {"available": False, "unavailable_reason": "qa_mask_unavailable"}

        red_scale, red_offset, nir_scale, nir_offset = calibration
        red = red_data.astype(np.float32) * red_scale + red_offset
        nir = nir_data.astype(np.float32) * nir_scale + nir_offset

        denom = nir + red
        with np.errstate(invalid="ignore", divide="ignore"):
            ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
        valid_mask = (red_data > 0) & (nir_data > 0) & (red >= 0) & (nir >= 0) & np.isfinite(ndvi)
        qa_values = qa_data.astype(np.uint16)
        cloud_confidence = (qa_values >> 8) & 0b11
        qa_mask = ((qa_values & _LANDSAT_QA_CLEAR_MASK) == 0) & (cloud_confidence < 2)
        geometry_mask = _geometry_mask(geometry, ndvi.shape, red_profile)
        if geometry_mask is None:
            return {"available": False, "unavailable_reason": "plot_not_fully_covered"}
        geometry_pixels = int(np.sum(geometry_mask))
        qa_masked_count = int(np.sum(valid_mask & ~qa_mask & geometry_mask))
        valid_mask &= qa_mask
        valid_mask &= geometry_mask
        valid_pixels = ndvi[valid_mask]
        if len(valid_pixels) == 0:
            log_phase("ndvi", "landsat_no_valid_pixels", scene_id=scene["scene_id"])
            return {
                "available": False,
                "unavailable_reason": "insufficient_in_plot_pixels",
                "valid_pixels": 0,
                "geometry_pixels": geometry_pixels,
                "total_pixels": geometry_pixels,
                "grid_pixels": int(ndvi.size),
                "geometry_mask_applied": True,
                "geometry_mask_method": "pixel_center",
            }

        ndvi_masked = np.where(valid_mask, ndvi, np.nan)
        buf = io.BytesIO()
        profile = red_profile.copy()
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
            "available": True,
            "mean": round(float(np.mean(valid_pixels)), 4),
            "min": round(float(np.min(valid_pixels)), 4),
            "max": round(float(np.max(valid_pixels)), 4),
            "std": round(float(np.std(valid_pixels)), 4),
            "median": round(float(np.median(valid_pixels)), 4),
            "valid_pixels": len(valid_pixels),
            "total_pixels": geometry_pixels,
            "grid_pixels": int(ndvi.size),
            "qa_masked_pixels": qa_masked_count,
            "qa_applied": True,
            "geometry_pixels": geometry_pixels,
            "geometry_masked_pixels": int(ndvi.size) - geometry_pixels,
            "geometry_mask_applied": True,
            "geometry_mask_method": "pixel_center",
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


def _geometry_mask(
    geometry: PolygonGeometry,
    shape: tuple[int, int],
    profile: dict[str, Any],
) -> Any | None:
    """Build an in-plot pixel mask, or return None if the window clips the plot."""
    from pyproj import Transformer
    from rasterio.features import geometry_mask
    from shapely.geometry import Polygon as ShapelyPolygon
    from shapely.geometry import mapping
    from shapely.geometry import shape as geometry_shape
    from shapely.ops import transform as transform_shape

    raster_crs = profile.get("crs")
    transform = profile.get("transform")
    if raster_crs is None or transform is None:
        raise ValueError("Raster profile must include CRS and transform for plot masking")

    project = Transformer.from_crs(geometry.crs, raster_crs, always_xy=True)
    raster_geometry_shape = transform_shape(project.transform, geometry_shape(geometry.to_geojson()))
    raster_geometry = mapping(raster_geometry_shape)
    raster_extent = ShapelyPolygon(
        [
            transform * (0, 0),
            transform * (shape[1], 0),
            transform * (shape[1], shape[0]),
            transform * (0, shape[0]),
        ]
    )
    if not raster_extent.covers(raster_geometry_shape):
        return None

    return geometry_mask(
        [raster_geometry],
        out_shape=shape,
        transform=transform,
        all_touched=False,
        invert=True,
    )


def _same_grid(
    first_data: Any,
    first_profile: dict[str, Any],
    second_data: Any,
    second_profile: dict[str, Any],
) -> bool:
    """Return whether arrays describe exactly the same raster grid."""
    return (
        first_data.shape == second_data.shape
        and first_profile.get("crs") == second_profile.get("crs")
        and first_profile.get("transform") == second_profile.get("transform")
    )


def _resample_categorical(
    data: Any,
    source_profile: dict[str, Any],
    target_profile: dict[str, Any],
    target_shape: tuple[int, int],
    *,
    source_nodata: int | None = None,
) -> Any:
    """Reproject a categorical raster to the target grid using nearest-neighbour."""
    import numpy as np
    from rasterio.warp import Resampling, reproject

    if (
        source_profile.get("crs") is None
        or source_profile.get("transform") is None
        or target_profile.get("crs") is None
        or target_profile.get("transform") is None
    ):
        raise ValueError("Raster profiles must include CRS and transform for alignment")

    if (
        data.shape == target_shape
        and source_profile["crs"] == target_profile["crs"]
        and source_profile["transform"] == target_profile["transform"]
    ):
        return data

    destination_nodata = source_nodata if source_nodata is not None else int(np.iinfo(data.dtype).max)
    destination = np.full(target_shape, destination_nodata, dtype=data.dtype)
    reproject(
        source=data,
        destination=destination,
        src_transform=source_profile["transform"],
        src_crs=source_profile["crs"],
        src_nodata=source_nodata,
        dst_transform=target_profile["transform"],
        dst_crs=target_profile["crs"],
        dst_nodata=destination_nodata,
        resampling=Resampling.nearest,
    )
    return destination


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
        window = window_from_bounds(*src_bbox, transform=src.transform)
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        data = src.read(1, window=window)
        profile = {
            "driver": "GTiff",
            "crs": src.crs,
            "transform": src.window_transform(window),
        }
    return data, profile


def fetch_ndvi_stat(
    search_id: str,
    coords: list[list[float]],
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
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
            "source": "sentinel-2-l2a",
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
