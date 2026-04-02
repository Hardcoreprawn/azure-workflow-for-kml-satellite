use numpy::ndarray::{Array2, Zip};
use numpy::{IntoPyArray, PyArray2, PyReadonlyArray2};
use pyo3::prelude::*;
use rayon::prelude::*;

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

    let red_slice = red.as_slice().expect("red array not contiguous");
    let nir_slice = nir.as_slice().expect("nir array not contiguous");

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

    let src_slice = src.as_slice().expect("src array not contiguous");

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

    let a_slice = a.as_slice().expect("ndvi_a not contiguous");
    let b_slice = b.as_slice().expect("ndvi_b not contiguous");

    // Parallel pixel-level delta + classification
    // Use thread-local accumulators, then reduce
    let (sum, sq_sum, min_v, max_v, n_valid, n_loss, n_gain, n_stable) = delta_buf
        .par_iter_mut()
        .enumerate()
        .fold(
            || (0.0f64, 0.0f64, f64::INFINITY, f64::NEG_INFINITY, 0u64, 0u64, 0u64, 0u64),
            |mut acc, (i, out)| {
                let row = i / cols;
                let col = i % cols;
                let ai = a_slice[row * a.ncols() + col];
                let bi = b_slice[row * b.ncols() + col];
                if ai.is_finite() && bi.is_finite() {
                    let d = bi - ai;
                    *out = d;
                    let df = d as f64;
                    acc.0 += df;
                    acc.1 += df * df;
                    if df < acc.2 { acc.2 = df; }
                    if df > acc.3 { acc.3 = df; }
                    acc.4 += 1;
                    if df < loss_threshold { acc.5 += 1; }
                    else if df > gain_threshold { acc.6 += 1; }
                    else { acc.7 += 1; }
                }
                acc
            },
        )
        .reduce(
            || (0.0, 0.0, f64::INFINITY, f64::NEG_INFINITY, 0, 0, 0, 0),
            |a, b| (
                a.0 + b.0,
                a.1 + b.1,
                a.2.min(b.2),
                a.3.max(b.3),
                a.4 + b.4,
                a.5 + b.5,
                a.6 + b.6,
                a.7 + b.7,
            ),
        );

    if n_valid == 0 {
        return Ok((
            Array2::from_shape_vec((rows, cols), delta_buf)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
                .into_pyarray(py),
            py.None(),
        ));
    }

    let nf = n_valid as f64;
    let mean = sum / nf;
    let std = ((sq_sum / nf) - mean * mean).abs().sqrt();

    // Median requires collecting valid values and sorting
    let mut valid_vals: Vec<f32> = Vec::with_capacity(n_valid as usize);
    for i in 0..size {
        if delta_buf[i].is_finite() {
            valid_vals.push(delta_buf[i]);
        }
    }
    valid_vals.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median = if valid_vals.len() % 2 == 0 {
        let mid = valid_vals.len() / 2;
        (valid_vals[mid - 1] as f64 + valid_vals[mid] as f64) / 2.0
    } else {
        valid_vals[valid_vals.len() / 2] as f64
    };

    let round4 = |v: f64| (v * 10000.0).round() / 10000.0;

    let dict = pyo3::types::PyDict::new(py);
    dict.set_item("mean_delta", round4(mean))?;
    dict.set_item("median_delta", round4(median))?;
    dict.set_item("std_delta", round4(std))?;
    dict.set_item("min_delta", round4(sum.min(min_v)))?;  // guard
    dict.set_item("min_delta", round4(min_v))?;
    dict.set_item("max_delta", round4(max_v))?;
    dict.set_item("loss_ha", (n_loss as f64 * pixel_area_ha * 100.0).round() / 100.0)?;
    dict.set_item("gain_ha", (n_gain as f64 * pixel_area_ha * 100.0).round() / 100.0)?;
    dict.set_item("stable_ha", (n_stable as f64 * pixel_area_ha * 100.0).round() / 100.0)?;
    dict.set_item("total_ha", (nf * pixel_area_ha * 100.0).round() / 100.0)?;
    dict.set_item("loss_pct", if nf > 0.0 { (n_loss as f64 / nf * 1000.0).round() / 10.0 } else { 0.0 })?;
    dict.set_item("gain_pct", if nf > 0.0 { (n_gain as f64 / nf * 1000.0).round() / 10.0 } else { 0.0 })?;
    dict.set_item("valid_pixels", n_valid)?;

    let delta = Array2::from_shape_vec((rows, cols), delta_buf)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok((delta.into_pyarray(py), dict.into()))
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
