"""Additional EUDR query-path tests for coverage hardening."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

import treesight.pipeline.eudr as eudr


class _Resp:
    def __init__(self, payload: dict, *, error: Exception | None = None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class _Client:
    def __init__(self, responses: list[_Resp]):
        self._responses = responses
        self.calls: list[dict] = []

    def post(self, _url: str, json: dict):
        self.calls.append(json)
        return self._responses.pop(0)


class _ContextClient:
    def __init__(self, inner: _Client):
        self.inner = inner

    def __enter__(self):
        return self.inner

    def __exit__(self, *_args):
        return False


class TestPointBufferGuards:
    def test_point_buffer_validates_radius_and_segments(self):
        with pytest.raises(ValueError, match="radius_m"):
            eudr._point_buffer(0, 0, 0)
        with pytest.raises(ValueError, match="segments"):
            eudr._point_buffer(0, 0, 10, segments=2)

    def test_point_buffer_returns_closed_ring(self):
        ring = eudr._point_buffer(2.35, 48.86, 100.0, segments=8)
        assert len(ring) == 9  # segments + 1, closing the ring
        assert ring[0] == ring[-1]
        assert all(len(pt) == 2 for pt in ring)

    def test_point_buffer_clamps_near_pole(self):
        """Near the pole, cos(lat) -> 0 would divide-by-zero without clamping."""
        ring = eudr._point_buffer(0.0, 89.9999999, 100.0, segments=4)
        assert len(ring) == 5
        assert all(math.isfinite(pt[0]) and math.isfinite(pt[1]) for pt in ring)


class TestCoordsToKml:
    def test_polygon_plot_closes_ring_and_escapes_name(self):
        kml = eudr.coords_to_kml(
            [{"name": "A & B", "coordinates": [[0, 0], [1, 0], [1, 1]]}],
        )
        assert "<name>A &amp; B</name>" in kml
        # Ring must be auto-closed: first/last coord repeated.
        assert kml.count("0,0,0") == 2

    def test_polygon_plot_already_closed_is_not_duplicated(self):
        kml = eudr.coords_to_kml(
            [{"name": "Closed", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}],
        )
        assert kml.count("0,0,0") == 2

    def test_point_plot_buffers_into_circle(self):
        kml = eudr.coords_to_kml([{"name": "Point", "lon": 2.35, "lat": 48.86}], buffer_m=50.0)
        assert "Buffer radius: 50.0m around (2.35, 48.86)" in kml
        assert "<Polygon>" in kml

    def test_point_plot_uses_custom_radius_over_default_buffer(self):
        kml = eudr.coords_to_kml([{"name": "Point", "lon": 0, "lat": 0, "radius_m": 25.0}])
        assert "Buffer radius: 25.0m" in kml

    def test_invalid_plot_is_skipped_with_warning(self, caplog):
        with caplog.at_level("WARNING"):
            kml = eudr.coords_to_kml([{"name": "NoCoords"}])
        assert "Skipping plot with no coordinates" in caplog.text
        assert "NoCoords" not in kml  # skipped plot contributes no placemark

    def test_default_doc_name(self):
        kml = eudr.coords_to_kml([])
        assert "<name>EUDR Plots</name>" in kml


class TestWorldcoverQuery:
    def test_query_worldcover_no_items(self):
        client = _Client([_Resp({"features": []})])
        result = eudr.query_worldcover([0, 0, 1, 1], http_client=client)
        assert result["available"] is False
        assert result["reason"] == "no_worldcover_data"

    def test_query_worldcover_missing_map_asset(self):
        client = _Client([_Resp({"features": [{"id": "item-1", "assets": {}}]})])
        result = eudr.query_worldcover([0, 0, 1, 1], http_client=client)
        assert result["reason"] == "no_map_asset"

    def test_query_worldcover_success(self, monkeypatch: pytest.MonkeyPatch):
        client = _Client(
            [_Resp({"features": [{"id": "item-1", "assets": {"map": {"href": "h"}}}]})]
        )
        monkeypatch.setattr(
            eudr,
            "_sample_worldcover_cog",
            lambda _href, _bbox: {"total_pixels": 2, "classes": [], "dominant_class": None},
        )
        result = eudr.query_worldcover([0, 0, 2, 2], http_client=client)
        assert result["available"] is True
        assert result["item_id"] == "item-1"
        assert result["center"] == {"lon": 1.0, "lat": 1.0}

    def test_query_worldcover_exception_returns_query_error(self):
        client = _Client([_Resp({}, error=RuntimeError("fail"))])
        result = eudr.query_worldcover([0, 0, 1, 1], http_client=client)
        assert result == {"available": False, "reason": "query_error", "bbox": [0, 0, 1, 1]}

    def test_query_worldcover_constructs_http_client_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        client = _Client([_Resp({"features": []})])
        monkeypatch.setattr(eudr.httpx, "Client", lambda **_kwargs: _ContextClient(client))
        result = eudr.query_worldcover([0, 0, 1, 1])
        assert result["reason"] == "no_worldcover_data"


class TestParseWdpaArea:
    def test_extracts_flat_fields(self):
        area = {
            "id": 555,
            "attributes": {
                "name": "Reserve A",
                "designation": {"name": "National Park"},
                "iucn_category": {"name": "II"},
                "countries": [{"name": "Brazil"}],
                "legal_status": "Designated",
            },
        }
        result = eudr._parse_wdpa_area(area)
        assert result == {
            "name": "Reserve A",
            "wdpa_id": 555,
            "designation": "National Park",
            "iucn_category": "II",
            "status": "Designated",
            "country": "Brazil",
        }

    def test_missing_nested_fields_default_to_empty(self):
        result = eudr._parse_wdpa_area({"id": 1, "attributes": {}})
        assert result["name"] == "Unknown"
        assert result["designation"] == ""
        assert result["iucn_category"] == ""
        assert result["country"] == ""

    def test_non_dict_designation_and_iucn_do_not_raise(self):
        area = {"attributes": {"designation": "not-a-dict", "iucn_category": None}}
        result = eudr._parse_wdpa_area(area)
        assert result["designation"] == ""
        assert result["iucn_category"] == ""


class TestCheckWdpaOverlap:
    def test_no_token_configured_skips_check(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("WDPA_API_TOKEN", raising=False)
        result = eudr.check_wdpa_overlap(0.0, 0.0, token="")
        assert result == {"checked": False, "reason": "no_api_token", "protected_areas": []}

    def test_success_with_protected_areas_found(self, monkeypatch: pytest.MonkeyPatch):
        response = _Resp(
            {
                "protected_areas": [
                    {"id": 1, "attributes": {"name": "Park A", "countries": [{"name": "Peru"}]}},
                ]
            }
        )
        monkeypatch.setattr(eudr.httpx, "get", lambda *_a, **_kw: response)

        result = eudr.check_wdpa_overlap(-70.0, -10.0, token="tok")
        assert result["checked"] is True
        assert result["is_protected"] is True
        assert result["protected_areas"][0]["name"] == "Park A"
        assert result["query_point"] == {"lon": -70.0, "lat": -10.0}

    def test_success_with_no_protected_areas(self, monkeypatch: pytest.MonkeyPatch):
        response = _Resp({"protected_areas": []})
        monkeypatch.setattr(eudr.httpx, "get", lambda *_a, **_kw: response)

        result = eudr.check_wdpa_overlap(0.0, 0.0, token="tok")
        assert result["checked"] is True
        assert result["is_protected"] is False

    def test_api_error_returns_unchecked(self, monkeypatch: pytest.MonkeyPatch):
        def _raise(*_a, **_kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(eudr.httpx, "get", _raise)

        result = eudr.check_wdpa_overlap(0.0, 0.0, token="tok")
        assert result["checked"] is False
        assert result["reason"] == "api_error"
        assert result["query_point"] == {"lon": 0.0, "lat": 0.0}

    def test_falls_back_to_env_var_token(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("WDPA_API_TOKEN", "env-token")
        response = _Resp({"protected_areas": []})
        monkeypatch.setattr(eudr.httpx, "get", lambda *_a, **_kw: response)

        result = eudr.check_wdpa_overlap(0.0, 0.0)
        assert result["checked"] is True


class TestLulcHelpers:
    def test_analyse_tree_cover_trend_branches(self):
        assert eudr._analyse_tree_cover_trend({"2022": {"tree_pct": 50.0}}) == (
            False,
            "insufficient_data",
        )
        assert eudr._analyse_tree_cover_trend(
            {"2021": {"tree_pct": 20.0}, "2022": {"tree_pct": 30.5}}
        ) == (True, "increasing")
        assert eudr._analyse_tree_cover_trend(
            {"2021": {"tree_pct": 80.0}, "2022": {"tree_pct": 70.0}}
        ) == (False, "declining")

    def test_query_lulc_annual_no_data(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(eudr, "_fetch_lulc_years", lambda *_args: {})
        result = eudr.query_lulc_annual([0, 0, 1, 1], http_client=SimpleNamespace())
        assert result["reason"] == "no_lulc_data"

    def test_query_lulc_annual_success_and_default_years(self, monkeypatch: pytest.MonkeyPatch):
        seen_years = []

        def _fake_fetch(_client, _url, _bbox, years):
            seen_years.extend(years)
            return {"2021": {"tree_pct": 90.0, "dominant": "Trees", "class_breakdown": {}}}

        monkeypatch.setattr(eudr, "_fetch_lulc_years", _fake_fetch)
        result = eudr.query_lulc_annual([0, 0, 1, 1], http_client=SimpleNamespace())

        assert result["available"] is True
        assert result["collection"] == "io-lulc-annual-v02"
        assert seen_years == list(range(2017, 2024))

    def test_fetch_lulc_years_covers_skip_and_exception_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls = {
            2021: _Resp({"features": []}),
            2022: _Resp({"features": [{"assets": {}}]}),
            2023: _Resp({}, error=RuntimeError("boom")),
        }
        sample_calls = []

        class _YearClient:
            def post(self, _url, json):
                year = int(json["datetime"][0:4])
                return calls[year]

        monkeypatch.setattr(
            eudr,
            "_sample_classification_cog",
            lambda *_args: (
                sample_calls.append(_args)
                or {"dominant_class": "Trees", "classes": [{"code": 4, "area_pct": 77.7}]}
            ),
        )

        result = eudr._fetch_lulc_years(
            _YearClient(), "https://stac", [0, 0, 1, 1], [2021, 2022, 2023]
        )
        assert result == {}
        assert sample_calls == []


class TestAlosQuery:
    def test_query_alos_no_data_and_missing_asset(self):
        no_data = _Client([_Resp({"features": []})])
        assert eudr.query_alos_fnf([0, 0, 1, 1], http_client=no_data)["reason"] == "no_alos_data"

        missing_asset = _Client([_Resp({"features": [{"id": "x", "assets": {}}]})])
        assert (
            eudr.query_alos_fnf([0, 0, 1, 1], http_client=missing_asset)["reason"]
            == "no_classification_asset"
        )

    def test_query_alos_success_and_exception(self, monkeypatch: pytest.MonkeyPatch):
        success = _Client(
            [
                _Resp(
                    {
                        "features": [
                            {
                                "id": "alos1",
                                "assets": {"C": {"href": "h"}},
                                "properties": {"datetime": "2023-01-01T00:00:00Z"},
                            }
                        ]
                    }
                )
            ]
        )
        monkeypatch.setattr(
            eudr,
            "_sample_classification_cog",
            lambda *_args: {
                "dominant_class": "Forest (>90% canopy)",
                "classes": [
                    {"code": 1, "area_pct": 70.0},
                    {"code": 2, "area_pct": 20.0},
                    {"code": 3, "area_pct": 5.0},
                    {"code": 4, "area_pct": 5.0},
                ],
            },
        )
        result = eudr.query_alos_fnf([0, 0, 1, 1], http_client=success)
        assert result["available"] is True
        assert result["year"] == 2023
        assert result["forest_pct"] == 90.0

        error = _Client([_Resp({}, error=RuntimeError("fail"))])
        assert eudr.query_alos_fnf([0, 0, 1, 1], http_client=error)["reason"] == "query_error"

    def test_query_alos_constructs_http_client_when_missing(self, monkeypatch: pytest.MonkeyPatch):
        client = _Client([_Resp({"features": []})])
        monkeypatch.setattr(eudr.httpx, "Client", lambda **_kwargs: _ContextClient(client))
        result = eudr.query_alos_fnf([0, 0, 1, 1])
        assert result["reason"] == "no_alos_data"


class _FakeRasterDataset:
    """Minimal stand-in for a rasterio dataset context manager.

    A real north-up affine transform (not identity) keeps rasterio's own
    windowing math (from_bounds/Window.intersection, both real, unmocked)
    happy — only rasterio.open + planetary_computer.sign_url are faked.
    """

    def __init__(self, data, width=10, height=10):
        from rasterio.transform import Affine

        self._data = data
        self.width = width
        self.height = height
        self.transform = Affine(0.1, 0, 0, 0, -0.1, 1)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _band, window=None):
        return self._data


def _patch_cog_read(monkeypatch: pytest.MonkeyPatch, data):
    import planetary_computer
    import rasterio

    monkeypatch.setattr(rasterio, "open", lambda _href: _FakeRasterDataset(data))
    monkeypatch.setattr(planetary_computer, "sign_url", lambda href: href)


class TestSampleWorldcoverCog:
    """Coverage for _sample_worldcover_cog's raster-sampling branches."""

    def test_returns_class_breakdown_sorted_by_pixel_count(self, monkeypatch: pytest.MonkeyPatch):
        import numpy as np

        data = np.array([[10, 10, 10, 40, 40, 0]], dtype="uint8")
        _patch_cog_read(monkeypatch, data)

        result = eudr._sample_worldcover_cog("https://example.com/cog.tif", [0, 0, 1, 1])
        assert result["total_pixels"] == 6
        # nodata (code 0) excluded from the area_pct denominator: 5 valid pixels
        assert result["classes"][0]["code"] == 10
        assert result["classes"][0]["label"] == "Tree cover"
        assert result["classes"][0]["pixel_count"] == 3
        assert result["classes"][0]["area_pct"] == 60.0
        assert result["classes"][1]["code"] == 40
        assert result["dominant_class"] == "Tree cover"

    def test_empty_window_returns_zero_pixels(self, monkeypatch: pytest.MonkeyPatch):
        import numpy as np

        _patch_cog_read(monkeypatch, np.array([], dtype="uint8"))

        result = eudr._sample_worldcover_cog("https://example.com/cog.tif", [0, 0, 1, 1])
        assert result == {"total_pixels": 0, "classes": [], "dominant_class": None}

    def test_all_nodata_returns_empty_classes(self, monkeypatch: pytest.MonkeyPatch):
        import numpy as np

        _patch_cog_read(monkeypatch, np.array([[0, 0, 0]], dtype="uint8"))

        result = eudr._sample_worldcover_cog("https://example.com/cog.tif", [0, 0, 1, 1])
        assert result["total_pixels"] == 3
        assert result["classes"] == []
        assert result["dominant_class"] is None


class TestSampleClassificationCog:
    """Coverage for _sample_classification_cog — the generic COG sampler used by
    IO LULC and ALOS FNF (mirrors _sample_worldcover_cog's structure)."""

    def test_returns_class_breakdown_with_custom_labels(self, monkeypatch: pytest.MonkeyPatch):
        import numpy as np

        data = np.array([[1, 1, 2, 0]], dtype="uint8")
        _patch_cog_read(monkeypatch, data)

        labels = {1: "Forest", 2: "Non-forest"}
        result = eudr._sample_classification_cog(
            "https://example.com/cog.tif", [0, 0, 1, 1], labels
        )
        assert result["total_pixels"] == 4
        assert result["classes"][0]["label"] == "Forest"
        assert result["classes"][0]["pixel_count"] == 2
        assert result["dominant_class"] == "Forest"

    def test_unknown_code_falls_back_to_generic_label(self, monkeypatch: pytest.MonkeyPatch):
        import numpy as np

        _patch_cog_read(monkeypatch, np.array([[99]], dtype="uint8"))

        result = eudr._sample_classification_cog("https://example.com/cog.tif", [0, 0, 1, 1], {})
        assert result["classes"][0]["label"] == "Unknown (99)"


class TestStubLulcAnnual:
    """Coverage for _stub_lulc_annual — the synthetic IO LULC fallback."""

    def test_default_years_and_declining_trend_shape(self):
        result = eudr._stub_lulc_annual([0, 0, 1, 1])
        assert result["available"] is True
        assert result["collection"] == "io-lulc-annual-v02"
        assert set(result["years"]) == {"2020", "2021", "2022", "2023"}
        # tree_pct declines slightly year over year (85.0 - (year-2020)*0.5)
        assert result["years"]["2020"]["tree_pct"] == 85.0
        assert result["years"]["2023"]["tree_pct"] == 83.5
        assert result["years"]["2020"]["dominant"] == "Trees"

    def test_custom_years(self):
        result = eudr._stub_lulc_annual([0, 0, 1, 1], years=[2018, 2019])
        assert set(result["years"]) == {"2018", "2019"}
        assert result["bbox"] == [0, 0, 1, 1]
