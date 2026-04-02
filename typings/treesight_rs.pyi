"""Type stubs for the treesight_rs Rust/PyO3 extension module."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

def compute_ndvi_array(
    red: NDArray[np.float32],
    nir: NDArray[np.float32],
) -> tuple[NDArray[np.float32], NDArray[np.bool_]]: ...
def ndvi_stats(
    ndvi: NDArray[np.float32],
    valid: NDArray[np.bool_],
) -> dict[str, float | int] | None: ...
def resample_nearest(
    src: NDArray[np.uint8],
    target_rows: int,
    target_cols: int,
) -> NDArray[np.uint8]: ...
def compute_change(
    ndvi_a: NDArray[np.float32],
    ndvi_b: NDArray[np.float32],
    pixel_area_ha: float,
    loss_threshold: float,
    gain_threshold: float,
) -> tuple[NDArray[np.float32], dict[str, float | int] | None]: ...
def apply_scl_mask(
    valid: NDArray[np.bool_],
    scl: NDArray[np.uint8],
    valid_classes: list[int],
) -> int: ...
