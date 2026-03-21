"""NDVI sampling from Planetary Computer tiles."""

from __future__ import annotations

import logging
import math
import struct
import zlib
from typing import cast

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from treesight.pipeline.enrichment.mosaic import PC_API

logger = logging.getLogger(__name__)


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
