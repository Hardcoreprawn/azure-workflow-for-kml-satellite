"""Shared GeoTIFF builders for test_fulfilment and test_change_detection."""

from __future__ import annotations

import io

import numpy as np
import rasterio
from rasterio.transform import from_bounds


def make_geotiff_bytes(
    width: int = 16,
    height: int = 16,
    crs: str = "EPSG:32637",
    bounds: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Generate a minimal multi-band (RGB) in-memory GeoTIFF.

    Default bounds cover the test AOI (~36.8E, 1.3S) projected into UTM 37N.
    """
    if bounds is None:
        from pyproj import Transformer

        t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x_min, y_min = t.transform(36.79, -1.32)
        x_max, y_max = t.transform(36.82, -1.29)
        bounds = (x_min, y_min, x_max, y_max)

    transform = from_bounds(*bounds, width, height)
    data = np.ones((3, height, width), dtype=np.uint8) * 128
    buf = io.BytesIO()
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="uint8",
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data)
    return buf.getvalue()


def make_ndvi_tiff(
    data: np.ndarray,
    bounds: tuple[float, float, float, float] = (0, 0, 100, 100),
) -> bytes:
    """Create a single-band float32 GeoTIFF from an NDVI array."""
    h, w = data.shape
    buf = io.BytesIO()
    transform = from_bounds(*bounds, w, h)
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(data.astype(np.float32)[np.newaxis, :, :])
    return buf.getvalue()
