"""Tests for treesight.pipeline.enrichment.flood — flood event detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from treesight.pipeline.enrichment.flood import (
    _is_uk,
    _is_us,
    fetch_ea_floods,
    fetch_flood_events,
    fetch_usgs_streamflow,
)

# ---------------------------------------------------------------------------
# Geolocation routing
# ---------------------------------------------------------------------------


class TestGeoRouting:
    def test_uk_centroid(self):
        assert _is_uk(52.0, -1.5) is True

    def test_us_centroid(self):
        assert _is_us(40.0, -100.0) is True

    def test_australia_neither(self):
        assert _is_uk(-33.0, 151.0) is False
        assert _is_us(-33.0, 151.0) is False


# ---------------------------------------------------------------------------
# fetch_ea_floods
# ---------------------------------------------------------------------------


class TestFetchEaFloods:
    def test_parses_ea_response(self):
        mock_json = {
            "items": [
                {
                    "severityLevel": "Warning",
                    "description": "River Soar near Mountsorrel",
                    "eaAreaName": "East Midlands",
                    "message": "Flooding expected",
                    "timeRaised": "2024-01-15T10:00:00Z",
                },
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_json
        mock_resp.raise_for_status = MagicMock()

        with patch("treesight.pipeline.enrichment.flood.httpx.get", return_value=mock_resp):
            events = fetch_ea_floods(52.0, -1.5, 53.0, -0.5)

        assert len(events) == 1
        assert events[0]["source"] == "ea"
        assert events[0]["severity"] == "Warning"

    def test_returns_error_on_failure(self):
        with patch(
            "treesight.pipeline.enrichment.flood.httpx.get",
            side_effect=Exception("timeout"),
        ):
            events = fetch_ea_floods(52.0, -1.5, 53.0, -0.5)
        assert events == []


# ---------------------------------------------------------------------------
# fetch_usgs_streamflow
# ---------------------------------------------------------------------------


class TestFetchUsgsStreamflow:
    def test_parses_usgs_response(self):
        mock_json = {
            "value": {
                "timeSeries": [
                    {
                        "sourceInfo": {
                            "siteName": "Test River",
                            "siteCode": [{"value": "12345"}],
                            "geoLocation": {
                                "geogLocation": {"latitude": 40.0, "longitude": -100.0}
                            },
                        },
                        "values": [
                            {"value": [{"value": "1500", "dateTime": "2024-01-15T10:00:00"}]}
                        ],
                    }
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_json
        mock_resp.raise_for_status = MagicMock()

        with patch("treesight.pipeline.enrichment.flood.httpx.get", return_value=mock_resp):
            events = fetch_usgs_streamflow(39.0, -101.0, 41.0, -99.0)

        assert len(events) == 1
        assert events[0]["source"] == "usgs"
        assert events[0]["site_name"] == "Test River"
        assert events[0]["discharge_cfs"] == 1500.0

    def test_returns_error_on_failure(self):
        with patch(
            "treesight.pipeline.enrichment.flood.httpx.get",
            side_effect=Exception("timeout"),
        ):
            events = fetch_usgs_streamflow(39.0, -101.0, 41.0, -99.0)
        assert events == []


# ---------------------------------------------------------------------------
# fetch_flood_events — routing
# ---------------------------------------------------------------------------


class TestFetchFloodEvents:
    def test_routes_uk_to_ea(self):
        bbox = [[-1.5, 52.0], [-0.5, 52.0], [-0.5, 53.0], [-1.5, 53.0]]
        with patch(
            "treesight.pipeline.enrichment.flood.fetch_ea_floods",
            return_value=[{"source": "ea"}],
        ) as mock_ea:
            result = fetch_flood_events(bbox, center_lat=52.5, center_lon=-1.0)
        assert result["source"] == "ea_flood_monitoring"
        assert result["count"] == 1
        mock_ea.assert_called_once()

    def test_routes_us_to_usgs(self):
        bbox = [[-101.0, 39.0], [-99.0, 39.0], [-99.0, 41.0], [-101.0, 41.0]]
        with patch(
            "treesight.pipeline.enrichment.flood.fetch_usgs_streamflow",
            return_value=[{"source": "usgs"}],
        ) as mock_usgs:
            result = fetch_flood_events(bbox, center_lat=40.0, center_lon=-100.0)
        assert result["source"] == "usgs_nwis"
        assert result["count"] == 1
        mock_usgs.assert_called_once()

    def test_returns_none_for_unsupported_region(self):
        bbox = [[151.0, -34.0], [152.0, -34.0], [152.0, -33.0], [151.0, -33.0]]
        result = fetch_flood_events(bbox, center_lat=-33.5, center_lon=151.5)
        assert result["source"] == "none"
        assert result["count"] == 0
