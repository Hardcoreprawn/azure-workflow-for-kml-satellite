"""Provider factory — selects the active imagery provider by name.

The factory maintains a registry of known adapters. New adapters are
registered by adding an entry to ``_ADAPTER_REGISTRY``.

Usage::

    from kml_satellite.providers.factory import get_provider

    provider = get_provider("planetary_computer")
    results = provider.search(aoi, filters)

The provider name is read from the ``IMAGERY_PROVIDER`` environment variable
via ``PipelineConfig.imagery_provider`` (PID Section 7.6).

References:
    PID FR-3.1  (provider-agnostic abstraction)
    PID Section 7.3  (Provider Adapter Layer)
    PID Section 7.6  (Two-adapter strategy — config-driven switching)
    PID Section 7.4.5 (No magic strings — named constants)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kml_satellite.models.imagery import ProviderConfig
from kml_satellite.providers.base import ImageryProvider, ProviderError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider name constants (PID 7.4.5 — no magic strings)
# ---------------------------------------------------------------------------

PLANETARY_COMPUTER = "planetary_computer"
SKYWATCH = "skywatch"

# ---------------------------------------------------------------------------
# Lazy-import adapter registry
# ---------------------------------------------------------------------------

# Each entry maps a provider name to a callable that returns the adapter
# *class*. We use a lazy import so that heavyweight provider dependencies
# (e.g. pystac-client, httpx) are only loaded when that adapter is selected.

_ADAPTER_REGISTRY: dict[str, Callable[[], type[ImageryProvider]]] = {}


def _register_builtin_adapters() -> None:
    """Register the built-in provider adapters.

    Called once on first ``get_provider`` invocation. Each registration
    is a lazy import thunk to avoid loading unused provider dependencies.
    """

    def _planetary_computer() -> type[ImageryProvider]:
        from kml_satellite.providers.planetary_computer import (
            PlanetaryComputerAdapter,
        )

        return PlanetaryComputerAdapter

    def _skywatch() -> type[ImageryProvider]:
        from kml_satellite.providers.skywatch import SkyWatchAdapter

        return SkyWatchAdapter

    _ADAPTER_REGISTRY[PLANETARY_COMPUTER] = _planetary_computer
    _ADAPTER_REGISTRY[SKYWATCH] = _skywatch


def _ensure_registry() -> None:
    """Initialise the adapter registry once (idempotent)."""
    if not _ADAPTER_REGISTRY:
        _register_builtin_adapters()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_provider(
    name: str,
    loader: Callable[[], type[ImageryProvider]],
) -> None:
    """Register a custom provider adapter.

    This allows third-party or test adapters to be plugged in without
    modifying the factory.

    Args:
        name: Provider name (e.g. ``"my_custom_provider"``).
        loader: A zero-argument callable that returns the adapter class.

    Raises:
        ValueError: If the name is empty.
    """
    if not name:
        msg = "Provider name must be non-empty"
        raise ValueError(msg)
    _ensure_registry()
    _ADAPTER_REGISTRY[name] = loader
    logger.debug("Registered provider adapter: %s", name)


def get_provider(
    name: str,
    config: ProviderConfig | None = None,
) -> ImageryProvider:
    """Create and return an imagery provider instance.

    Args:
        name: Provider identifier (e.g. ``"planetary_computer"``, ``"skywatch"``).
        config: Optional ``ProviderConfig``. If ``None``, a default config
                with just the provider name is used.

    Returns:
        A configured ``ImageryProvider`` instance.

    Raises:
        ProviderError: If the named provider is not registered.
    """
    _ensure_registry()

    loader = _ADAPTER_REGISTRY.get(name)
    if loader is None:
        available = ", ".join(sorted(_ADAPTER_REGISTRY))
        msg = f"Unknown imagery provider: {name!r}. Available: {available}"
        raise ProviderError(provider=name, message=msg)

    adapter_cls = loader()

    if config is None:
        config = ProviderConfig(name=name)
    elif config.name != name:
        msg = f"ProviderConfig.name {config.name!r} does not match requested provider {name!r}"
        raise ProviderError(provider=name, message=msg)

    logger.info("Creating imagery provider: %s", name)
    return adapter_cls(config)


def list_providers() -> list[str]:
    """Return the names of all registered provider adapters."""
    _ensure_registry()
    return sorted(_ADAPTER_REGISTRY)
