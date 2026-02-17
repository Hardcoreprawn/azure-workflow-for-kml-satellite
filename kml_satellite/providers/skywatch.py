"""SkyWatch EarthCache adapter.

Production adapter using the SkyWatch EarthCache API for aggregated
commercial satellite imagery (Maxar, Planet, Airbus) at <= 50 cm resolution.

This is a stub — the full implementation is a future milestone.

References:
    PID Section 7.6 (SkyWatch for production)
    PID FR-3.2 (implement at least two provider adapters)
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


class SkyWatchAdapter(ImageryProvider):
    """SkyWatch EarthCache adapter.

    Full implementation is a future milestone. This stub satisfies
    the ABC contract and allows the factory and type system to work.
    """

    def search(
        self,
        aoi: AOI,
        filters: ImageryFilters | None = None,
    ) -> list[SearchResult]:
        """Search SkyWatch EarthCache archive."""
        raise NotImplementedError("SkyWatchAdapter.search() — future milestone")

    def order(self, scene_id: str) -> OrderId:
        """Submit order to SkyWatch EarthCache."""
        raise NotImplementedError("SkyWatchAdapter.order() — future milestone")

    def poll(self, order_id: str) -> OrderStatus:
        """Poll order status from SkyWatch."""
        raise NotImplementedError("SkyWatchAdapter.poll() — future milestone")

    def download(self, order_id: str) -> BlobReference:
        """Download imagery from SkyWatch."""
        raise NotImplementedError("SkyWatchAdapter.download() — future milestone")
