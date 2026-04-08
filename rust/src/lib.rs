#![deny(warnings)]
#![warn(clippy::all)]

use numpy::ndarray::{Array2, Zip};
use numpy::{IntoPyArray, PyArray2, PyReadonlyArray2};
use pyo3::prelude::*;
use rayon::prelude::*;

/// Helper: extract a contiguous slice from a 2-D array, returning a Python
/// ValueError instead of panicking if the array is not contiguous.
fn contiguous_slice<'a, T: numpy::Element>(
    arr: &'a numpy::ndarray::ArrayView2<'a, T>,
    name: &str,
) -> PyResult<&'a [T]> {
    arr.as_slice().ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err(format!("{name} array is not contiguous"))
    })
}

// ---------------------------------------------------------------------------
// NDVI band math  (hotspot #1)
// ---------------------------------------------------------------------------

/// Compute NDVI from red (B04) and NIR (B08) bands.
///
/// Returns (ndvi, valid_mask) where:
///   - ndvi is float32 with NaN for invalid pixels
///   - valid_mask is bool (True where both bands > 0 and NDVI is finite)
#[pyfunction]
fn compute_ndvi_array<'py>(
    py: Python<'py>,
    red: PyReadonlyArray2<'py, f32>,
    nir: PyReadonlyArray2<'py, f32>,
) -> PyResult<(Bound<'py, PyArray2<f32>>, Bound<'py, PyArray2<bool>>)> {
    let red = red.as_array();
    let nir = nir.as_array();

    let rows = red.nrows();
    let cols = red.ncols();

    // Flat buffers for parallel iteration
    let size = rows * cols;
    let mut ndvi_buf = vec![f32::NAN; size];
    let mut valid_buf = vec![false; size];

    let red_slice = contiguous_slice(&red, "red")?;
    let nir_slice = contiguous_slice(&nir, "nir")?;

    ndvi_buf
        .par_iter_mut()
        .zip(valid_buf.par_iter_mut())
        .enumerate()
        .for_each(|(i, (ndvi_out, valid_out))| {
            let r = red_slice[i];
            let n = nir_slice[i];
            let denom = n + r;
            if r > 0.0 && n > 0.0 && denom > 0.0 {
                let val = (n - r) / denom;
                if val.is_finite() {
                    *ndvi_out = val;
                    *valid_out = true;
                }
            }
        });

    let ndvi = Array2::from_shape_vec((rows, cols), ndvi_buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let valid = Array2::from_shape_vec((rows, cols), valid_buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok((ndvi.into_pyarray(py), valid.into_pyarray(py)))
}

/// Compute statistics over valid NDVI pixels.
///
/// Returns dict with mean, min, max, std, median, valid_pixels, total_pixels.
#[pyfunction]
fn ndvi_stats(py: Python<'_>, ndvi: PyReadonlyArray2<'_, f32>, valid: PyReadonlyArray2<'_, bool>) -> PyResult<PyObject> {
    let ndvi = ndvi.as_array();
    let valid = valid.as_array();

    let mut vals: Vec<f32> = Vec::new();
    let total = ndvi.len();

    Zip::from(&ndvi).and(&valid).for_each(|&v, &m| {
        if m {
            vals.push(v);
        }
    });

    if vals.is_empty() {
        return Ok(py.None());
    }

    let n = vals.len() as f64;
    let sum: f64 = vals.iter().map(|&v| v as f64).sum();
    let mean = sum / n;

    let mut min_v = f64::INFINITY;
    let mut max_v = f64::NEG_INFINITY;
    let mut sq_sum = 0.0_f64;

    for &v in &vals {
        let vf = v as f64;
        if vf < min_v {
            min_v = vf;
        }
        if vf > max_v {
            max_v = vf;
        }
        let diff = vf - mean;
        sq_sum += diff * diff;
    }

    let std = (sq_sum / n).sqrt();

    // Median via partial sort
    vals.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median = if vals.len() % 2 == 0 {
        let mid = vals.len() / 2;
        (vals[mid - 1] as f64 + vals[mid] as f64) / 2.0
    } else {
        vals[vals.len() / 2] as f64
    };

    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("mean", (mean * 10000.0).round() / 10000.0)?;
    dict.set_item("min", (min_v * 10000.0).round() / 10000.0)?;
    dict.set_item("max", (max_v * 10000.0).round() / 10000.0)?;
    dict.set_item("std", (std * 10000.0).round() / 10000.0)?;
    dict.set_item("median", (median * 10000.0).round() / 10000.0)?;
    dict.set_item("valid_pixels", vals.len())?;
    dict.set_item("total_pixels", total)?;

    Ok(dict.into())
}

// ---------------------------------------------------------------------------
// SCL nearest-neighbour resampling  (hotspot #3)
// ---------------------------------------------------------------------------

/// Resize a 2D uint8 array via nearest-neighbour resampling.
///
/// Designed for Sentinel-2 SCL band (20 m → 10 m) but works for any
/// categorical raster where interpolation is invalid.
#[pyfunction]
fn resample_nearest<'py>(
    py: Python<'py>,
    src: PyReadonlyArray2<'py, u8>,
    target_rows: usize,
    target_cols: usize,
) -> PyResult<Bound<'py, PyArray2<u8>>> {
    let src = src.as_array();
    let src_rows = src.nrows();
    let src_cols = src.ncols();

    if src_rows == target_rows && src_cols == target_cols {
        return Ok(src.to_owned().into_pyarray(py));
    }

    let row_scale = src_rows as f64 / target_rows as f64;
    let col_scale = src_cols as f64 / target_cols as f64;

    let src_slice = contiguous_slice(&src, "src")?;

    // Build row and column index lookup tables
    let row_idx: Vec<usize> = (0..target_rows)
        .map(|r| {
            let mapped = ((r as f64 + 0.5) * row_scale - 0.5).round() as isize;
            mapped.clamp(0, (src_rows - 1) as isize) as usize
        })
        .collect();

    let col_idx: Vec<usize> = (0..target_cols)
        .map(|c| {
            let mapped = ((c as f64 + 0.5) * col_scale - 0.5).round() as isize;
            mapped.clamp(0, (src_cols - 1) as isize) as usize
        })
        .collect();

    let mut out = vec![0u8; target_rows * target_cols];

    out.par_chunks_mut(target_cols)
        .enumerate()
        .for_each(|(r, row_out)| {
            let sr = row_idx[r];
            let src_row_offset = sr * src_cols;
            for (c, pixel) in row_out.iter_mut().enumerate() {
                *pixel = src_slice[src_row_offset + col_idx[c]];
            }
        });

    let arr = Array2::from_shape_vec((target_rows, target_cols), out)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    Ok(arr.into_pyarray(py))
}

// ---------------------------------------------------------------------------
// Change detection pixel math  (hotspot #2)
// ---------------------------------------------------------------------------

/// Thread-local accumulator for parallel delta computation.
#[derive(Clone)]
struct DeltaAccum {
    sum: f64,
    sq_sum: f64,
    min_v: f64,
    max_v: f64,
    n_valid: u64,
    n_loss: u64,
    n_gain: u64,
    n_stable: u64,
}

impl DeltaAccum {
    fn new() -> Self {
        Self {
            sum: 0.0, sq_sum: 0.0,
            min_v: f64::INFINITY, max_v: f64::NEG_INFINITY,
            n_valid: 0, n_loss: 0, n_gain: 0, n_stable: 0,
        }
    }

    fn merge(mut self, other: Self) -> Self {
        self.sum += other.sum;
        self.sq_sum += other.sq_sum;
        self.min_v = self.min_v.min(other.min_v);
        self.max_v = self.max_v.max(other.max_v);
        self.n_valid += other.n_valid;
        self.n_loss += other.n_loss;
        self.n_gain += other.n_gain;
        self.n_stable += other.n_stable;
        self
    }

    /// Classify a single valid delta and accumulate stats.
    fn record(&mut self, df: f64, loss_threshold: f64, gain_threshold: f64) {
        self.sum += df;
        self.sq_sum += df * df;
        if df < self.min_v { self.min_v = df; }
        if df > self.max_v { self.max_v = df; }
        self.n_valid += 1;
        if df < loss_threshold { self.n_loss += 1; }
        else if df > gain_threshold { self.n_gain += 1; }
        else { self.n_stable += 1; }
    }
}

/// Round a float to 4 decimal places.
fn round4(v: f64) -> f64 {
    (v * 10000.0).round() / 10000.0
}

/// Compute the median of a sorted f32 slice (as f64).
fn sorted_median(vals: &[f32]) -> f64 {
    if vals.len() % 2 == 0 {
        let mid = vals.len() / 2;
        (vals[mid - 1] as f64 + vals[mid] as f64) / 2.0
    } else {
        vals[vals.len() / 2] as f64
    }
}

/// Build the stats dict from accumulated delta statistics.
fn build_change_dict(
    py: Python<'_>,
    acc: &DeltaAccum,
    median: f64,
    pixel_area_ha: f64,
) -> PyResult<PyObject> {
    let nf = acc.n_valid as f64;
    let mean = acc.sum / nf;
    let std = ((acc.sq_sum / nf) - mean * mean).abs().sqrt();

    let ha = |count: u64| (count as f64 * pixel_area_ha * 100.0).round() / 100.0;
    let pct = |count: u64| if nf > 0.0 { (count as f64 / nf * 1000.0).round() / 10.0 } else { 0.0 };

    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("mean_delta", round4(mean))?;
    dict.set_item("median_delta", round4(median))?;
    dict.set_item("std_delta", round4(std))?;
    dict.set_item("min_delta", round4(acc.min_v))?;
    dict.set_item("max_delta", round4(acc.max_v))?;
    dict.set_item("loss_ha", ha(acc.n_loss))?;
    dict.set_item("gain_ha", ha(acc.n_gain))?;
    dict.set_item("stable_ha", ha(acc.n_stable))?;
    dict.set_item("total_ha", ha(acc.n_valid))?;
    dict.set_item("loss_pct", pct(acc.n_loss))?;
    dict.set_item("gain_pct", pct(acc.n_gain))?;
    dict.set_item("valid_pixels", acc.n_valid)?;
    Ok(dict.into())
}

/// Compute per-pixel NDVI change and aggregate statistics.
///
/// Accepts two float32 NDVI arrays (earlier and later) and thresholds.
/// Returns (delta_array, stats_dict) where delta = later - earlier for
/// valid pixels (both finite), NaN elsewhere.
#[pyfunction]
fn compute_change<'py>(
    py: Python<'py>,
    ndvi_a: PyReadonlyArray2<'py, f32>,
    ndvi_b: PyReadonlyArray2<'py, f32>,
    pixel_area_ha: f64,
    loss_threshold: f64,
    gain_threshold: f64,
) -> PyResult<(Bound<'py, PyArray2<f32>>, PyObject)> {
    let a = ndvi_a.as_array();
    let b = ndvi_b.as_array();
    let rows = a.nrows().min(b.nrows());
    let cols = a.ncols().min(b.ncols());
    let size = rows * cols;
    let mut delta_buf = vec![f32::NAN; size];

    let a_slice = contiguous_slice(&a, "ndvi_a")?;
    let b_slice = contiguous_slice(&b, "ndvi_b")?;

    let acc = delta_buf
        .par_iter_mut()
        .enumerate()
        .fold(DeltaAccum::new, |mut acc, (i, out)| {
            let ai = a_slice[(i / cols) * a.ncols() + (i % cols)];
            let bi = b_slice[(i / cols) * b.ncols() + (i % cols)];
            if ai.is_finite() && bi.is_finite() {
                let d = bi - ai;
                *out = d;
                acc.record(d as f64, loss_threshold, gain_threshold);
            }
            acc
        })
        .reduce(DeltaAccum::new, DeltaAccum::merge);

    let to_array = |buf| Array2::from_shape_vec((rows, cols), buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()));

    if acc.n_valid == 0 {
        return Ok((to_array(delta_buf)?.into_pyarray(py), py.None()));
    }

    let mut valid_vals: Vec<f32> = delta_buf.iter().copied().filter(|v| v.is_finite()).collect();
    valid_vals.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median = sorted_median(&valid_vals);

    let stats = build_change_dict(py, &acc, median, pixel_area_ha)?;
    Ok((to_array(delta_buf)?.into_pyarray(py), stats))
}

// ---------------------------------------------------------------------------
// Apply SCL mask to an existing valid_mask (in-place)
// ---------------------------------------------------------------------------

/// Apply SCL mask: keep only pixels where SCL class is in valid_classes.
///
/// Returns the count of pixels that were valid before but masked by SCL.
#[pyfunction]
fn apply_scl_mask(
    valid: &Bound<'_, PyArray2<bool>>,
    scl: PyReadonlyArray2<'_, u8>,
    valid_classes: Vec<u8>,
) -> PyResult<u64> {
    use numpy::PyArrayMethods;

    let scl = scl.as_array();
    // SAFETY: No other thread accesses this array during execution.
    // PyO3 holds the GIL, so Python cannot touch it concurrently.
    // We only write `false` (narrowing the valid set), never `true`.
    let mut valid_rw = unsafe { valid.as_array_mut() };

    let mut masked_count = 0u64;

    Zip::from(&mut valid_rw).and(&scl).for_each(|v, &s| {
        if *v && !valid_classes.contains(&s) {
            *v = false;
            masked_count += 1;
        }
    });

    Ok(masked_count)
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

#[pymodule]
fn treesight_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_ndvi_array, m)?)?;
    m.add_function(wrap_pyfunction!(ndvi_stats, m)?)?;
    m.add_function(wrap_pyfunction!(resample_nearest, m)?)?;
    m.add_function(wrap_pyfunction!(compute_change, m)?)?;
    m.add_function(wrap_pyfunction!(apply_scl_mask, m)?)?;
    Ok(())
}
