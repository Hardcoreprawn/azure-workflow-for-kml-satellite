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

    Defines the minimum API surface we use from rasterio datasets.
    """

    @property
    def crs(self) -> Any:
        """Coordinate reference system of the dataset."""
        ...

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Bounding box of the dataset (minx, miny, maxx, maxy)."""
        ...

    @property
    def transform(self) -> Any:
        """Affine transform for the dataset."""
        ...

    @property
    def meta(self) -> dict[str, Any]:
        """Dataset metadata dictionary."""
        ...

    @property
    def profile(self) -> dict[str, Any]:
        """Dataset profile dictionary (includes metadata)."""
        ...

    @property
    def width(self) -> int:
        """Width of the dataset in pixels."""
        ...

    @property
    def height(self) -> int:
        """Height of the dataset in pixels."""
        ...

    @property
    def count(self) -> int:
        """Number of bands in the dataset."""
        ...

    def read(self, *args: Any, **kwargs: Any) -> Any:
        """Read raster data."""
        ...

    def write(self, *args: Any, **kwargs: Any) -> None:
        """Write raster data."""
        ...


class RasterioModule(Protocol):
    """Protocol for the rasterio module.

    Specifies the rasterio API surface used in post-processing activities.
    """

    def open(
        self, fp: str, mode: str = "r", **kwargs: Any
    ) -> AbstractContextManager[RasterDataset]:
        """Open a raster dataset."""
        ...

    def band(self, ds: RasterDataset, bidx: int) -> Any:
        """Get a band from a dataset."""
        ...

    @property
    def mask(self) -> Any:
        """rasterio.mask submodule for clipping operations."""
        ...

    @property
    def warp(self) -> Any:
        """rasterio.warp submodule for reprojection operations."""
        ...

    @property
    def crs(self) -> Any:
        """rasterio.crs submodule for CRS operations."""
        ...


# ---------------------------------------------------------------------------
# Planetary Computer Protocol
# ---------------------------------------------------------------------------


class PlanetaryComputerModule(Protocol):
    """Protocol for the planetary_computer module.

    Specifies the API for signing STAC asset URLs with SAS tokens.
    """

    def sign(self, url: str) -> str:
        """Sign a URL with a Planetary Computer SAS token.

        Args:
            url: URL to sign (typically a STAC asset href).

        Returns:
            Signed URL with SAS token appended.
        """
        ...


# ---------------------------------------------------------------------------
# Callable Protocols
# ---------------------------------------------------------------------------


class SignerProtocol(Protocol):
    """Protocol for URL signing functions.

    Generic abstraction for functions that add authentication tokens
    to URLs (e.g., SAS tokens, signed URLs).
    """

    def __call__(self, url: str) -> str:
        """Sign a URL.

        Args:
            url: URL to sign.

        Returns:
            Signed URL with authentication token.
        """
        ...
