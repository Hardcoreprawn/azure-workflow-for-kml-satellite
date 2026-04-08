"""Tests for the treesight_rs Rust/PyO3 acceleration module."""

from __future__ import annotations

import numpy as np
import pytest

# All tests skip gracefully if Rust extension not installed.
rs = pytest.importorskip("treesight_rs")


# ---------------------------------------------------------------------------
# §1 — compute_ndvi_array
# ---------------------------------------------------------------------------


class TestComputeNdviArray:
    def test_basic_band_math(self):
        red = np.array([[100, 200, 0]], dtype=np.float32)
        nir = np.array([[300, 200, 0]], dtype=np.float32)
        ndvi, valid = rs.compute_ndvi_array(red, nir)

        assert ndvi.shape == (1, 3)
        assert valid.shape == (1, 3)
        # pixel 0: (300-100)/(300+100) = 0.5
        assert pytest.approx(ndvi[0, 0], abs=1e-4) == 0.5
        # pixel 1: (200-200)/(200+200) = 0.0
        assert pytest.approx(ndvi[0, 1], abs=1e-4) == 0.0
        # pixel 2: both zero → NaN, invalid
        assert np.isnan(ndvi[0, 2])
        assert valid[0, 0] is np.True_
        assert valid[0, 1] is np.True_
        assert valid[0, 2] is np.False_

    def test_large_array(self):
        rng = np.random.default_rng(42)
        red = rng.integers(0, 5000, size=(512, 512)).astype(np.float32)
        nir = rng.integers(0, 5000, size=(512, 512)).astype(np.float32)
        ndvi, valid = rs.compute_ndvi_array(red, nir)
        assert ndvi.shape == (512, 512)
        assert valid.dtype == bool


# ---------------------------------------------------------------------------
# §2 — ndvi_stats
# ---------------------------------------------------------------------------


class TestNdviStats:
    def test_returns_dict_with_expected_keys(self):
        ndvi = np.array([[0.3, 0.5], [np.nan, 0.7]], dtype=np.float32)
        valid = np.array([[True, True], [False, True]])
        stats = rs.ndvi_stats(ndvi, valid)
        assert isinstance(stats, dict)
        assert set(stats.keys()) >= {
            "mean",
            "min",
            "max",
            "std",
            "median",
            "valid_pixels",
            "total_pixels",
        }
        assert stats["valid_pixels"] == 3
        assert stats["total_pixels"] == 4
        assert pytest.approx(stats["mean"], abs=1e-4) == 0.5

    def test_no_valid_pixels(self):
        ndvi = np.full((2, 2), np.nan, dtype=np.float32)
        valid = np.zeros((2, 2), dtype=bool)
        result = rs.ndvi_stats(ndvi, valid)
        assert result is None


# ---------------------------------------------------------------------------
# §3 — resample_nearest
# ---------------------------------------------------------------------------


class TestResampleNearest:
    def test_upsample_2x(self):
        src = np.array([[1, 2], [3, 4]], dtype=np.uint8)
        out = rs.resample_nearest(src, 4, 4)
        assert out.shape == (4, 4)
        # Corners should replicate
        assert out[0, 0] == 1
        assert out[0, 3] == 2
        assert out[3, 0] == 3
        assert out[3, 3] == 4

    def test_same_size_passthrough(self):
        src = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        out = rs.resample_nearest(src, 2, 2)
        np.testing.assert_array_equal(out, src)

    def test_downsample(self):
        src = np.ones((100, 100), dtype=np.uint8) * 42
        out = rs.resample_nearest(src, 10, 10)
        assert out.shape == (10, 10)
        assert np.all(out == 42)


# ---------------------------------------------------------------------------
# §4 — compute_change
# ---------------------------------------------------------------------------


class TestComputeChange:
    def test_basic_change_detection(self):
        a = np.array([[0.5, 0.3], [0.7, 0.2]], dtype=np.float32)
        b = np.array([[0.6, 0.1], [0.8, 0.9]], dtype=np.float32)
        delta, stats = rs.compute_change(a, b, 0.01, -0.1, 0.1)
        assert delta.shape == (2, 2)
        assert isinstance(stats, dict)
        assert "mean_delta" in stats
        assert "loss_ha" in stats
        assert stats["valid_pixels"] == 4

    def test_all_nan_returns_none_stats(self):
        a = np.full((2, 2), np.nan, dtype=np.float32)
        b = np.full((2, 2), np.nan, dtype=np.float32)
        _delta, stats = rs.compute_change(a, b, 0.01, -0.1, 0.1)
        assert stats is None

    def test_loss_and_gain_classification(self):
        a = np.array([[0.8, 0.2]], dtype=np.float32)
        b = np.array([[0.5, 0.6]], dtype=np.float32)
        _delta, stats = rs.compute_change(a, b, 0.01, -0.1, 0.1)
        # pixel 0: delta = -0.3 (loss), pixel 1: delta = +0.4 (gain)
        assert stats["loss_pct"] == 50.0
        assert stats["gain_pct"] == 50.0

    def test_min_delta_is_smallest_per_pixel_change(self):
        """Regression: min_delta must be the smallest single-pixel delta,
        not min(running_sum, min_delta) which compared unrelated values."""
        a = np.array([[0.8, 0.2, 0.5]], dtype=np.float32)
        b = np.array([[0.5, 0.6, 0.4]], dtype=np.float32)
        # deltas: -0.3, +0.4, -0.1
        _delta, stats = rs.compute_change(a, b, 0.01, -0.5, 0.5)
        assert pytest.approx(stats["min_delta"], abs=1e-4) == -0.3
        assert pytest.approx(stats["max_delta"], abs=1e-4) == 0.4


# ---------------------------------------------------------------------------
# §5 — apply_scl_mask
# ---------------------------------------------------------------------------


class TestApplyScLMask:
    def test_masks_invalid_classes(self):
        valid = np.array([[True, True], [True, True]])
        scl = np.array([[4, 8], [5, 3]], dtype=np.uint8)
        masked_count = rs.apply_scl_mask(valid, scl, [4, 5])
        assert masked_count == 2
        assert valid[0, 0] is np.True_  # class 4 → kept
        assert valid[0, 1] is np.False_  # class 8 → masked
        assert valid[1, 0] is np.True_  # class 5 → kept
        assert valid[1, 1] is np.False_  # class 3 → masked

    def test_no_mask_when_all_valid(self):
        valid = np.array([[True, True]], dtype=bool)
        scl = np.array([[4, 5]], dtype=np.uint8)
        masked_count = rs.apply_scl_mask(valid, scl, [4, 5, 6])
        assert masked_count == 0
        assert np.all(valid)


# ---------------------------------------------------------------------------
# §6 — Pipeline integration: Rust vs Python parity
# ---------------------------------------------------------------------------


class TestRustPythonParity:
    """Verify Rust functions produce equivalent results to pure-Python."""

    def test_ndvi_parity(self):
        rng = np.random.default_rng(99)
        red = rng.integers(1, 4000, size=(64, 64)).astype(np.float32)
        nir = rng.integers(1, 4000, size=(64, 64)).astype(np.float32)

        # Rust
        r_ndvi, r_valid = rs.compute_ndvi_array(red, nir)

        # Python
        denom = nir + red
        p_ndvi = np.where(denom > 0, (nir - red) / denom, np.nan)
        p_valid = (red > 0) & (nir > 0) & np.isfinite(p_ndvi)

        np.testing.assert_allclose(r_ndvi[r_valid], p_ndvi[p_valid], atol=1e-5)
        np.testing.assert_array_equal(r_valid, p_valid)

    def test_resample_parity(self):
        src = np.arange(25, dtype=np.uint8).reshape(5, 5)
        target = (10, 10)

        # Rust
        r_out = rs.resample_nearest(src, *target)

        # Python (same algorithm as _resample_scl)
        row_scale = src.shape[0] / target[0]
        col_scale = src.shape[1] / target[1]
        row_idx = np.rint((np.arange(target[0]) + 0.5) * row_scale - 0.5).astype(int)
        col_idx = np.rint((np.arange(target[1]) + 0.5) * col_scale - 0.5).astype(int)
        np.clip(row_idx, 0, src.shape[0] - 1, out=row_idx)
        np.clip(col_idx, 0, src.shape[1] - 1, out=col_idx)
        p_out = src[np.ix_(row_idx, col_idx)]

        np.testing.assert_array_equal(r_out, p_out)
