"""Planetary Computer provider (§5.4).

Queries the Microsoft Planetary Computer STAC API for Sentinel-2 L2A
and NAIP imagery using ``pystac-client`` with
``planetary_computer.sign_inplace`` for automatic SAS token injection.

Collection priority: NAIP (~0.6 m, US-only) is tried first.  When it
returns no results the search falls back to Sentinel-2 L2A (10 m,
global).  Callers can override the list via ``imagery_filters.collections``
or the provider ``collections`` config key.

When ``stub_mode=True`` (used in unit tests), synthetic search results
and downloads are returned without any network calls.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from treesight.log import log_phase
from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters, SearchResult
from treesight.providers.base import BlobReference, ImageryProvider, OrderStatus, ProviderConfig

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Preferred search order: NAIP first (higher res), Sentinel-2 fallback.
DEFAULT_COLLECTIONS: list[str] = ["naip", "sentinel-2-l2a"]

# Each collection uses a different asset key for its main raster.
COLLECTION_ASSET_KEYS: dict[str, str] = {
    "naip": "image",
    "sentinel-2-l2a": "visual",
}
DEFAULT_ASSET_KEY = "visual"  # fallback for unknown collections

# Default spatial resolution (GSD) when the STAC item omits `gsd`.
COLLECTION_DEFAULT_GSD: dict[str, float] = {
    "naip": 0.6,
    "sentinel-2-l2a": 10.0,
}

DEFAULT_MAX_ITEMS = 5


class PlanetaryComputerProvider(ImageryProvider):
    def __init__(self, config: ProviderConfig | None = None) -> None:
        config = config or {}
        self.api_url = str(config.get("api_url", DEFAULT_API_URL))
        self._stub_mode = bool(config.get("stub_mode", False))
        self._asset_key = str(config.get("asset_key", DEFAULT_ASSET_KEY))
        self._collections = list(config.get("collections", DEFAULT_COLLECTIONS))
        self._max_items = int(config.get("max_items", DEFAULT_MAX_ITEMS))
        self._fallback = bool(config.get("fallback", True))

    @property
    def name(self) -> str:
        return "planetary_computer"

    def search(self, aoi: AOI, filters: ImageryFilters) -> list[SearchResult]:
        """Search Planetary Computer STAC for imagery covering the AOI.

        Collections are tried **in priority order**.  If ``fallback`` is
        enabled (the default), the search moves to the next collection when
        the current one yields no results.  With fallback disabled all
        collections are queried in a single STAC request.
        """
        log_phase("acquisition", "search", aoi_name=aoi.feature_name, provider=self.name)

        if self._stub_mode:
            return self._stub_search(aoi, filters)

        import planetary_computer
        from pystac_client import Client

        catalog = Client.open(self.api_url, modifier=planetary_computer.sign_inplace)

        collections = filters.collections or self._collections
        datetime_range = self._build_datetime_range(filters)

        if self._fallback:
            # Try each collection individually in priority order.
            for collection in collections:
                results = self._search_collection(
                    catalog,
                    [collection],
                    aoi,
                    filters,
                    datetime_range,
                )
                if results:
                    log_phase(
                        "acquisition",
                        "search_complete",
                        aoi_name=aoi.feature_name,
                        collection=collection,
                        results_count=len(results),
                    )
                    return results
                logger.info(
                    "No results from %s for %s, trying next collection",
                    collection,
                    aoi.feature_name,
                )
            # All collections exhausted
            log_phase(
                "acquisition",
                "search_complete",
                aoi_name=aoi.feature_name,
                results_count=0,
            )
            return []

        # Fallback disabled — single combined search across all collections.
        results = self._search_collection(
            catalog,
            collections,
            aoi,
            filters,
            datetime_range,
        )
        log_phase(
            "acquisition",
            "search_complete",
            aoi_name=aoi.feature_name,
            results_count=len(results),
        )
        return results

    def _search_collection(
        self,
        catalog: Any,
        collections: list[str],
        aoi: AOI,
        filters: ImageryFilters,
        datetime_range: str | None,
    ) -> list[SearchResult]:
        """Run a single STAC search for the given *collections*."""
        query = self._build_query(filters, collections)

        stac_search = catalog.search(
            collections=collections,
            bbox=aoi.buffered_bbox,
            datetime=datetime_range,
            query=query,
            max_items=self._max_items,
        )

        results: list[SearchResult] = []
        for item in stac_search.items():
            coll_id = item.collection_id or ""
            asset_key = COLLECTION_ASSET_KEYS.get(coll_id, self._asset_key)
            asset = item.assets.get(asset_key)
            if not asset:
                logger.debug("Item %s missing asset '%s', skipping", item.id, asset_key)
                continue

            props = item.properties
            acq_date = self._parse_datetime(props.get("datetime"))
            crs_code = self._extract_crs(props)
            default_gsd = COLLECTION_DEFAULT_GSD.get(coll_id, 10.0)

            results.append(
                SearchResult(
                    scene_id=item.id,
                    provider=self.name,
                    acquisition_date=acq_date,
                    cloud_cover_pct=float(props.get("eo:cloud_cover", 0.0)),
                    spatial_resolution_m=float(props.get("gsd", default_gsd)),
                    off_nadir_deg=float(props.get("view:off_nadir", 0.0)),
                    crs=crs_code,
                    bbox=list(item.bbox) if item.bbox else aoi.buffered_bbox,
                    asset_url=asset.href,
                    extra={
                        "collection": coll_id,
                        "asset_key": asset_key,
                        "platform": props.get("platform", ""),
                        "media_type": asset.media_type or "",
                    },
                )
            )

        # Sort by cloud cover ascending (least cloudy first)
        results.sort(key=lambda r: r.cloud_cover_pct)
        return results

    def order(self, scene_id: str) -> str:
        """Place an order. PC assets are immediately available — returns a synthetic ID."""
        log_phase("acquisition", "order", scene_id=scene_id, provider=self.name)
        return f"pc-order-{scene_id}-{uuid.uuid4().hex[:8]}"

    def poll(self, order_id: str) -> OrderStatus:
        """Poll order status. PC is synchronous — always ready."""
        return OrderStatus(
            state="ready",
            message="Assets available",
            progress_pct=100.0,
            is_terminal=True,
        )

    def download(self, order_id: str) -> BlobReference:
        """Return metadata for a download. Real bytes are fetched by fulfilment."""
        log_phase("fulfilment", "download", order_id=order_id, provider=self.name)

        if self._stub_mode:
            return self._stub_download(order_id)

        return BlobReference(
            container="kml-output",
            blob_path=f"imagery/raw/{order_id}.tif",
            size_bytes=0,
            content_type="image/tiff",
        )

    def sign_asset_url(self, url: str) -> str:
        """Re-sign an asset URL to refresh an expired SAS token."""
        import planetary_computer

        return planetary_computer.sign_url(url)

    def composite_search(
        self,
        aoi: AOI,
        filters: ImageryFilters,
        *,
        temporal_count: int = 6,
    ) -> list[SearchResult]:
        """Search NAIP for a high-res baseline *and* Sentinel-2 for temporal fill.

        Returns up to ``1 + temporal_count`` results:

        * 1 NAIP result tagged ``extra["role"] = "detail"`` (if available)
        * Up to *temporal_count* Sentinel-2 results tagged ``extra["role"]
          = "temporal"``

        If NAIP has no coverage for the AOI the Sentinel-2 results are still
        returned (the detail layer is simply absent).
        """
        log_phase(
            "acquisition",
            "composite_search",
            aoi_name=aoi.feature_name,
            provider=self.name,
        )

        if self._stub_mode:
            return self._stub_composite_search(aoi, filters, temporal_count)

        import planetary_computer
        from pystac_client import Client

        catalog = Client.open(self.api_url, modifier=planetary_computer.sign_inplace)

        results: list[SearchResult] = []

        # --- NAIP detail layer (best single image) ---
        naip_results = self._search_collection(
            catalog,
            ["naip"],
            aoi,
            filters,
            datetime_range=self._build_datetime_range(filters),
        )
        if naip_results:
            best_naip = naip_results[0]
            best_naip.extra["role"] = "detail"
            results.append(best_naip)
            logger.info(
                "NAIP detail found for %s: %s (%.1fm)",
                aoi.feature_name,
                best_naip.scene_id,
                best_naip.spatial_resolution_m,
            )
        else:
            logger.info(
                "No NAIP coverage for %s, Sentinel-2 only",
                aoi.feature_name,
            )

        # --- Sentinel-2 temporal series ---
        s2_filters = filters.model_copy()
        s2_results = self._search_collection(
            catalog,
            ["sentinel-2-l2a"],
            aoi,
            s2_filters,
            datetime_range=self._build_datetime_range(s2_filters),
        )
        for r in s2_results[:temporal_count]:
            r.extra["role"] = "temporal"
            results.append(r)

        log_phase(
            "acquisition",
            "composite_search_complete",
            aoi_name=aoi.feature_name,
            naip=1 if naip_results else 0,
            s2=min(len(s2_results), temporal_count),
            total=len(results),
        )
        return results

    # --- Internal helpers ---

    @staticmethod
    def _build_datetime_range(filters: ImageryFilters) -> str | None:
        """Build a STAC datetime range string from filter dates."""
        if filters.date_start and filters.date_end:
            return f"{filters.date_start.isoformat()}/{filters.date_end.isoformat()}"
        if filters.date_start:
            return f"{filters.date_start.isoformat()}/.."
        if filters.date_end:
            return f"../{filters.date_end.isoformat()}"
        return None

    @staticmethod
    def _build_query(
        filters: ImageryFilters,
        collections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a STAC query dict from imagery filters.

        NAIP items have no ``eo:cloud_cover`` property (clear-sky aerial
        photography), so the cloud filter is omitted when searching only
        NAIP.
        """
        naip_only = collections is not None and collections == ["naip"]
        if naip_only:
            return {}
        return {"eo:cloud_cover": {"lt": filters.max_cloud_cover_pct}}

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        """Parse an ISO datetime string, falling back to now(UTC)."""
        if not value:
            return datetime.now(UTC)
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return datetime.now(UTC)

    @staticmethod
    def _extract_crs(props: dict[str, Any]) -> str:
        """Extract CRS from STAC item properties."""
        epsg = props.get("proj:epsg")
        if epsg:
            return f"EPSG:{epsg}"
        return "EPSG:4326"

    # --- Stub helpers (unit tests only) ---

    def _stub_search(self, aoi: AOI, filters: ImageryFilters) -> list[SearchResult]:
        """Return a realistic-looking synthetic search result.

        When the default collection order is used the stub pretends NAIP
        returned a result (higher res).  If the caller explicitly requests
        only ``sentinel-2-l2a`` the stub returns an S2 result instead.
        """
        now = datetime.now(UTC)
        collections = filters.collections or self._collections
        use_naip = "naip" in collections

        if use_naip:
            scene_id = f"naip_{now.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
            return [
                SearchResult(
                    scene_id=scene_id,
                    provider=self.name,
                    acquisition_date=now,
                    cloud_cover_pct=0.0,
                    spatial_resolution_m=0.6,
                    off_nadir_deg=0.0,
                    crs="EPSG:26911",
                    bbox=aoi.buffered_bbox,
                    asset_url=f"https://stub.blob.core.windows.net/imagery/{scene_id}.tif",
                    extra={"collection": "naip", "asset_key": "image", "stub": True},
                )
            ]

        scene_id = f"S2B_MSIL2A_{now.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        return [
            SearchResult(
                scene_id=scene_id,
                provider=self.name,
                acquisition_date=now,
                cloud_cover_pct=8.5,
                spatial_resolution_m=10.0,
                off_nadir_deg=5.2,
                crs="EPSG:32637",
                bbox=aoi.buffered_bbox,
                asset_url=f"https://stub.blob.core.windows.net/imagery/{scene_id}.tif",
                extra={"collection": "sentinel-2-l2a", "asset_key": "visual", "stub": True},
            )
        ]

    def _stub_download(self, order_id: str) -> BlobReference:
        """Return a synthetic blob reference."""
        return BlobReference(
            container="kml-output",
            blob_path=f"imagery/raw/stub/{order_id}.tif",
            size_bytes=1024,
            content_type="image/tiff",
        )

    def _stub_composite_search(
        self,
        aoi: AOI,
        filters: ImageryFilters,
        temporal_count: int,
    ) -> list[SearchResult]:
        """Synthetic composite results for unit tests."""
        from datetime import timedelta

        now = datetime.now(UTC)
        results: list[SearchResult] = []

        # NAIP detail
        naip_id = f"naip_{now.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        results.append(
            SearchResult(
                scene_id=naip_id,
                provider=self.name,
                acquisition_date=now,
                cloud_cover_pct=0.0,
                spatial_resolution_m=0.6,
                off_nadir_deg=0.0,
                crs="EPSG:26911",
                bbox=aoi.buffered_bbox,
                asset_url=f"https://stub.blob.core.windows.net/imagery/{naip_id}.tif",
                extra={"collection": "naip", "asset_key": "image", "role": "detail", "stub": True},
            )
        )

        # S2 temporal series
        for i in range(temporal_count):
            dt = now - timedelta(days=60 * (i + 1))
            s2_id = f"S2B_MSIL2A_{dt.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
            results.append(
                SearchResult(
                    scene_id=s2_id,
                    provider=self.name,
                    acquisition_date=dt,
                    cloud_cover_pct=5.0 + i * 2,
                    spatial_resolution_m=10.0,
                    off_nadir_deg=3.0,
                    crs="EPSG:32611",
                    bbox=aoi.buffered_bbox,
                    asset_url=f"https://stub.blob.core.windows.net/imagery/{s2_id}.tif",
                    extra={
                        "collection": "sentinel-2-l2a",
                        "asset_key": "visual",
                        "role": "temporal",
                        "stub": True,
                    },
                )
            )

        return results
