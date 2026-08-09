"""Additional EUDR query-path tests for coverage hardening."""

from __future__ import annotations

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

        class _YearClient:
            def post(self, _url, json):
                year = int(json["datetime"][0:4])
                return calls[year]

        monkeypatch.setattr(
            eudr,
            "_sample_classification_cog",
            lambda *_args: {"dominant_class": "Trees", "classes": [{"code": 4, "area_pct": 77.7}]},
        )

        result = eudr._fetch_lulc_years(
            _YearClient(), "https://stac", [0, 0, 1, 1], [2021, 2022, 2023]
        )
        assert result == {}


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
