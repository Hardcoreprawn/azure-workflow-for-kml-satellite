"""Stub providers and helpers for unit / integration tests.

Everything here moved to ``treesight/providers/stub.py`` (#1215) — a live
``func start`` host process needs to import these too, for the local/CI
pipeline e2e gate (both the fake imagery provider and the synthetic GeoTIFF
bytes its fake ``asset_url`` would otherwise fail to fetch). Re-exported
here so existing test imports keep working unchanged.
"""

from __future__ import annotations

from treesight.providers.stub import (
    StubPlanetaryComputerProvider,
    get_stub_geotiff,
    make_stub_geotiff,
)

__all__ = ["StubPlanetaryComputerProvider", "get_stub_geotiff", "make_stub_geotiff"]
