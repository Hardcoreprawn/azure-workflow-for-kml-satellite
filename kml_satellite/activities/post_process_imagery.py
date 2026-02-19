"""Post-process imagery activity — clip to AOI polygon and reproject.

This activity takes a downloaded GeoTIFF reference, clips it to the
AOI polygon boundary, reprojects if needed, and returns the result
metadata.  It implements graceful degradation: if clipping fails, the
raw image is preserved and flagged in the output.

Operations (in order):
1. **Reproject** if source CRS differs from target CRS (FR-3.11)
2. **Clip** to AOI polygon boundary using ``rasterio.mask`` (FR-3.12)

Engineering standards:
    PID 7.4.1  Zero-Assumption Input Handling — validate all inputs.
    PID 7.4.2  Fail Loudly, Fail Safely — graceful degradation on clip failure.
    PID 7.4.4  Idempotent — same input produces same output path.
    PID 7.4.5  Explicit — typed models, named constants, clear units.
    PID 7.4.6  Observability — structured logging at activity boundaries.

References:
    PID FR-3.11  (reproject if CRS differs)
    PID FR-3.12  (clip to AOI polygon boundary)
    PID FR-4.3   (store clipped imagery under ``/imagery/clipped/``)
    PID FR-4.5   (output imagery in GeoTIFF format)
    PID Section 7.4.2 (Graceful degradation)
    PID Section 7.5   (Compute Model — GDAL operations within Functions limits)
    PID Section 10.1  (Container & Path Layout)
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from kml_satellite.core.constants import OUTPUT_CONTAINER
from kml_satellite.core.exceptions import PipelineError

logger = logging.getLogger("kml_satellite.activities.post_process_imagery")

# Default target CRS (EPSG:4326 = WGS 84, consistent with KML source data)
DEFAULT_TARGET_CRS = "EPSG:4326"


class PostProcessError(PipelineError):
    """Raised when post-processing fails fatally.

    Attributes:
        message: Human-readable error description.
        retryable: Whether the orchestrator should retry.
    """

    default_stage = "post_process_imagery"
    default_code = "POST_PROCESS_FAILED"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)


def post_process_imagery(
    download_result: dict[str, Any],
    aoi: dict[str, Any],
    *,
    orchard_name: str = "",
    timestamp: str = "",
    target_crs: str = DEFAULT_TARGET_CRS,
    enable_clipping: bool = True,
    enable_reprojection: bool = True,
) -> dict[str, Any]:
    """Clip and/or reproject a downloaded GeoTIFF to the AOI polygon.

    Args:
        download_result: Dict from the download_imagery activity containing
            ``order_id``, ``blob_path``, ``size_bytes``, etc.
        aoi: Serialised AOI dict with ``exterior_coords``,
            ``feature_name``, and optionally ``interior_coords``.
        orchard_name: Orchard/project name for output path generation.
        timestamp: Processing timestamp (ISO 8601). Defaults to now.
        target_crs: Target CRS for reprojection (default EPSG:4326).
        enable_clipping: Whether to clip to AOI polygon (default True).
            Can be disabled via configuration.
        enable_reprojection: Whether to reproject if CRS differs (default True).

    Returns:
        A dict containing:
        - ``order_id``: Source order ID.
        - ``source_blob_path``: Path to the raw imagery.
        - ``clipped_blob_path``: Path to the clipped output (or raw if clipping failed/disabled).
        - ``container``: Output container name.
        - ``clipped``: Whether clipping was successfully applied.
        - ``reprojected``: Whether reprojection was applied.
        - ``source_crs``: CRS of the source raster.
        - ``target_crs``: Target CRS.
        - ``source_size_bytes``: Size of the source file.
        - ``output_size_bytes``: Size of the output file.
        - ``processing_duration_seconds``: Time spent processing.
        - ``clip_error``: Error message if clipping failed (empty if OK).

    Raises:
        PostProcessError: If a fatal error prevents any useful output.
    """
    # Validate inputs (PID 7.4.1)
    order_id = str(download_result.get("order_id", ""))
    source_blob_path = str(download_result.get("blob_path", ""))
    source_size = int(download_result.get("size_bytes", 0))
    feature_name = str(aoi.get("feature_name", ""))
    scene_id = str(download_result.get("scene_id", ""))

    if not order_id:
        msg = "post_process_imagery: order_id is missing from download_result"
        raise PostProcessError(msg, retryable=False)

    if not source_blob_path:
        msg = "post_process_imagery: blob_path is missing from download_result"
        raise PostProcessError(msg, retryable=False)

    logger.info(
        "post_process_imagery started | order=%s | feature=%s | "
        "clipping=%s | reprojection=%s | target_crs=%s",
        order_id,
        feature_name,
        enable_clipping,
        enable_reprojection,
        target_crs,
    )

    start_time = time.monotonic()

    # Build AOI polygon geometry for clipping
    exterior_coords = aoi.get("exterior_coords", [])
    interior_coords = aoi.get("interior_coords", [])

    if enable_clipping and not exterior_coords:
        logger.warning(
            "No exterior_coords in AOI for order %s — clipping disabled",
            order_id,
        )
        enable_clipping = False

    # Build the clipped output path (PID FR-4.3, Section 10.1)
    from kml_satellite.utils.blob_paths import build_clipped_imagery_path
    from kml_satellite.utils.helpers import parse_timestamp

    ts = parse_timestamp(timestamp)
    name_for_path = feature_name or scene_id or "unknown"
    clipped_blob_path = build_clipped_imagery_path(
        name_for_path,
        orchard_name or "unknown",
        timestamp=ts,
    )

    # Attempt rasterio-based processing
    result = _process_raster(
        source_blob_path=source_blob_path,
        clipped_blob_path=clipped_blob_path,
        exterior_coords=exterior_coords,
        interior_coords=interior_coords,
        target_crs=target_crs,
        enable_clipping=enable_clipping,
        enable_reprojection=enable_reprojection,
        order_id=order_id,
        feature_name=feature_name,
    )

    duration = time.monotonic() - start_time

    logger.info(
        "post_process_imagery completed | order=%s | feature=%s | "
        "clipped=%s | reprojected=%s | duration=%.2fs",
        order_id,
        feature_name,
        result["clipped"],
        result["reprojected"],
        duration,
    )

    return {
        "order_id": order_id,
        "source_blob_path": source_blob_path,
        "clipped_blob_path": result["output_path"],
        "container": OUTPUT_CONTAINER,
        "clipped": result["clipped"],
        "reprojected": result["reprojected"],
        "source_crs": result["source_crs"],
        "target_crs": target_crs,
        "source_size_bytes": source_size,
        "output_size_bytes": result["output_size_bytes"],
        "processing_duration_seconds": round(duration, 3),
        "clip_error": result.get("clip_error", ""),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _process_raster(
    *,
    source_blob_path: str,
    clipped_blob_path: str,
    exterior_coords: list[list[float]],
    interior_coords: list[list[list[float]]],
    target_crs: str,
    enable_clipping: bool,
    enable_reprojection: bool,
    order_id: str,
    feature_name: str,
) -> dict[str, Any]:
    """Execute the raster processing pipeline (reproject + clip).

    This function wraps rasterio operations with graceful degradation:
    if clipping fails, the raw image metadata is returned instead.

    Returns:
        Dict with ``clipped``, ``reprojected``, ``source_crs``,
        ``output_path``, ``output_size_bytes``, and ``clip_error``.
    """
    try:
        import rasterio
    except ImportError as exc:
        logger.warning(
            "rasterio not available — skipping raster processing | order=%s | error=%s",
            order_id,
            exc,
        )
        return {
            "clipped": False,
            "reprojected": False,
            "source_crs": "",
            "output_path": source_blob_path,
            "output_size_bytes": 0,
            "clip_error": f"rasterio not available: {exc}",
        }

    # NOTE: In production, source_blob_path would reference Azure Blob Storage.
    # The actual blob download/upload is an infrastructure concern — currently
    # the provider adapter streams data but doesn't persist it (see M-2.4 notes).
    # This implementation processes local file paths for testability.
    # When blob I/O is wired, this will use rasterio's GDAL vsicurl or
    # download to a temp file first.

    source_crs = ""
    reprojected = False
    clipped = False
    clip_error = ""
    output_path = source_blob_path
    output_size_bytes = 0
    reprojected_temp_path = ""

    try:
        source_crs = _get_raster_crs(source_blob_path, rasterio)

        # Step 1: Reproject if needed (FR-3.11)
        working_path = source_blob_path
        if enable_reprojection and source_crs and source_crs != target_crs:
            working_path = _reproject_raster(
                source_blob_path,
                target_crs,
                rasterio,
                order_id=order_id,
            )
            reprojected_temp_path = working_path
            reprojected = True
            logger.info(
                "Reprojected | order=%s | %s → %s",
                order_id,
                source_crs,
                target_crs,
            )

        # Step 2: Clip to AOI polygon (FR-3.12)
        if enable_clipping:
            try:
                output_path, output_size_bytes = _clip_raster(
                    working_path,
                    clipped_blob_path,
                    exterior_coords,
                    interior_coords,
                    rasterio,
                    order_id=order_id,
                    feature_name=feature_name,
                )
                clipped = True
            except Exception as exc:
                # Graceful degradation (PID 7.4.2): clipping failed.
                # Always fall back to the original source blob path so callers
                # receive a stable, upload-safe location.
                clip_error = str(exc)
                output_path = source_blob_path
                logger.warning(
                    "Clip failed (graceful degradation) | order=%s | feature=%s "
                    "| error=%s | returned_path=%s",
                    order_id,
                    feature_name,
                    exc,
                    output_path,
                )
        else:
            output_path = working_path
            # Populate size when reprojection-only (no clipping)
            if reprojected and working_path != source_blob_path:
                with contextlib.suppress(OSError):
                    output_size_bytes = Path(working_path).stat().st_size

    except Exception as exc:
        # Fatal raster processing error — graceful degradation
        clip_error = str(exc)
        logger.warning(
            "Raster processing failed (graceful degradation) | order=%s | error=%s",
            order_id,
            exc,
        )
    finally:
        # Clean up temporary reprojected file if it's not the final output
        if reprojected_temp_path and reprojected_temp_path != output_path:
            try:
                Path(reprojected_temp_path).unlink()
                logger.debug(
                    "Removed temporary reprojected file | order=%s | path=%s",
                    order_id,
                    reprojected_temp_path,
                )
            except OSError:
                pass  # Best-effort cleanup

    return {
        "clipped": clipped,
        "reprojected": reprojected,
        "source_crs": source_crs,
        "output_path": output_path,
        "output_size_bytes": output_size_bytes,
        "clip_error": clip_error,
    }


def _get_raster_crs(path: str, rasterio: Any) -> str:
    """Read the CRS from a raster file.

    Args:
        path: Path to the raster file.
        rasterio: The rasterio module.

    Returns:
        CRS string (e.g. ``"EPSG:4326"``) or empty string if unavailable.
    """
    try:
        with rasterio.open(path) as src:
            if src.crs:
                return str(src.crs)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("Could not read CRS from %s: %s", path, exc)
    return ""


def _reproject_raster(
    source_path: str,
    target_crs: str,
    rasterio: Any,
    *,
    order_id: str = "",
) -> str:
    """Reproject a raster to the target CRS.

    Creates a reprojected copy alongside the source file.
    Uses rasterio.warp for memory-efficient reprojection.

    Args:
        source_path: Source raster file path.
        target_crs: Target CRS string (e.g. ``"EPSG:4326"``).
        rasterio: The rasterio module.
        order_id: Order ID for logging.

    Returns:
        Path to the reprojected raster.

    Raises:
        PostProcessError: If reprojection fails.
    """
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    try:
        dst_crs = CRS.from_user_input(target_crs)

        with rasterio.open(source_path) as src:
            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds
            )

            dst_profile = src.profile.copy()
            dst_profile.update(
                crs=dst_crs,
                transform=transform,
                width=width,
                height=height,
            )

            # Write reprojected output alongside source
            source = Path(source_path)
            reprojected_path = str(
                source.with_stem(source.stem + "_reprojected").with_suffix(".tif")
            )
            with rasterio.open(reprojected_path, "w", **dst_profile) as dst:
                for band_idx in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, band_idx),
                        destination=rasterio.band(dst, band_idx),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=dst_crs,
                        resampling=Resampling.bilinear,
                    )

        return reprojected_path

    except Exception as exc:
        msg = f"Reprojection failed for order {order_id}: {exc}"
        raise PostProcessError(msg, retryable=True) from exc


def _clip_raster(
    source_path: str,
    output_path: str,
    exterior_coords: list[list[float]],
    interior_coords: list[list[list[float]]],
    rasterio: Any,
    *,
    order_id: str = "",
    feature_name: str = "",
) -> tuple[str, int]:
    """Clip a raster to an AOI polygon using rasterio.mask.

    Uses memory-efficient windowed reading via ``rasterio.mask.mask()``.

    Args:
        source_path: Source raster file path.
        output_path: Desired output file path.
        exterior_coords: Exterior ring as list of ``[lon, lat]`` pairs.
        interior_coords: Interior rings (holes).
        rasterio: The rasterio module.
        order_id: Order ID for logging.
        feature_name: Feature name for logging.

    Returns:
        Tuple of (output_path, output_size_bytes).

    Raises:
        PostProcessError: If clipping fails.
    """
    from rasterio.mask import mask as rasterio_mask

    try:
        # Build GeoJSON geometry for rasterio.mask
        geometry = _build_geojson_polygon(exterior_coords, interior_coords)

        with rasterio.open(source_path) as src:
            out_image, out_transform = rasterio_mask(
                src,
                [geometry],
                crop=True,
                all_touched=True,
            )

            out_profile = src.profile.copy()
            out_profile.update(
                height=out_image.shape[1],
                width=out_image.shape[2],
                transform=out_transform,
            )

            with rasterio.open(output_path, "w", **out_profile) as dst:
                dst.write(out_image)

        # Get output file size
        from pathlib import Path

        output_size = Path(output_path).stat().st_size

        logger.info(
            "Clip completed | order=%s | feature=%s | output=%s | size=%d bytes",
            order_id,
            feature_name,
            output_path,
            output_size,
        )

        return output_path, output_size

    except PostProcessError:
        raise
    except Exception as exc:
        msg = f"Clipping failed for order {order_id}, feature {feature_name}: {exc}"
        raise PostProcessError(msg, retryable=True) from exc


def _build_geojson_polygon(
    exterior_coords: list[list[float]],
    interior_coords: list[list[list[float]]],
) -> dict[str, Any]:
    """Build a GeoJSON Polygon geometry from coordinate lists.

    Args:
        exterior_coords: Exterior ring as list of ``[lon, lat]`` pairs.
        interior_coords: Interior rings (holes) as list of list of pairs.

    Returns:
        A GeoJSON-compatible dict with ``type`` and ``coordinates``.
    """
    rings: list[list[list[float]]] = [exterior_coords]
    if interior_coords:
        rings.extend(interior_coords)
    return {
        "type": "Polygon",
        "coordinates": rings,
    }
