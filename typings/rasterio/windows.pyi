"""Minimal type stubs for rasterio.windows."""

from rasterio.transform import Affine

class Window:
    def __init__(
        self,
        col_off: float,
        row_off: float,
        width: float,
        height: float,
    ) -> None: ...
    def intersection(self, other: Window) -> Window: ...

def from_bounds(
    left: float,
    bottom: float,
    right: float,
    top: float,
    transform: Affine | None = ...,
) -> Window: ...
