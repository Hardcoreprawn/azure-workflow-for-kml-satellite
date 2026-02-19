"""ImageryProvider abstract base class.

Defines the contract that every imagery provider adapter must implement.
The orchestrator interacts exclusively with this interface — it never
knows (or cares) which concrete provider is behind it.

Lifecycle:
    1. ``search(aoi, filters)`` — find scenes covering an AOI.
    2. ``order(scene_id)``      — request imagery delivery.
    3. ``poll(order_id)``       — check delivery status (may be instant).
    4. ``download(order_id)``   — download imagery and return a ``BlobReference``.

Each concrete adapter (``PlanetaryComputerAdapter``, ``SkyWatchAdapter``, etc.)
implements these four methods per the provider's API specifics.

References:
    PID FR-3.1   (provider-agnostic abstraction layer)
    PID Section 7.3  (Provider Adapter Layer diagram)
    PID Section 7.6  (Two-adapter strategy)
    PID Section 7.4.5 (Type hints everywhere)
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from kml_satellite.core.exceptions import PipelineError

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


class ImageryProvider(abc.ABC):
    """Abstract base class for imagery provider adapters.

    Concrete implementations must override ``search``, ``order``, ``poll``,
    and ``download``.  The constructor receives a ``ProviderConfig`` which
    carries the API URL, auth mechanism, and provider-specific parameters.

    Example usage::

        provider = get_provider("planetary_computer")
        results = provider.search(aoi, filters)
        order = provider.order(results[0].scene_id)
        status = provider.poll(order.order_id)
        blob = provider.download(order.order_id)
    """

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        """Return the provider name from configuration."""
        return self._config.name

    @property
    def config(self) -> ProviderConfig:
        """Return the provider configuration (read-only)."""
        return self._config

    # ------------------------------------------------------------------
    # Abstract methods — every adapter must implement these
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def search(
        self,
        aoi: AOI,
        filters: ImageryFilters | None = None,
    ) -> list[SearchResult]:
        """Search the provider's archive for scenes covering *aoi*.

        Args:
            aoi: The area of interest to search for.
            filters: Optional search filters (cloud cover, date range, etc.).
                     If ``None``, the adapter should apply sensible defaults.

        Returns:
            A list of ``SearchResult`` objects, ordered by relevance
            (best match first). Empty list when no scenes match.

        Raises:
            ProviderError: On transient or permanent API errors.
        """

    @abc.abstractmethod
    def order(self, scene_id: str) -> OrderId:
        """Submit an order / download request for the given scene.

        For providers like Planetary Computer where assets are immediately
        available, this may simply wrap the asset URL in an ``OrderId``.

        Args:
            scene_id: Provider-specific scene identifier (from ``SearchResult``).

        Returns:
            An ``OrderId`` representing the submitted order.

        Raises:
            ProviderError: On transient or permanent API errors.
        """

    @abc.abstractmethod
    def poll(self, order_id: str) -> OrderStatus:
        """Check the current status of an imagery order.

        For providers with instant fulfilment (e.g. STAC), this should
        return ``OrderState.READY`` immediately.

        Args:
            order_id: The provider-specific order identifier.

        Returns:
            An ``OrderStatus`` with the current lifecycle state.

        Raises:
            ProviderError: On transient or permanent API errors.
        """

    @abc.abstractmethod
    def download(self, order_id: str) -> BlobReference:
        """Download imagery for a completed order and store it in Blob Storage.

        The adapter is responsible for streaming the imagery to the output
        container and returning a ``BlobReference`` pointing to the stored blob.

        Args:
            order_id: The provider-specific order identifier
                      (must be in ``READY`` state).

        Returns:
            A ``BlobReference`` pointing to the stored imagery.

        Raises:
            ProviderError: If the order is not ready or the download fails.
        """


# ---------------------------------------------------------------------------
# Provider exceptions
# ---------------------------------------------------------------------------


class ProviderError(PipelineError):
    """Base exception for provider adapter errors.

    Attributes:
        provider: Name of the provider that raised the error.
        message: Human-readable error description.
        retryable: Whether the caller should retry the operation.
    """

    default_stage = "provider"
    default_code = "PROVIDER_ERROR"

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.provider = provider
        super().__init__(
            message,
            retryable=retryable,
            code=self.default_code,
            stage=self.default_stage,
        )

    def __str__(self) -> str:
        return f"[{self.provider}] {self.message}"


class ProviderAuthError(ProviderError):
    """Authentication or authorisation failure with the provider API."""

    default_code = "PROVIDER_AUTH_FAILED"

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(provider, message, retryable=False)


class ProviderSearchError(ProviderError):
    """Error during imagery archive search."""

    default_code = "PROVIDER_SEARCH_FAILED"


class ProviderOrderError(ProviderError):
    """Error during order submission or polling."""

    default_code = "PROVIDER_ORDER_FAILED"


class ProviderDownloadError(ProviderError):
    """Error during imagery download."""

    default_code = "PROVIDER_DOWNLOAD_FAILED"
