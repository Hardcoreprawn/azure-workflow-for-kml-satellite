"""Protocol definitions for external module dependencies.

Provides type-safe abstractions for third-party modules that don't ship
with type stubs or use complex dynamic APIs. Using Protocol allows us
to specify the exact API surface we depend on without requiring the
actual module at type-check time.

References:
    PEP 544 — Structural Subtyping (Static Duck Typing)
    PID 7.4.5 — Explicit Over Implicit (strong typing)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

# ---------------------------------------------------------------------------
# Rasterio Protocols
# ---------------------------------------------------------------------------


class RasterArray(Protocol):
    """Protocol for raster-like array results returned by rasterio reads."""

    shape: tuple[int, ...]


class RasterDataset(Protocol):
    """Protocol for rasterio.DatasetReader/Writer.

    Defines the minimum API surface used from rasterio datasets.
    Read-only members are declared as class-level annotations so Protocol
    recognises them as abstract instance attributes without method stubs.
    """

    # Instance attributes (read-only in rasterio, declared as protocol members)
    crs: object
    bounds: tuple[float, float, float, float]
    transform: object
    meta: dict[str, object]
    profile: dict[str, object]
    width: int
    height: int
    count: int

    def read(self, *args: object, **kwargs: object) -> RasterArray: ...

    def write(self, *args: RasterArray, **kwargs: object) -> None: ...


class RasterioModule(Protocol):
    """Protocol for the rasterio module.

    Specifies the rasterio API surface used in post-processing activities.
    Submodule attributes (mask, warp, crs) are declared as class-level
    annotations; callable methods use standard Protocol stub form.
    """

    # Submodule attributes
    mask: object
    warp: object
    crs: object

    def open(
        self, fp: str, mode: str = "r", **kwargs: object
    ) -> AbstractContextManager[RasterDataset]: ...

    def band(self, ds: RasterDataset, bidx: int) -> RasterArray: ...


# ---------------------------------------------------------------------------
# Planetary Computer Protocol
# ---------------------------------------------------------------------------


class PlanetaryComputerModule(Protocol):
    """Protocol for the planetary_computer module.

    Specifies the API surface for signing STAC asset URLs with SAS tokens.
    """

    def sign(self, url: str) -> str: ...


# ---------------------------------------------------------------------------
# Callable Protocols
# ---------------------------------------------------------------------------


class SignerProtocol(Protocol):
    """Protocol for URL signing functions.

    Generic abstraction for callables that add authentication tokens to URLs
    (e.g., SAS tokens, signed URLs).
    """

    def __call__(self, url: str) -> str: ...
