"""Imagery provider adapters.

Implements the provider-agnostic adapter pattern (Strategy pattern):
- ImageryProvider: Abstract base class defining the interface
- PlanetaryComputerAdapter: Microsoft Planetary Computer (STAC, free, dev/test)
- SkyWatchAdapter: SkyWatch EarthCache (paid, production)

The active provider is selected via configuration, enabling zero-code-change
provider switching.
"""
