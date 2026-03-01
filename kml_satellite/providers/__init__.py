"""Imagery provider adapters.

Implements the provider-agnostic adapter pattern (Strategy pattern):
- ImageryProvider: Abstract base class defining the interface
- PlanetaryComputerAdapter: Microsoft Planetary Computer (STAC, free, dev/test)

The active provider is selected via configuration, enabling zero-code-change
provider switching.

References:
    PID FR-3.1  (provider-agnostic abstraction layer)
    PID Section 7.3  (Provider Adapter Layer)
"""

from kml_satellite.providers.base import (
    ImageryProvider,
    ProviderAuthError,
    ProviderDownloadError,
    ProviderError,
    ProviderOrderError,
    ProviderSearchError,
)
from kml_satellite.providers.factory import (
    PLANETARY_COMPUTER,
    clear_provider_cache,
    get_provider,
    list_providers,
    register_provider,
)

__all__ = [
    "PLANETARY_COMPUTER",
    "ImageryProvider",
    "ProviderAuthError",
    "ProviderDownloadError",
    "ProviderError",
    "ProviderOrderError",
    "ProviderSearchError",
    "clear_provider_cache",
    "get_provider",
    "list_providers",
    "register_provider",
]
