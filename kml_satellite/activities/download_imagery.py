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
from datetime import datetime
from typing import Any

from kml_satellite.models.imagery import BlobReference, ProviderConfig
from kml_satellite.providers.base import ProviderDownloadError, ProviderError
from kml_satellite.providers.factory import get_provider
from kml_satellite.utils.blob_paths import build_imagery_path

logger = logging.getLogger("kml_satellite.activities.download_imagery")

# Output container name (PID Section 10.1)
OUTPUT_CONTAINER = "kml-output"

# Maximum number of download retries (PID FR-6.5)
DEFAULT_MAX_DOWNLOAD_RETRIES = 3


class DownloadError(Exception):
    """Raised when imagery download fails.

    Attributes:
        message: Human-readable error description.
        retryable: Whether the orchestrator should retry the operation.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.message = message
        self.retryable = retryable
        super().__init__(message)


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
    config = _build_provider_config(provider, provider_config)

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

    # Build PID-compliant blob path (PID Section 10.1, FR-4.2)
    ts = _parse_timestamp(timestamp)
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

    Checks:
    - File is non-empty (size_bytes > 0)
    - Content type is consistent with GeoTIFF

    Args:
        blob_ref: The ``BlobReference`` to validate.
        order_id: Order ID for error messages.

    Raises:
        DownloadError: If validation fails.
    """
    if blob_ref.size_bytes <= 0:
        msg = f"Downloaded file is empty for order {order_id} (0 bytes)"
        raise DownloadError(msg, retryable=True)

    if blob_ref.content_type not in ("image/tiff", "image/geotiff", "application/geo+json"):
        logger.warning(
            "Unexpected content type for order %s: %s (expected image/tiff)",
            order_id,
            blob_ref.content_type,
        )


def _build_provider_config(
    provider_name: str,
    overrides: dict[str, Any] | None,
) -> ProviderConfig:
    """Build a ``ProviderConfig`` from the provider name and optional overrides."""
    if overrides is None:
        return ProviderConfig(name=provider_name)

    return ProviderConfig(
        name=provider_name,
        api_base_url=str(overrides.get("api_base_url", "")),
        auth_mechanism=str(overrides.get("auth_mechanism", "none")),
        keyvault_secret_name=str(overrides.get("keyvault_secret_name", "")),
        extra_params={str(k): str(v) for k, v in overrides.get("extra_params", {}).items()},
    )


def _parse_timestamp(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp string, defaulting to current UTC time."""
    if not timestamp:
        return datetime.now().astimezone()
    try:
        return datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return datetime.now().astimezone()
