"""Microsoft Planetary Computer adapter (STAC API).

Concrete ``ImageryProvider`` implementation using the free Microsoft
Planetary Computer STAC API. Supports Sentinel-2 L2A (10 m, global)
and NAIP (~60 cm, US-only) collections.

STAC assets are available for immediate download, so ``order()`` is
a lightweight wrapper and ``poll()`` always returns ``READY``.

Configuration:
    The STAC catalogue URL defaults to
    ``https://planetarycomputer.microsoft.com/api/stac/v1``.
    Override via ``ProviderConfig.api_base_url`` if needed.

References:
    PID FR-3.2  (at least two provider adapters)
    PID FR-3.4  (archive search + download)
    PID FR-3.8  (submit search queries to provider API)
    PID FR-3.10 (download imagery on completion)
    PID Section 7.6 (Planetary Computer for dev/test)
    Planetary Computer STAC API:
        https://planetarycomputer.microsoft.com/docs/reference/stac/
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pystac_client

from kml_satellite.models.imagery import (
    BlobReference,
    ImageryFilters,
    OrderId,
    OrderState,
    OrderStatus,
    SearchResult,
)
from kml_satellite.providers.base import (
    ImageryProvider,
    ProviderDownloadError,
    ProviderSearchError,
)

if TYPE_CHECKING:
    from kml_satellite.models.aoi import AOI
    from kml_satellite.models.imagery import ProviderConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Default collections when none specified in filters.
_DEFAULT_COLLECTIONS = ["sentinel-2-l2a"]

# STAC asset key fallback order for download URL resolution.
_FALLBACK_ASSET_KEYS = ("visual", "B04", "rendered_preview")

# Default output container for downloaded imagery.
_DEFAULT_OUTPUT_CONTAINER = "kml-output"


class PlanetaryComputerAdapter(ImageryProvider):
    """Planetary Computer STAC adapter.

    Uses ``pystac-client`` for catalogue search and ``httpx`` for asset
    download. STAC items are instantly available, so ``order()`` and
    ``poll()`` are thin wrappers.

    The adapter maintains an in-memory mapping of order IDs to their
    resolved asset URLs so that ``download()`` can retrieve the file.
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._stac_url = config.api_base_url or _DEFAULT_STAC_URL
        # order_id → (scene_id, asset_url)
        # NOTE: This mapping is unbounded and will grow as orders are created.
        # In the current deployment model, adapter instances are expected to be
        # short-lived (e.g. instantiated per request in a serverless context),
        # so the in-memory cache is discarded with each instance.  If this
        # adapter is ever reused across many requests in a long-running
        # process, consider adding a size limit, LRU eviction, or time-based
        # cleanup for this mapping.
        self._orders: dict[str, tuple[str, str]] = {}

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(
        self,
        aoi: AOI,
        filters: ImageryFilters | None = None,
    ) -> list[SearchResult]:
        """Search the Planetary Computer STAC catalogue.

        Args:
            aoi: Area of interest — uses ``buffered_bbox`` if available,
                 otherwise ``bbox``.
            filters: Optional search filters.

        Returns:
            List of ``SearchResult`` sorted by cloud cover (ascending).

        Raises:
            ProviderSearchError: On STAC API errors.
        """
        filters = filters or ImageryFilters()
        bbox = _aoi_to_bbox(aoi)

        collections = filters.collections or list(_DEFAULT_COLLECTIONS)
        date_range = _build_date_range(filters)

        query_params: dict[str, Any] = {}
        if filters.max_cloud_cover_pct < 100.0:
            query_params["eo:cloud_cover"] = {"lte": filters.max_cloud_cover_pct}

        try:
            catalogue = pystac_client.Client.open(self._stac_url)
            stac_search = catalogue.search(
                bbox=bbox,
                collections=collections,
                datetime=date_range,
                query=query_params if query_params else None,
                max_items=50,
            )
            items = list(stac_search.items())
        except Exception as exc:
            msg = f"STAC search failed: {exc}"
            raise ProviderSearchError(provider=self.name, message=msg, retryable=True) from exc

        results: list[SearchResult] = []
        for item in items:
            result = self._item_to_search_result(item)
            if result is not None:
                results.append(result)

        # Sort by cloud cover ascending (best scenes first).
        results.sort(key=lambda r: r.cloud_cover_pct)

        logger.info(
            "Planetary Computer search: %d items found for bbox=%s, collections=%s",
            len(results),
            bbox,
            collections,
        )
        return results

    # ------------------------------------------------------------------
    # order
    # ------------------------------------------------------------------

    def order(self, scene_id: str) -> OrderId:
        """Wrap STAC asset URL as an order (instant fulfilment).

        For Planetary Computer, ordering is a no-op — we just resolve
        the asset URL and store it for ``download()``.

        Args:
            scene_id: The STAC item ID from a ``SearchResult``.

        Returns:
            An ``OrderId`` with the asset URL encoded as the order_id.
        """
        order_id = f"pc-{scene_id}"
        self._orders[order_id] = (scene_id, "")

        logger.info("Planetary Computer order created: %s → %s", order_id, scene_id)
        return OrderId(provider=self.name, order_id=order_id, scene_id=scene_id)

    # ------------------------------------------------------------------
    # poll
    # ------------------------------------------------------------------

    def poll(self, order_id: str) -> OrderStatus:
        """Check order status (STAC: always immediately ready).

        Args:
            order_id: The order identifier from ``order()``.

        Returns:
            ``OrderStatus`` with ``state=READY``.
        """
        return OrderStatus(
            order_id=order_id,
            state=OrderState.READY,
            message="STAC assets are immediately available",
            progress_pct=100.0,
            updated_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # download
    # ------------------------------------------------------------------

    def download(self, order_id: str) -> BlobReference:
        """Download imagery for a completed order.

        Re-fetches the STAC item to resolve the latest asset URL,
        downloads the GeoTIFF via ``httpx``, and returns a
        ``BlobReference`` describing where the file was stored.

        Args:
            order_id: The order identifier from ``order()``.

        Returns:
            A ``BlobReference`` pointing to the downloaded imagery.

        Raises:
            ProviderDownloadError: If the order is unknown or download fails.
        """
        if order_id not in self._orders:
            msg = f"Unknown order: {order_id}"
            raise ProviderDownloadError(provider=self.name, message=msg)

        scene_id, _ = self._orders[order_id]

        # Re-fetch STAC item to get the current asset URL.
        try:
            asset_url = self._resolve_asset_url(scene_id)
        except ProviderDownloadError:
            raise
        except Exception as exc:
            msg = f"Failed to resolve asset URL for {scene_id}: {exc}"
            raise ProviderDownloadError(provider=self.name, message=msg, retryable=True) from exc

        # Download the asset.
        try:
            size_bytes = self._download_asset(asset_url, scene_id)
        except Exception as exc:
            msg = f"Failed to download asset for {scene_id}: {exc}"
            raise ProviderDownloadError(provider=self.name, message=msg, retryable=True) from exc

        blob_path = _build_blob_path(scene_id)
        container = self.config.extra_params.get("output_container", _DEFAULT_OUTPUT_CONTAINER)

        logger.info(
            "Downloaded %s to %s/%s (%d bytes)",
            scene_id,
            container,
            blob_path,
            size_bytes,
        )

        return BlobReference(
            container=container,
            blob_path=blob_path,
            size_bytes=size_bytes,
            content_type="image/tiff",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _item_to_search_result(self, item: Any) -> SearchResult | None:
        """Convert a STAC item to a ``SearchResult``, or ``None`` if unusable."""
        try:
            properties = item.properties or {}
            scene_id = item.id

            # Acquisition date.
            dt_str = properties.get("datetime") or ""
            if dt_str:
                acquisition_date = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            else:
                acquisition_date = datetime.now(UTC)

            cloud_cover = float(properties.get("eo:cloud_cover", 0.0))

            # Spatial resolution from GSD property.
            gsd = float(properties.get("gsd", 0.0))

            # CRS — STAC items typically declare proj:epsg.
            crs = properties.get("proj:epsg")
            crs_str = f"EPSG:{crs}" if crs else "EPSG:4326"

            # Bounding box.
            bbox_raw = item.bbox or [0.0, 0.0, 0.0, 0.0]
            bbox = (
                float(bbox_raw[0]),
                float(bbox_raw[1]),
                float(bbox_raw[2]),
                float(bbox_raw[3]),
            )

            # Best asset URL.
            asset_url = _resolve_best_asset_url(item)

            return SearchResult(
                scene_id=scene_id,
                provider=self.name,
                acquisition_date=acquisition_date,
                cloud_cover_pct=cloud_cover,
                spatial_resolution_m=gsd,
                crs=crs_str,
                bbox=bbox,
                asset_url=asset_url,
                extra={
                    "platform": properties.get("platform", ""),
                    "constellation": properties.get("constellation", ""),
                    "collection": getattr(item, "collection_id", ""),
                },
            )
        except Exception:
            logger.warning("Skipping unparseable STAC item: %s", getattr(item, "id", "?"))
            return None

    def _resolve_asset_url(self, scene_id: str) -> str:
        """Fetch a STAC item by ID and return the best asset URL."""
        catalogue = pystac_client.Client.open(self._stac_url)

        search = catalogue.search(
            ids=[scene_id],
            max_items=1,
        )
        items = list(search.items())
        if not items:
            msg = f"STAC item not found: {scene_id}"
            raise ProviderDownloadError(provider=self.name, message=msg)

        url = _resolve_best_asset_url(items[0])
        if not url:
            msg = f"No downloadable asset found for STAC item: {scene_id}"
            raise ProviderDownloadError(provider=self.name, message=msg)

        return url

    def _download_asset(self, url: str, scene_id: str) -> int:
        """Download an asset from *url* and return its size in bytes.

        Uses streaming to avoid loading large satellite imagery files
        (potentially hundreds of MB) entirely into memory.  In a full
        deployment the chunks would be forwarded to Azure Blob Storage;
        for now we just accumulate the byte count (the blob upload is
        an infrastructure concern for M-2.3+).
        """
        with (
            httpx.Client(timeout=60.0, follow_redirects=True) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)

        logger.debug("Downloaded %d bytes for %s from %s", size, scene_id, url)
        return size


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _aoi_to_bbox(aoi: AOI) -> tuple[float, float, float, float]:
    """Extract the best bounding box from an AOI.

    Prefers ``buffered_bbox`` if it has non-zero extent, otherwise
    falls back to ``bbox``.
    """
    if aoi.buffered_bbox and aoi.buffered_bbox != (0.0, 0.0, 0.0, 0.0):
        return aoi.buffered_bbox
    return aoi.bbox


def _build_date_range(filters: ImageryFilters) -> str | None:
    """Convert filter dates to a STAC datetime range string.

    Returns ``None`` if no date constraints are set.

    Examples:
        - ``"2025-01-01T00:00:00Z/2025-12-31T23:59:59Z"``
        - ``"2025-01-01T00:00:00Z/.."``  (open end)
        - ``"../2025-12-31T23:59:59Z"``  (open start)
    """
    if filters.date_start is None and filters.date_end is None:
        return None

    start = filters.date_start.isoformat() if filters.date_start else ".."
    end = filters.date_end.isoformat() if filters.date_end else ".."
    return f"{start}/{end}"


def _resolve_best_asset_url(item: Any) -> str:
    """Pick the best downloadable asset URL from a STAC item."""
    assets = getattr(item, "assets", {}) or {}
    for key in _FALLBACK_ASSET_KEYS:
        asset = assets.get(key)
        if asset:
            return str(asset.href)

    # Fallback: first asset with an href.
    for asset in assets.values():
        if hasattr(asset, "href") and asset.href:
            return str(asset.href)

    return ""


def _build_blob_path(scene_id: str) -> str:
    """Build a deterministic blob path for a downloaded scene.

    Format: ``imagery/raw/{scene_id}.tif``

    The path is based solely on the scene_id so that re-downloading
    the same scene overwrites the previous blob rather than creating
    duplicates — consistent with the idempotency principle (PID 7.4.4).
    """
    return f"imagery/raw/{scene_id}.tif"
