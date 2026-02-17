"""Microsoft Planetary Computer adapter (STAC API).

Development/testing adapter using the free Microsoft Planetary Computer
STAC API. Provides access to Sentinel-2 L2A (10 m global) and NAIP
(~60 cm, US-only) collections.

This is a stub — the full implementation is in Issue #9 (M-2.2).

References:
    PID Section 7.6 (Planetary Computer for dev/test)
    PID FR-3.2 (implement at least two provider adapters)
    Planetary Computer STAC API: https://planetarycomputer.microsoft.com/docs/reference/stac/
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kml_satellite.providers.base import ImageryProvider

if TYPE_CHECKING:
    from kml_satellite.models.aoi import AOI
    from kml_satellite.models.imagery import (
        BlobReference,
        ImageryFilters,
        OrderId,
        OrderStatus,
        SearchResult,
    )


class PlanetaryComputerAdapter(ImageryProvider):
    """Planetary Computer STAC adapter.

    Full implementation in M-2.2 (Issue #9). This stub satisfies
    the ABC contract and allows the factory and type system to work.
    """

    def search(
        self,
        aoi: AOI,
        filters: ImageryFilters | None = None,
    ) -> list[SearchResult]:
        """Search Planetary Computer STAC catalogue."""
        raise NotImplementedError("PlanetaryComputerAdapter.search() — see Issue #9")

    def order(self, scene_id: str) -> OrderId:
        """Submit order (STAC: effectively a no-op, returns asset URL)."""
        raise NotImplementedError("PlanetaryComputerAdapter.order() — see Issue #9")

    def poll(self, order_id: str) -> OrderStatus:
        """Poll order status (STAC: always immediately ready)."""
        raise NotImplementedError("PlanetaryComputerAdapter.poll() — see Issue #9")

    def download(self, order_id: str) -> BlobReference:
        """Download GeoTIFF asset from STAC item."""
        raise NotImplementedError("PlanetaryComputerAdapter.download() — see Issue #9")
