"""Synthetic-data imagery for CANOPEX_TEST_MODE (#1215).

This lives in the production package — not ``tests/`` — for exactly one
reason: a live ``func start`` host process (used by the local/CI pipeline
e2e gate) needs to import it, and code outside ``tests/`` isn't shipped or
importable from the deployed image today. Nothing here activates on its
own: selection only ever happens behind ``treesight.config.is_test_mode_
enabled()``, which reads an operator-set environment variable, never
request/event payload data.

``tests/stub_provider.py`` re-exports these so existing pytest usage is
unaffected.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import rasterio
from rasterio.transform import from_bounds as _tfm

from treesight.config import OUTPUT_CONTAINER
from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters, SearchResult
from treesight.providers.base import BlobReference, ProviderConfig
from treesight.providers.planetary_computer import (
    COLLECTION_ASSET_KEYS,
    COLLECTION_DEFAULT_GSD,
    DEFAULT_ASSET_KEY,
    PlanetaryComputerProvider,
)

_STUB_PROFILES: dict[str, dict[str, object]] = {
    "naip": {"prefix": "naip", "cloud": 0.0, "crs": "EPSG:26911", "off_nadir": 0.0},
    "sentinel-2-l2a": {
        "prefix": "S2B_MSIL2A",
        "cloud": 8.5,
        "crs": "EPSG:32637",
        "off_nadir": 5.2,
    },
    "landsat-c2-l2": {
        "prefix": "LC09_L2SP",
        "cloud": 12.0,
        "crs": "EPSG:32614",
        "off_nadir": 0.0,
    },
}


# ---------------------------------------------------------------------------
# Stub GeoTIFF generator — used by fulfilment.py's fetch functions when
# CANOPEX_TEST_MODE is enabled, so a live host never fetches the stub
# provider's fake asset_url over the network.
# ---------------------------------------------------------------------------

_stub_geotiff_cache: bytes | None = None

# Fallback extent used when no AOI bbox is available — covers sample.kml's
# buffered_bbox [36.79, -1.32, 36.82, -1.29] with a small margin.
_FALLBACK_BBOX: list[float] = [36.78, -1.33, 36.83, -1.28]


def make_stub_geotiff(bbox: list[float] | None = None) -> bytes:
    """Generate a minimal valid GeoTIFF sized and positioned from *bbox*.

    Parameters
    ----------
    bbox:
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326 derived from
        the AOI's ``buffered_bbox``.  When ``None`` the fixed fallback extent
        that covers ``sample.kml`` is used — kept for callers that do not
        have an AOI in scope (e.g. unit tests that pre-date this fix).

    Returns
    -------
    bytes
        A 50×50 pixel, 3-band EPSG:4326 GeoTIFF whose spatial extent matches
        *bbox*.  All pixels are set to ``128`` so downstream numeric checks
        (NDVI, change detection) receive a reproducible, non-zero signal.
    """
    resolved = bbox if bbox is not None else _FALLBACK_BBOX
    min_lon, min_lat, max_lon, max_lat = resolved
    buf = io.BytesIO()
    transform = _tfm(min_lon, min_lat, max_lon, max_lat, 50, 50)
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


def get_stub_geotiff(bbox: list[float] | None = None) -> bytes:
    """Return stub GeoTIFF bytes sized and positioned from *bbox*.

    When *bbox* is ``None`` a cached fixed-extent GeoTIFF is returned for
    backward-compatibility with callers that do not have an AOI in scope.
    When *bbox* is provided a fresh GeoTIFF is generated per-call — no
    caching, because each AOI has a distinct spatial extent.
    """
    global _stub_geotiff_cache
    if bbox is None:
        if _stub_geotiff_cache is None:
            _stub_geotiff_cache = make_stub_geotiff()
        return _stub_geotiff_cache
    return make_stub_geotiff(bbox)


class StubPlanetaryComputerProvider(PlanetaryComputerProvider):
    """Drop-in replacement for ``PlanetaryComputerProvider`` that returns
    synthetic data without hitting the network.
    """

    def __init__(self, config: ProviderConfig | None = None) -> None:
        config = dict(config or {})
        config["stub_mode"] = True  # keep flag so callers can introspect
        super().__init__(config)

    # -- search ---------------------------------------------------------

    def search(self, aoi: AOI, filters: ImageryFilters) -> list[SearchResult]:
        now = datetime.now(UTC)
        collections = filters.collections or self._collections
        first = collections[0] if collections else "sentinel-2-l2a"
        return [self._stub_result_for_collection(first, aoi, now)]

    def _stub_result_for_collection(self, collection: str, aoi: AOI, now: datetime) -> SearchResult:
        gsd = COLLECTION_DEFAULT_GSD.get(collection, 10.0)
        asset_key = COLLECTION_ASSET_KEYS.get(collection, DEFAULT_ASSET_KEY)
        profile = _STUB_PROFILES.get(collection, _STUB_PROFILES["sentinel-2-l2a"])
        scene_id = f"{profile['prefix']}_{now.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"

        return SearchResult(
            scene_id=scene_id,
            provider=self.name,
            acquisition_date=now,
            cloud_cover_pct=float(profile["cloud"]),  # type: ignore[arg-type]
            spatial_resolution_m=gsd,
            off_nadir_deg=float(profile["off_nadir"]),  # type: ignore[arg-type]
            crs=str(profile["crs"]),
            bbox=aoi.buffered_bbox,
            asset_url=f"https://stub.blob.core.windows.net/imagery/{scene_id}.tif",
            extra={"collection": collection, "asset_key": asset_key, "stub": True},
        )

    # -- download ---------------------------------------------------------

    def download(self, order_id: str) -> BlobReference:
        return BlobReference(
            container=OUTPUT_CONTAINER,
            blob_path=f"imagery/raw/stub/{order_id}.tif",
            size_bytes=1024,
            content_type="image/tiff",
        )

    # -- composite_search ---------------------------------------------------

    def composite_search(
        self,
        aoi: AOI,
        filters: ImageryFilters,
        *,
        temporal_count: int = 6,
    ) -> list[SearchResult]:
        now = datetime.now(UTC)
        results: list[SearchResult] = []

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
