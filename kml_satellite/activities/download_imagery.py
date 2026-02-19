"""Download imagery activity — download GeoTIFF and store in Blob Storage.

This activity takes an imagery outcome dict (from the polling phase)
and calls the provider adapter's ``download()`` method to stream the
GeoTIFF to Azure Blob Storage.  It validates the download, retries on
transient failures, and returns a result dict with blob path and file
metadata.

The activity does **not** decide *which* orders to download — the
orchestrator fans out a ``download_imagery`` call for each order that
reached ``state == "ready"`` during the polling phase.

Engineering standards:
    PID 7.4.1  Zero-Assumption Input Handling — validate inputs.
    PID 7.4.2  Fail Loudly — ``DownloadError`` propagates for retry / dead-letter.
    PID 7.4.4  Idempotent — same order_id overwrites the same blob path.
    PID 7.4.5  Explicit — typed models, named constants, explicit units.
    PID 7.4.6  Observability — structured logging at activity boundaries.

References:
    PID FR-3.10  (download imagery upon job completion)
    PID FR-4.2   (store raw imagery under ``/imagery/raw/``)
    PID FR-4.5   (output imagery in GeoTIFF format)
    PID FR-4.6   (metadata JSON per AOI)
    PID FR-6.5   (dead-letter failed items after max retries)
    PID Section 10.1  (Container & Path Layout)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from kml_satellite.core.constants import OUTPUT_CONTAINER
from kml_satellite.providers.base import ProviderDownloadError, ProviderError
from kml_satellite.providers.factory import get_provider
from kml_satellite.utils.blob_paths import build_imagery_path
from kml_satellite.utils.helpers import build_provider_config, parse_timestamp

if TYPE_CHECKING:
    from kml_satellite.models.imagery import BlobReference

from kml_satellite.core.exceptions import PipelineError

logger = logging.getLogger("kml_satellite.activities.download_imagery")

# Maximum number of download retries (PID FR-6.5)
DEFAULT_MAX_DOWNLOAD_RETRIES = 3


class DownloadError(PipelineError):
    """Raised when imagery download fails.

    Attributes:
        message: Human-readable error description.
        retryable: Whether the orchestrator should retry the operation.
    """

    default_stage = "download_imagery"
    default_code = "DOWNLOAD_FAILED"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)


def download_imagery(
    imagery_outcome: dict[str, Any],
    *,
    provider_name: str = "planetary_computer",
    provider_config: dict[str, Any] | None = None,
    orchard_name: str = "",
    timestamp: str = "",
    max_retries: int = DEFAULT_MAX_DOWNLOAD_RETRIES,
) -> dict[str, Any]:
    """Download GeoTIFF imagery and store it in Blob Storage.

    Args:
        imagery_outcome: Dict from the polling phase containing
            ``order_id``, ``scene_id``, ``provider``, ``aoi_feature_name``.
        provider_name: Name of the imagery provider to use.
        provider_config: Optional provider configuration overrides.
        orchard_name: Orchard/project name for blob path generation.
        timestamp: Processing timestamp (ISO 8601) for blob path.
            Defaults to current UTC time.
        max_retries: Maximum download retry attempts (default 3, FR-6.5).

    Returns:
        A dict containing:
        - ``order_id``: The order that was downloaded.
        - ``scene_id``: Scene identifier.
        - ``provider``: Provider name.
        - ``aoi_feature_name``: Feature name from the AOI.
        - ``blob_path``: Path in Blob Storage where the file was stored.
        - ``container``: Blob container name.
        - ``size_bytes``: Downloaded file size in bytes.
        - ``content_type``: MIME content type.
        - ``download_duration_seconds``: Time spent downloading.
        - ``retry_count``: Number of retries needed (0 if first attempt succeeded).

    Raises:
        DownloadError: If the download fails after all retry attempts
            or the downloaded file is invalid.
    """
    # Validate input (PID 7.4.1)
    order_id = str(imagery_outcome.get("order_id", ""))
    scene_id = str(imagery_outcome.get("scene_id", ""))
    provider = str(imagery_outcome.get("provider", provider_name))
    feature_name = str(imagery_outcome.get("aoi_feature_name", ""))

    if not order_id:
        msg = "download_imagery: order_id is missing from imagery_outcome"
        raise DownloadError(msg, retryable=False)

    logger.info(
        "download_imagery started | order=%s | scene=%s | feature=%s | provider=%s",
        order_id,
        scene_id,
        feature_name,
        provider,
    )

    # Build provider config
    config = build_provider_config(provider, provider_config)

    # Get provider adapter
    try:
        adapter = get_provider(provider, config)
    except ProviderError as exc:
        msg = f"Failed to create provider {provider!r}: {exc}"
        raise DownloadError(msg, retryable=False) from exc

    # Download with retry logic (PID FR-6.5)
    blob_ref, duration, retries_used = _download_with_retry(
        adapter,
        order_id,
        max_retries=max_retries,
    )

    # Validate the download (PID 7.4.1)
    _validate_download(blob_ref, order_id)

    # Build PID-compliant blob path (PID Section 10.1, FR-4.2).
    # This is the *canonical* destination path. The provider adapter may
    # place the file at a staging path (blob_ref.blob_path); the canonical
    # path is what downstream consumers (metadata, orchestrator) use.
    ts = parse_timestamp(timestamp)
    blob_path = build_imagery_path(
        feature_name or scene_id,
        orchard_name or "unknown",
        timestamp=ts,
    )

    logger.info(
        "download_imagery completed | order=%s | scene=%s | feature=%s | "
        "blob_path=%s | size=%d bytes | duration=%.2fs | retries=%d",
        order_id,
        scene_id,
        feature_name,
        blob_path,
        blob_ref.size_bytes,
        duration,
        retries_used,
    )

    return {
        "order_id": order_id,
        "scene_id": scene_id,
        "provider": provider,
        "aoi_feature_name": feature_name,
        "blob_path": blob_path,
        "adapter_blob_path": blob_ref.blob_path,
        "container": OUTPUT_CONTAINER,
        "size_bytes": blob_ref.size_bytes,
        "content_type": blob_ref.content_type,
        "download_duration_seconds": round(duration, 3),
        "retry_count": retries_used,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _download_with_retry(
    adapter: object,
    order_id: str,
    *,
    max_retries: int = DEFAULT_MAX_DOWNLOAD_RETRIES,
) -> tuple[BlobReference, float, int]:
    """Call ``adapter.download()`` with retry logic.

    Retries on ``ProviderDownloadError`` when the error is marked
    as retryable. Non-retryable errors propagate immediately.

    Args:
        adapter: Provider adapter instance.
        order_id: The order to download.
        max_retries: Maximum retry attempts.

    Returns:
        Tuple of (BlobReference, download_duration_seconds, retries_used).

    Raises:
        DownloadError: After all retries are exhausted or on
            non-retryable errors.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            start_time = time.monotonic()
            blob_ref = adapter.download(order_id)  # type: ignore[union-attr]
            duration = time.monotonic() - start_time
            return blob_ref, duration, attempt
        except ProviderDownloadError as exc:
            last_error = exc
            if not exc.retryable:
                msg = f"Download failed (non-retryable): {exc}"
                raise DownloadError(msg, retryable=False) from exc

            if attempt < max_retries:
                logger.warning(
                    "Download attempt %d/%d failed (retryable) | order=%s | error=%s",
                    attempt + 1,
                    max_retries + 1,
                    order_id,
                    exc,
                )
            else:
                logger.error(
                    "Download retries exhausted | order=%s | attempts=%d | error=%s",
                    order_id,
                    max_retries + 1,
                    exc,
                )

    msg = f"Download failed after {max_retries + 1} attempts: {last_error}"
    raise DownloadError(msg, retryable=False) from last_error


def _validate_download(blob_ref: BlobReference, order_id: str) -> None:
    """Validate a downloaded file reference.

    Checks (in order):
    1. File is non-empty (``size_bytes > 0``).
    2. Content type is consistent with GeoTIFF.
    3. Raster content is valid (readable GeoTIFF with expected
       characteristics) via ``_validate_raster_content``.

    Args:
        blob_ref: The ``BlobReference`` to validate.
        order_id: Order ID for error messages.

    Raises:
        DownloadError: If validation fails (retryable for empty files,
            non-retryable for corrupt content).
    """
    if blob_ref.size_bytes <= 0:
        msg = f"Downloaded file is empty for order {order_id} (0 bytes)"
        raise DownloadError(msg, retryable=True)

    # Content-type sanity check — warn but don't reject.
    if blob_ref.content_type not in ("image/tiff", "image/geotiff"):
        logger.warning(
            "Unexpected content type for order %s: %s (expected image/tiff or image/geotiff)",
            order_id,
            blob_ref.content_type,
        )

    # Rasterio-based content validation (Issue #46).
    _validate_raster_content(blob_ref, order_id)


def _validate_raster_content(blob_ref: BlobReference, order_id: str) -> None:
    """Validate raster content via rasterio when the blob is accessible.

    Attempts to open the blob with rasterio (over Azure Blob Storage
    or a local path) and check:
    - The file is a readable raster (valid GeoTIFF header).
    - At least one band exists.
    - Raster dimensions are positive.

    If the blob is not accessible (e.g. adapter hasn't persisted to
    storage yet), validation is skipped with a debug log — full
    rasterio validation activates once blob persistence is wired.

    Args:
        blob_ref: The ``BlobReference`` to validate.
        order_id: Order ID for error messages.

    Raises:
        DownloadError: Non-retryable if the raster is corrupt or unreadable.
    """
    import os

    connection_string = os.environ.get("AzureWebJobsStorage", "")  # noqa: SIM112
    if not connection_string:
        logger.debug(
            "Skipping rasterio content validation (no AzureWebJobsStorage) | order=%s",
            order_id,
        )
        return

    try:
        import rasterio
        from azure.storage.blob import BlobServiceClient

        blob_service = BlobServiceClient.from_connection_string(connection_string)
        blob_client = blob_service.get_blob_client(
            container=blob_ref.container,
            blob=blob_ref.blob_path,
        )

        if not blob_client.exists():
            logger.debug(
                "Blob not yet persisted, skipping rasterio validation | "
                "container=%s | path=%s | order=%s",
                blob_ref.container,
                blob_ref.blob_path,
                order_id,
            )
            return

        # Stream minimal header bytes to a temp file for rasterio.
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            blob_data = blob_client.download_blob()
            blob_data.readinto(tmp)
            tmp_path = Path(tmp.name)

        try:
            with rasterio.open(tmp_path) as ds:
                if ds.count < 1:
                    msg = f"Downloaded raster has no bands for order {order_id} (count={ds.count})"
                    raise DownloadError(msg, retryable=False)

                if ds.width <= 0 or ds.height <= 0:
                    msg = (
                        f"Downloaded raster has invalid dimensions for order {order_id} "
                        f"(width={ds.width}, height={ds.height})"
                    )
                    raise DownloadError(msg, retryable=False)

                logger.info(
                    "Raster content validated | order=%s | bands=%d | size=%dx%d | crs=%s",
                    order_id,
                    ds.count,
                    ds.width,
                    ds.height,
                    ds.crs,
                )
        except DownloadError:
            raise
        except Exception as exc:
            msg = f"Downloaded file is not a valid GeoTIFF for order {order_id}: {exc}"
            raise DownloadError(msg, retryable=False) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    except DownloadError:
        raise
    except ImportError:
        logger.debug(
            "rasterio not available, skipping content validation | order=%s",
            order_id,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning(
            "Raster content validation skipped due to error | order=%s | error=%s",
            order_id,
            exc,
        )


# Re-export for backwards compatibility and test imports.
_build_provider_config = build_provider_config
_parse_timestamp = parse_timestamp
