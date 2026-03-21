"""Minimal type stubs for rasterio — covers only the API surface used by treesight."""

from io import BytesIO
from typing import BinaryIO, Literal, overload

from rasterio import windows as windows
from rasterio.crs import CRS as CRS
from rasterio.io import DatasetReader as DatasetReader
from rasterio.io import DatasetWriter as DatasetWriter
from rasterio.transform import Affine as Affine

class Band:
    """Opaque handle returned by :func:`rasterio.band`."""


@overload
def open(
    fp: str | BytesIO | BinaryIO,
    mode: Literal["w"],
    **kwargs: object,
) -> DatasetWriter: ...


@overload
def open(
    fp: str | BytesIO | BinaryIO,
    mode: str = ...,
    **kwargs: object,
) -> DatasetReader: ...


def band(ds: DatasetReader | DatasetWriter, bidx: int) -> Band: ...
