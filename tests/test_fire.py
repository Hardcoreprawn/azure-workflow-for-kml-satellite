"""Tests for treesight.pipeline.enrichment.fire — fire hotspot detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from treesight.pipeline.enrichment.fire import (
    _parse_firms_csv,
    fetch_fire_hotspots,
)

# ---------------------------------------------------------------------------
# _parse_firms_csv
# ---------------------------------------------------------------------------


class TestParseFirmsCsv:
    def test_parses_valid_csv(self):
        csv = (
            "latitude,longitude,acq_date,acq_time,confidence,frp,bright_ti4\n"
            "52.1,-1.2,2024-01-15,0600,high,12.5,310.2\n"
            "52.2,-1.3,2024-01-15,0630,nominal,8.1,305.0\n"
        )
        events = _parse_firms_csv(csv)
        assert len(events) == 2
        assert events[0]["latitude"] == 52.1
        assert events[0]["frp"] == 12.5
        assert events[1]["confidence"] == "nominal"

    def test_empty_csv(self):
        assert _parse_firms_csv("") == []
        assert _parse_firms_csv("latitude,longitude\n") == []

    def test_skips_malformed_rows(self):
        csv = (
            "latitude,longitude,acq_date,acq_time,confidence,frp,bright_ti4\n"
            "52.1,-1.2,2024-01-15,0600,high,12.5,310.2\n"
            "bad,row\n"
        )
        events = _parse_firms_csv(csv)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# fetch_fire_hotspots
# ---------------------------------------------------------------------------


class TestFetchFireHotspots:
    def test_disabled_when_no_api_key(self):
        with patch("treesight.pipeline.enrichment.fire.FIRMS_API_KEY", ""):
            result = fetch_fire_hotspots([[-1.5, 52.0], [-0.5, 53.0]])
        assert result["source"] == "firms_disabled"
        assert result["count"] == 0

    def test_fetches_with_api_key(self):
        csv_response = (
            "latitude,longitude,acq_date,acq_time,confidence,frp,bright_ti4\n"
            "52.1,-1.2,2024-01-15,0600,high,12.5,310.2\n"
        )
        mock_resp = MagicMock()
        mock_resp.text = csv_response
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("treesight.pipeline.enrichment.fire.FIRMS_API_KEY", "test-key"),
            patch("treesight.pipeline.enrichment.fire.httpx.get", return_value=mock_resp),
        ):
            result = fetch_fire_hotspots([[-1.5, 52.0], [-0.5, 53.0]])

        assert result["source"] == "firms_viirs"
        assert result["count"] == 1
        assert result["events"][0]["latitude"] == 52.1

    def test_returns_error_on_failure(self):
        with (
            patch("treesight.pipeline.enrichment.fire.FIRMS_API_KEY", "test-key"),
            patch(
                "treesight.pipeline.enrichment.fire.httpx.get",
                side_effect=Exception("timeout"),
            ),
        ):
            result = fetch_fire_hotspots([[-1.5, 52.0], [-0.5, 53.0]])
        assert result["source"] == "firms_error"
        assert result["count"] == 0
