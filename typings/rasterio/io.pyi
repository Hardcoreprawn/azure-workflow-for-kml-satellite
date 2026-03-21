"""Minimal type stubs for rasterio.io."""

from types import TracebackType

import numpy
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.windows import Window

class DatasetReader:
    width: int
    height: int
    count: int
    dtypes: tuple[str, ...]
    crs: CRS | None
    bounds: tuple[float, float, float, float]
    transform: Affine
    nodata: float | None
    driver: str
    profile: dict[str, object]

    def read(
        self,
        indexes: int | list[int] | None = ...,
        window: Window | None = ...,
        **kwargs: object,
    ) -> numpy.ndarray: ...

    def window_transform(self, window: Window) -> Affine: ...

    def __enter__(self) -> DatasetReader: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


class DatasetWriter:
    def write(
        self,
        data: numpy.ndarray,
        indexes: int | None = None,
    ) -> None: ...

    def __enter__(self) -> DatasetWriter: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


class MemoryFile:
    def __init__(self, data: bytes | None = ...) -> None: ...
    def open(self) -> DatasetReader: ...

    def __enter__(self) -> MemoryFile: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
