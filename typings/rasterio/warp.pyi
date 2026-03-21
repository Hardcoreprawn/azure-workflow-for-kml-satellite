"""Minimal type stubs for rasterio.warp."""

import enum

import numpy
from rasterio import Band
from rasterio.crs import CRS
from rasterio.transform import Affine

class Resampling(enum.IntEnum):
    nearest = 0
    bilinear = 1
    cubic = 2
    lanczos = 3
    average = 5
    mode = 6


def calculate_default_transform(
    src_crs: CRS | str,
    dst_crs: CRS | str,
    width: int,
    height: int,
    left: float,
    bottom: float,
    right: float,
    top: float,
) -> tuple[Affine, int, int]: ...


def reproject(
    source: Band | numpy.ndarray,
    destination: Band | numpy.ndarray,
    src_transform: Affine | None = None,
    src_crs: CRS | str | None = None,
    dst_transform: Affine | None = None,
    dst_crs: CRS | str | None = None,
    resampling: Resampling = Resampling.nearest,
    **kwargs: object,
) -> tuple[numpy.ndarray, Affine]: ...
