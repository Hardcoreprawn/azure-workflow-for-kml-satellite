"""Phase 3 — Fulfilment logic (§3.3).

Download imagery via COG windowed reads and post-process (clip/reproject).

Cloud Optimized GeoTIFFs (COGs) on Planetary Computer support HTTP range
requests.  Instead of downloading entire ~300 MB tiles, we open the URL
with rasterio's ``/vsicurl/`` virtual filesystem, compute a pixel window
from the AOI bounding box, and read only the relevant pixels — typically
a few hundred KB to a few MB.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import from_bounds as window_from_bounds

from treesight.log import log_error, log_phase
from treesight.models.aoi import AOI
from treesight.models.outcomes import DownloadResult, PostProcessResult
from treesight.providers.base import ImageryProvider
from treesight.storage.client import BlobStorageClient

logger = logging.getLogger(__name__)


def _make_stub_geotiff() -> bytes:
    """Generate a minimal valid GeoTIFF covering the test AOI area."""
    import numpy as np

    # Use EPSG:4326 to avoid CRS transform issues in tests
    buf = io.BytesIO()
    from rasterio.transform import from_bounds as _tfm

    # Covers test AOI buffered_bbox [36.79, -1.32, 36.82, -1.29]
    transform = _tfm(36.78, -1.33, 36.83, -1.28, 50, 50)
    data = np.ones((3, 50, 50), dtype=np.uint8) * 128
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=50,
        width=50,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)
    return buf.getvalue()


_stub_geotiff_cache: bytes | None = None


def _get_stub_geotiff() -> bytes:
    global _stub_geotiff_cache
    if _stub_geotiff_cache is None:
        _stub_geotiff_cache = _make_stub_geotiff()
    return _stub_geotiff_cache


def download_imagery(
    outcome: dict[str, Any],
    provider: ImageryProvider,
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
    asset_url: str = "",
    aoi_bbox: list[float] | None = None,
    role: str = "",
    collection: str = "",
) -> dict[str, Any]:
    """Download imagery for a single AOI and upload to blob storage.

    When *asset_url* is provided and *aoi_bbox* is available, a COG windowed
    read fetches only the pixels covering the bounding box.  Falls back to
    full download when no bbox is given, and to a stub when there is no URL.

    The *role* tag (``"detail"`` or ``"temporal"``) controls the output
    sub-path: detail images (NAIP) go to ``imagery/detail/``, temporal
    images (Sentinel-2) go to ``imagery/raw/``.
    """
    start = time.monotonic()
    order_id = outcome.get("order_id", "")
    scene_id = outcome.get("scene_id", "")
    aoi_name = outcome.get("aoi_feature_name", "")

    try:
        blob_ref = provider.download(order_id)
        safe_name = aoi_name.replace(" ", "_").replace("/", "_")
        subdir = "detail" if role == "detail" else "raw"
        dest_path = f"imagery/{subdir}/{project_name}/{timestamp}/{safe_name}/{scene_id}.tif"

        if asset_url and aoi_bbox:
            image_bytes = cog_windowed_read(asset_url, aoi_bbox)
        elif asset_url:
            image_bytes = fetch_asset_bytes(asset_url)
        else:
            image_bytes = _get_stub_geotiff()

        content_type = blob_ref.content_type or "image/tiff"
        storage.upload_bytes(
            output_container,
            dest_path,
            image_bytes,
            content_type=content_type,
        )

        duration = time.monotonic() - start
        log_phase(
            "fulfilment",
            "download_complete",
            order_id=order_id,
            blob_path=dest_path,
            size_bytes=len(image_bytes),
            duration=f"{duration:.1f}s",
        )

        return DownloadResult(
            order_id=order_id,
            scene_id=scene_id,
            provider=provider.name,
            aoi_feature_name=aoi_name,
            blob_path=dest_path,
            adapter_blob_path=blob_ref.blob_path,
            container=output_container,
            size_bytes=len(image_bytes),
            content_type=content_type,
            download_duration_seconds=duration,
            retry_count=0,
        ).model_dump()

    except Exception as exc:
        duration = time.monotonic() - start
        log_error("fulfilment", "download_failed", str(exc), order_id=order_id)
        return {
            "state": "failed",
            "order_id": order_id,
            "scene_id": scene_id,
            "provider": provider.name,
            "aoi_feature_name": aoi_name,
            "blob_path": "",
            "adapter_blob_path": "",
            "container": "",
            "size_bytes": 0,
            "content_type": "",
            "download_duration_seconds": duration,
            "retry_count": 0,
            "error": str(exc),
        }


def post_process_imagery(
    download_result: dict[str, Any],
    aoi: AOI,
    project_name: str,
    timestamp: str,
    target_crs: str,
    enable_clipping: bool,
    enable_reprojection: bool,
    output_container: str,
    storage: BlobStorageClient,
    square_frame: bool = False,
    frame_padding_pct: float = 10.0,
) -> dict[str, Any]:
    """Clip to AOI geometry and/or reproject a downloaded GeoTIFF.

    When *square_frame* is True, outputs a square-framed rendering window
    that wholly contains the AOI polygon with *frame_padding_pct* % padding
    (#176).  This is purely for display — the user's irregular polygon is
    preserved in AOI metadata for all analytical operations (NDVI, change
    detection, area calculations).  The square frame gives regular tiles
    that are easy to compare side-by-side in a UI grid.
    """
    start = time.monotonic()
    order_id = download_result.get("order_id", "")
    source_path = download_result.get("blob_path", "")

    try:
        safe_name = aoi.feature_name.replace(" ", "_").replace("/", "_")
        scene_id = download_result.get("scene_id", "")

        # Output path depends on framing mode
        if square_frame:
            clipped_path = f"imagery/framed/{project_name}/{timestamp}/{safe_name}/{scene_id}.tif"
        else:
            clipped_path = f"imagery/clipped/{project_name}/{timestamp}/{safe_name}/{scene_id}.tif"

        # Fetch the raw raster bytes from storage
        raw_bytes = storage.download_bytes(
            download_result.get("container", output_container),
            source_path,
        )
        source_size = len(raw_bytes)

        clipped = False
        reprojected = False
        source_crs = ""
        output_bytes = raw_bytes

        with MemoryFile(raw_bytes) as memfile, memfile.open() as src:
            source_crs = str(src.crs) if src.crs else ""

            if square_frame and aoi.bbox:
                from treesight.geo import square_bbox

                sq_bbox = square_bbox(aoi.bbox, padding_pct=frame_padding_pct)
                output_bytes = _clip_to_bbox(src, sq_bbox)
                clipped = True
            elif enable_clipping and aoi.exterior_coords:
                output_bytes = _clip_to_bbox(src, aoi.buffered_bbox)
                clipped = True

            if enable_reprojection and source_crs and source_crs != target_crs:
                output_bytes = _reproject_bytes(output_bytes, target_crs)
                reprojected = True

        storage.upload_bytes(
            output_container,
            clipped_path,
            output_bytes,
            content_type="image/tiff",
        )

        duration = time.monotonic() - start
        log_phase(
            "fulfilment",
            "post_process_complete",
            order_id=order_id,
            clipped=clipped,
            reprojected=reprojected,
            duration=f"{duration:.1f}s",
        )

        return PostProcessResult(
            order_id=order_id,
            source_blob_path=source_path,
            clipped_blob_path=clipped_path,
            container=output_container,
            clipped=clipped,
            reprojected=reprojected,
            source_crs=source_crs,
            target_crs=target_crs,
            source_size_bytes=source_size,
            output_size_bytes=len(output_bytes),
            processing_duration_seconds=duration,
        ).model_dump()

    except Exception as exc:
        duration = time.monotonic() - start
        log_error("fulfilment", "post_process_failed", str(exc), order_id=order_id)
        return {
            "state": "failed",
            "order_id": order_id,
            "source_blob_path": source_path,
            "clipped_blob_path": "",
            "container": "",
            "clipped": False,
            "reprojected": False,
            "source_crs": "",
            "target_crs": target_crs,
            "source_size_bytes": 0,
            "output_size_bytes": 0,
            "processing_duration_seconds": duration,
            "clip_error": str(exc),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def cog_windowed_read(url: str, bbox: list[float]) -> bytes:
    """Read only the pixels covering *bbox* from a Cloud Optimized GeoTIFF.

    Uses HTTP range requests — typically fetches a few hundred KB instead of
    the full ~300 MB Sentinel-2 tile.

    Parameters
    ----------
    url:
        Signed COG URL (Planetary Computer / Azure Blob Storage).
    bbox:
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.

    Returns
    -------
    bytes
        A GeoTIFF containing only the windowed pixels.
    """
    log_phase("fulfilment", "cog_read_start", url=url[:120])

    with rasterio.open(url) as src:
        # Transform bbox from EPSG:4326 → source CRS if needed
        src_bbox = _transform_bbox(bbox, "EPSG:4326", str(src.crs))

        window = window_from_bounds(*src_bbox, transform=src.transform)
        # Clamp to dataset bounds
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

        data = src.read(window=window)
        win_transform = src.window_transform(window)

        buf = io.BytesIO()
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[1],
            width=data.shape[2],
            transform=win_transform,
            compress="deflate",
        )

        with rasterio.open(buf, "w", **profile) as dst:
            dst.write(data)

    result = buf.getvalue()
    log_phase(
        "fulfilment",
        "cog_read_complete",
        size_bytes=len(result),
        window_shape=f"{data.shape[1]}x{data.shape[2]}",
    )
    return result


def _transform_bbox(
    bbox: list[float],
    src_crs: str,
    dst_crs: str,
) -> tuple[float, float, float, float]:
    """Reproject a bounding box between CRS."""
    if src_crs == dst_crs:
        return (bbox[0], bbox[1], bbox[2], bbox[3])

    from pyproj import Transformer

    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    x_min, y_min = transformer.transform(bbox[0], bbox[1])
    x_max, y_max = transformer.transform(bbox[2], bbox[3])
    return (
        min(x_min, x_max),
        min(y_min, y_max),
        max(x_min, x_max),
        max(y_min, y_max),
    )


def _clip_to_bbox(src: rasterio.DatasetReader, bbox: list[float]) -> bytes:
    """Clip an open rasterio dataset to a bounding box, return GeoTIFF bytes."""
    src_bbox = _transform_bbox(bbox, "EPSG:4326", str(src.crs))
    window = window_from_bounds(*src_bbox, transform=src.transform)
    window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

    data = src.read(window=window)
    win_transform = src.window_transform(window)

    buf = io.BytesIO()
    profile = src.profile.copy()
    profile.update(
        driver="GTiff",
        height=data.shape[1],
        width=data.shape[2],
        transform=win_transform,
        compress="deflate",
    )
    with rasterio.open(buf, "w", **profile) as dst:
        dst.write(data)
    return buf.getvalue()


def _reproject_bytes(tiff_bytes: bytes, target_crs: str) -> bytes:
    """Reproject GeoTIFF bytes to *target_crs*, return new GeoTIFF bytes."""
    with MemoryFile(tiff_bytes) as memfile, memfile.open() as src:
        if src.crs is None:
            msg = "Source GeoTIFF has no CRS — cannot reproject"
            raise ValueError(msg)
        transform, width, height = calculate_default_transform(
            src.crs,
            target_crs,
            src.width,
            src.height,
            *src.bounds,
        )
        profile = src.profile.copy()
        profile.update(
            crs=target_crs,
            transform=transform,
            width=width,
            height=height,
        )

        buf = io.BytesIO()
        with rasterio.open(buf, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=Resampling.bilinear,
                )
    return buf.getvalue()


def fetch_asset_bytes(url: str) -> bytes:
    """Full-file download fallback for non-COG assets."""
    import httpx

    log_phase("fulfilment", "fetch_start", url=url[:120])

    with (
        httpx.Client(timeout=300.0, follow_redirects=True) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        chunks: list[bytes] = []
        for chunk in response.iter_bytes(chunk_size=1_048_576):
            chunks.append(chunk)

    data = b"".join(chunks)
    log_phase("fulfilment", "fetch_complete", size_bytes=len(data))
    return data
