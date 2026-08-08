"""Tests for AOI-aware stub GeoTIFF generation (#1222).

Verifies that ``make_stub_geotiff`` and ``get_stub_geotiff`` derive the
synthetic raster's spatial extent from the supplied bbox rather than returning
a fixed hardcoded extent — a prerequisite for a meaningful multi-AOI corpus
(any other fixture AOI fed through the stub previously got imagery that did
not cover its own geometry).

Covers five AOI shape categories that represent known-tricky pipeline inputs:
  - normal (rectangular)
  - concave polygon
  - multi-polygon
  - polygon with hole
  - huge / large-extent polygon
"""

from __future__ import annotations

import io

import rasterio

from treesight.providers.stub import _FALLBACK_BBOX, get_stub_geotiff, make_stub_geotiff

# ---------------------------------------------------------------------------
# Representative bboxes by shape category (min_lon, min_lat, max_lon, max_lat)
# ---------------------------------------------------------------------------

_NORMAL_BBOX = [36.80, -1.31, 36.81, -1.30]
_CONCAVE_BBOX = [36.75, -1.40, 36.90, -1.20]
_MULTI_POLYGON_BBOX = [10.00, 48.00, 10.50, 48.50]
_POLYGON_WITH_HOLE_BBOX = [-0.15, 51.45, -0.10, 51.50]
_HUGE_EXTENT_BBOX = [-10.00, -5.00, 10.00, 5.00]


def _open_geotiff(data: bytes) -> rasterio.DatasetReader:
    """Return an open rasterio DatasetReader from raw GeoTIFF bytes."""
    return rasterio.open(io.BytesIO(data))


class TestMakeStubGeotiffAOIAware:
    """make_stub_geotiff derives extent from the supplied bbox."""

    def test_normal_bbox_sets_spatial_extent(self):
        tiff = make_stub_geotiff(_NORMAL_BBOX)
        with _open_geotiff(tiff) as src:
            bounds = src.bounds
        assert abs(bounds.left - _NORMAL_BBOX[0]) < 1e-6
        assert abs(bounds.bottom - _NORMAL_BBOX[1]) < 1e-6
        assert abs(bounds.right - _NORMAL_BBOX[2]) < 1e-6
        assert abs(bounds.top - _NORMAL_BBOX[3]) < 1e-6

    def test_concave_polygon_bbox_sets_spatial_extent(self):
        tiff = make_stub_geotiff(_CONCAVE_BBOX)
        with _open_geotiff(tiff) as src:
            bounds = src.bounds
        assert abs(bounds.left - _CONCAVE_BBOX[0]) < 1e-6
        assert abs(bounds.bottom - _CONCAVE_BBOX[1]) < 1e-6
        assert abs(bounds.right - _CONCAVE_BBOX[2]) < 1e-6
        assert abs(bounds.top - _CONCAVE_BBOX[3]) < 1e-6

    def test_multi_polygon_bbox_sets_spatial_extent(self):
        tiff = make_stub_geotiff(_MULTI_POLYGON_BBOX)
        with _open_geotiff(tiff) as src:
            bounds = src.bounds
        assert abs(bounds.left - _MULTI_POLYGON_BBOX[0]) < 1e-6
        assert abs(bounds.bottom - _MULTI_POLYGON_BBOX[1]) < 1e-6
        assert abs(bounds.right - _MULTI_POLYGON_BBOX[2]) < 1e-6
        assert abs(bounds.top - _MULTI_POLYGON_BBOX[3]) < 1e-6

    def test_polygon_with_hole_bbox_sets_spatial_extent(self):
        tiff = make_stub_geotiff(_POLYGON_WITH_HOLE_BBOX)
        with _open_geotiff(tiff) as src:
            bounds = src.bounds
        assert abs(bounds.left - _POLYGON_WITH_HOLE_BBOX[0]) < 1e-6
        assert abs(bounds.top - _POLYGON_WITH_HOLE_BBOX[3]) < 1e-6

    def test_huge_extent_bbox_sets_spatial_extent(self):
        tiff = make_stub_geotiff(_HUGE_EXTENT_BBOX)
        with _open_geotiff(tiff) as src:
            bounds = src.bounds
        assert abs(bounds.left - _HUGE_EXTENT_BBOX[0]) < 1e-6
        assert abs(bounds.bottom - _HUGE_EXTENT_BBOX[1]) < 1e-6
        assert abs(bounds.right - _HUGE_EXTENT_BBOX[2]) < 1e-6
        assert abs(bounds.top - _HUGE_EXTENT_BBOX[3]) < 1e-6

    def test_none_falls_back_to_fixed_sample_extent(self):
        tiff = make_stub_geotiff(None)
        with _open_geotiff(tiff) as src:
            bounds = src.bounds
        assert abs(bounds.left - _FALLBACK_BBOX[0]) < 1e-6
        assert abs(bounds.bottom - _FALLBACK_BBOX[1]) < 1e-6
        assert abs(bounds.right - _FALLBACK_BBOX[2]) < 1e-6
        assert abs(bounds.top - _FALLBACK_BBOX[3]) < 1e-6

    def test_different_bboxes_produce_different_geotiffs(self):
        """Each AOI's stub GeoTIFF must cover a distinct extent."""
        tiff_a = make_stub_geotiff(_NORMAL_BBOX)
        tiff_b = make_stub_geotiff(_CONCAVE_BBOX)
        assert tiff_a != tiff_b

    def test_output_is_valid_geotiff_with_three_bands(self):
        tiff = make_stub_geotiff(_NORMAL_BBOX)
        with _open_geotiff(tiff) as src:
            assert src.count == 3
            assert src.width == 50
            assert src.height == 50

    def test_output_crs_is_epsg4326(self):
        tiff = make_stub_geotiff(_NORMAL_BBOX)
        with _open_geotiff(tiff) as src:
            assert src.crs is not None
            assert "4326" in str(src.crs)

    def test_pixel_values_are_deterministic(self):
        """Pixel values must be identical across repeated calls for the same bbox."""
        tiff_1 = make_stub_geotiff(_NORMAL_BBOX)
        tiff_2 = make_stub_geotiff(_NORMAL_BBOX)
        assert tiff_1 == tiff_2


class TestGetStubGeotiffAOIAware:
    """get_stub_geotiff forwards bbox to make_stub_geotiff and caches only the
    no-bbox (None) path to preserve backward-compatibility."""

    def test_with_bbox_returns_aoi_sized_extent(self):
        tiff = get_stub_geotiff(_NORMAL_BBOX)
        with _open_geotiff(tiff) as src:
            assert abs(src.bounds.left - _NORMAL_BBOX[0]) < 1e-6

    def test_without_bbox_returns_fallback_extent(self):
        tiff = get_stub_geotiff(None)
        with _open_geotiff(tiff) as src:
            assert abs(src.bounds.left - _FALLBACK_BBOX[0]) < 1e-6

    def test_no_arg_same_as_none(self):
        tiff = get_stub_geotiff()
        with _open_geotiff(tiff) as src:
            assert abs(src.bounds.left - _FALLBACK_BBOX[0]) < 1e-6

    def test_none_path_is_cached_identity(self):
        """The no-bbox path must return the same bytes object from the cache."""
        a = get_stub_geotiff(None)
        b = get_stub_geotiff(None)
        assert a is b  # same cached object

    def test_bbox_path_is_not_cached(self):
        """AOI-specific calls must not share a cache entry across different bboxes."""
        a = get_stub_geotiff(_NORMAL_BBOX)
        b = get_stub_geotiff(_CONCAVE_BBOX)
        with _open_geotiff(a) as src_a, _open_geotiff(b) as src_b:
            assert abs(src_a.bounds.left - _NORMAL_BBOX[0]) < 1e-6
            assert abs(src_b.bounds.left - _CONCAVE_BBOX[0]) < 1e-6


class TestFulfilmentCogReadUsesAOIBbox:
    """cog_windowed_read passes bbox to get_stub_geotiff in test mode."""

    def test_stub_geotiff_matches_supplied_bbox_in_test_mode(self, monkeypatch):
        import io as _io

        import rasterio as _rasterio

        monkeypatch.setenv("CANOPEX_TEST_MODE", "1")

        # Must import after monkeypatch so is_test_mode_enabled() sees the env var.
        from treesight.pipeline.fulfilment import cog_windowed_read

        result_bytes = cog_windowed_read("https://stub/fake.tif", _NORMAL_BBOX)

        with _rasterio.open(_io.BytesIO(result_bytes)) as src:
            assert abs(src.bounds.left - _NORMAL_BBOX[0]) < 1e-6
            assert abs(src.bounds.right - _NORMAL_BBOX[2]) < 1e-6

    def test_different_aois_produce_different_extents_in_test_mode(self, monkeypatch):
        import io as _io

        import rasterio as _rasterio

        monkeypatch.setenv("CANOPEX_TEST_MODE", "1")

        from treesight.pipeline.fulfilment import cog_windowed_read

        tiff_a = cog_windowed_read("https://stub/fake.tif", _NORMAL_BBOX)
        tiff_b = cog_windowed_read("https://stub/fake.tif", _HUGE_EXTENT_BBOX)

        with _rasterio.open(_io.BytesIO(tiff_a)) as src_a:
            left_a = src_a.bounds.left
        with _rasterio.open(_io.BytesIO(tiff_b)) as src_b:
            left_b = src_b.bounds.left
        assert left_a != left_b
