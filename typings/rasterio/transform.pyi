"""Minimal type stubs for rasterio.transform (and affine.Affine)."""

from collections.abc import Iterator

class Affine:
    """Affine transformation matrix (6 coefficients, column-major)."""

    def __getitem__(self, index: int) -> float: ...
    def __iter__(self) -> Iterator[float]: ...
    def __len__(self) -> int: ...


def from_bounds(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
) -> Affine: ...
