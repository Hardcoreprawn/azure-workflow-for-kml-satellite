"""SkyWatch EarthCache adapter.

Production adapter using the SkyWatch EarthCache API for aggregated
commercial satellite imagery (Maxar, Planet, Airbus) at <= 50 cm resolution.

**Status: NOT YET IMPLEMENTED.**

The adapter class exists to satisfy the ABC contract and type system,
but runtime instantiation is blocked by ``SkyWatchNotImplementedError``
raised in ``__init__``.  The provider factory explicitly prevents
selection of ``skywatch`` until this module is fully implemented.

References:
    PID Section 7.6 (SkyWatch for production)
    PID FR-3.2 (implement at least two provider adapters)
    Issue #44 — explicit guard until implemented
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kml_satellite.providers.base import ImageryProvider, ProviderError

if TYPE_CHECKING:
    from kml_satellite.models.aoi import AOI
    from kml_satellite.models.imagery import (
        BlobReference,
        ImageryFilters,
        OrderId,
        OrderStatus,
        ProviderConfig,
        SearchResult,
    )


class SkyWatchNotImplementedError(ProviderError):
    """Raised when the SkyWatch adapter is selected but not yet implemented.

    This is a deliberate guard — not a generic ``NotImplementedError`` —
    so callers receive an actionable, provider-typed error that is
    explicitly non-retryable.
    """

    def __init__(self) -> None:
        super().__init__(
            provider="skywatch",
            message=(
                "SkyWatch EarthCache adapter is not yet implemented. "
                "Set IMAGERY_PROVIDER to 'planetary_computer' or wait for "
                "the SkyWatch milestone. See Issue #44."
            ),
            retryable=False,
        )


class SkyWatchAdapter(ImageryProvider):
    """SkyWatch EarthCache adapter.

    **Not yet implemented.** Instantiation raises
    ``SkyWatchNotImplementedError`` to prevent silent placeholder
    failures at runtime (PID 7.4.2 — fail loudly, fail safely).
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        raise SkyWatchNotImplementedError

    def search(
        self,
        aoi: AOI,  # noqa: ARG002
        filters: ImageryFilters | None = None,  # noqa: ARG002
    ) -> list[SearchResult]:
        """Search SkyWatch EarthCache archive."""
        raise SkyWatchNotImplementedError

    def order(self, scene_id: str) -> OrderId:  # noqa: ARG002
        """Submit order to SkyWatch EarthCache."""
        raise SkyWatchNotImplementedError

    def poll(self, order_id: str) -> OrderStatus:  # noqa: ARG002
        """Poll order status from SkyWatch."""
        raise SkyWatchNotImplementedError

    def download(self, order_id: str) -> BlobReference:  # noqa: ARG002
        """Download imagery from SkyWatch."""
        raise SkyWatchNotImplementedError
