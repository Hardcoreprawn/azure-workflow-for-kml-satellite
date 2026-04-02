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
from typing import Any, cast

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
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
    2,  # Dark area pixels
    4,  # Vegetation
    5,  # Bare soils
    6,  # Water (optional — valid surface, NDVI ≈ −0.1 to 0)
)


def compute_ndvi(
    bbox: list[float],
    date_start: str,
    date_end: str,
    max_cloud: float = 20.0,
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
        None if no scene found.
    """
    import numpy as np
    import rasterio

    log_phase("ndvi", "search_start", bbox=bbox, window=f"{date_start}/{date_end}")

    scene = _find_best_s2_scene(bbox, date_start, date_end, max_cloud)
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
        b08_data, _b08_profile = _cog_band_read(scene["B08"], bbox)

        # Ensure same shape (B04 is 10m, B08 is 10m for S2 L2A — should match)
        if b04_data.shape != b08_data.shape:
            # Resample to smaller extent
            min_h = min(b04_data.shape[0], b08_data.shape[0])
            min_w = min(b04_data.shape[1], b08_data.shape[1])
            b04_data = b04_data[:min_h, :min_w]
            b08_data = b08_data[:min_h, :min_w]

        # Read SCL band for pixel-level cloud masking (20 m → resample to 10 m)
        scl_mask = None
        scl_masked_count = 0
        if scene.get("SCL"):
            try:
                scl_data, _scl_profile = _cog_band_read(scene["SCL"], bbox)
                # Resample SCL (20m) to match B04/B08 (10m) via nearest-neighbour
                if _rs is not None:
                    scl_mask = _rs.resample_nearest(
                        scl_data.astype(np.uint8),
                        b04_data.shape[0],
                        b04_data.shape[1],
                    )
                else:
                    scl_mask = _resample_scl(scl_data, b04_data.shape)
                log_phase("ndvi", "scl_loaded", scene_id=scene["scene_id"])
            except Exception as scl_exc:
                logger.warning(
                    "SCL read failed for %s, falling back to no pixel mask: %s",
                    scene["scene_id"],
                    scl_exc,
                )

        # Convert to float for band math
        red = b04_data.astype(np.float32)
        nir = b08_data.astype(np.float32)

        if _rs is not None:
            # Rust-accelerated NDVI: parallel SIMD band math
            ndvi, valid_mask = _rs.compute_ndvi_array(red, nir)

            # Apply SCL mask via Rust (in-place)
            if scl_mask is not None:
                scl_masked_count = int(
                    _rs.apply_scl_mask(
                        valid_mask,
                        scl_mask.astype(np.uint8),
                        list(VALID_SCL_CLASSES),
                    )
                )
        else:
            # Pure-Python fallback
            denom = nir + red
            ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
            valid_mask = (b04_data > 0) & (b08_data > 0) & np.isfinite(ndvi)
            if scl_mask is not None:
                scl_valid = np.isin(scl_mask, VALID_SCL_CLASSES)
                scl_masked_count = int(np.sum(valid_mask & ~scl_valid))
                valid_mask = valid_mask & scl_valid

        valid_pixels = ndvi[valid_mask]

        if len(valid_pixels) == 0:
            log_phase("ndvi", "no_valid_pixels", scene_id=scene["scene_id"])
            return None

        stats = {
            "mean": round(float(np.mean(valid_pixels)), 4),
            "min": round(float(np.min(valid_pixels)), 4),
            "max": round(float(np.max(valid_pixels)), 4),
            "std": round(float(np.std(valid_pixels)), 4),
            "median": round(float(np.median(valid_pixels)), 4),
            "valid_pixels": len(valid_pixels),
            "total_pixels": int(ndvi.size),
            "scl_masked_pixels": scl_masked_count,
            "scl_applied": scl_mask is not None,
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
        src_bbox = _transform_bbox_4326(bbox, str(src.crs))
        window = window_from_bounds(*src_bbox, transform=src.transform)
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        data = src.read(1, window=window)
        profile = {
            "driver": "GTiff",
            "crs": src.crs,
            "transform": src.window_transform(window),
        }
    return data, profile


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


def _transform_bbox_4326(
    bbox: list[float],
    dst_crs: str,
) -> tuple[float, float, float, float]:
    """Reproject [min_lon, min_lat, max_lon, max_lat] from EPSG:4326."""
    if dst_crs in ("EPSG:4326", "epsg:4326"):
        return (bbox[0], bbox[1], bbox[2], bbox[3])

    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    x_min, y_min = transformer.transform(bbox[0], bbox[1])
    x_max, y_max = transformer.transform(bbox[2], bbox[3])
    return (
        min(x_min, x_max),
        min(y_min, y_max),
        max(x_min, x_max),
        max(y_min, y_max),
    )


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
    http = client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
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


def _extract_red_channel_from_png(png_bytes: bytes) -> list[int]:
    """Extract non-transparent red channel values from a PNG without PIL.

    Handles RGBA 8-bit PNGs (the format PC returns for expression tiles).
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

    if not width or not height or bit_depth != 8:
        return []

    # Determine bytes per pixel
    if color_type == 6:  # RGBA
        bpp = 4
    elif color_type == 2:  # RGB
        bpp = 3
    else:
        return []  # unsupported

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
