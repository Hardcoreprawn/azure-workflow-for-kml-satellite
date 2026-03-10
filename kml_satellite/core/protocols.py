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

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

# ---------------------------------------------------------------------------
# Rasterio Protocols
# ---------------------------------------------------------------------------


class RasterDataset(Protocol):
    """Protocol for rasterio.DatasetReader/Writer.

    Defines the minimum API surface used from rasterio datasets.
    Read-only members are declared as class-level annotations so Protocol
    recognises them as abstract instance attributes without method stubs.
    """

    # Instance attributes (read-only in rasterio, declared as protocol members)
    crs: Any
    bounds: tuple[float, float, float, float]
    transform: Any
    meta: dict[str, Any]
    profile: dict[str, Any]
    width: int
    height: int
    count: int

    def read(self, *args: Any, **kwargs: Any) -> Any: ...

    def write(self, *args: Any, **kwargs: Any) -> None: ...


class RasterioModule(Protocol):
    """Protocol for the rasterio module.

    Specifies the rasterio API surface used in post-processing activities.
    Submodule attributes (mask, warp, crs) are declared as class-level
    annotations; callable methods use standard Protocol stub form.
    """

    # Submodule attributes
    mask: Any
    warp: Any
    crs: Any

    def open(
        self, fp: str, mode: str = "r", **kwargs: Any
    ) -> AbstractContextManager[RasterDataset]: ...

    def band(self, ds: RasterDataset, bidx: int) -> Any: ...


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
