"""Imagery provider adapters.

Implements the provider-agnostic adapter pattern (Strategy pattern):
- ImageryProvider: Abstract base class defining the interface
- PlanetaryComputerAdapter: Microsoft Planetary Computer (STAC, free, dev/test)
- SkyWatchAdapter: SkyWatch EarthCache (paid, production)

The active provider is selected via configuration, enabling zero-code-change
provider switching.

References:
    PID FR-3.1  (provider-agnostic abstraction layer)
    PID Section 7.3  (Provider Adapter Layer)
    PID Section 7.6  (Two-adapter strategy)
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
    SKYWATCH,
    get_provider,
    list_providers,
    register_provider,
)
from kml_satellite.providers.skywatch import SkyWatchNotImplementedError

__all__ = [
    "PLANETARY_COMPUTER",
    "SKYWATCH",
    "ImageryProvider",
    "ProviderAuthError",
    "ProviderDownloadError",
    "ProviderError",
    "ProviderOrderError",
    "ProviderSearchError",
    "SkyWatchNotImplementedError",
    "get_provider",
    "list_providers",
    "register_provider",
]
