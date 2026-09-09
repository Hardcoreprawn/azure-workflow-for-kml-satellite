"""Unit tests for treesight.eudr.plots, treesight.eudr.usage, and treesight.eudr.export."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from treesight.analysis.prompts import build_eudr_prompt, build_timelapse_prompt
from treesight.eudr.export import (
    SUMMARY_CSV_FIELDS,
    build_summary_csv,
    summary_rows_from_manifest,
)
from treesight.eudr.plots import sanitise_name, validate_plot
from treesight.eudr.stripe_checkout import (
    build_eudr_checkout_kwargs,
    resolve_eudr_prices,
)
from treesight.eudr.usage import eudr_usage_payload, last_n_month_keys, month_key, parse_iso_datetime

# ---------------------------------------------------------------------------
# treesight.eudr.plots
# ---------------------------------------------------------------------------


class TestSanitiseName:
    def test_strips_special_chars(self):
        assert sanitise_name("Plot <A>") == "Plot A"

    def test_truncates(self):
        assert len(sanitise_name("x" * 200)) == 100

    def test_non_string_returns_empty(self):
        assert sanitise_name(None) == ""  # type: ignore[arg-type]

    def test_allows_safe_chars(self):
        assert sanitise_name("Farm-Block_1.2") == "Farm-Block_1.2"


class TestValidatePlot:
    def test_valid_point(self):
        result = validate_plot(0, {"name": "A", "lon": 2.35, "lat": 48.86})
        assert isinstance(result, dict)
        assert result["lon"] == pytest.approx(2.35)

    def test_valid_polygon(self):
        coords = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
        result = validate_plot(0, {"name": "B", "coordinates": coords})
        assert isinstance(result, dict)
        assert len(result["coordinates"]) == 3

    def test_non_dict_returns_error(self):
        assert isinstance(validate_plot(0, "bad"), str)

    def test_out_of_range_lon(self):
        result = validate_plot(0, {"lon": 200.0, "lat": 48.86})
        assert isinstance(result, str)
        assert "out of range" in result

    def test_polygon_too_few_points(self):
        result = validate_plot(0, {"coordinates": [[0.0, 0.0], [1.0, 0.0]]})
        assert isinstance(result, str)
        assert ">= 3" in result

    def test_missing_coords_returns_error(self):
        result = validate_plot(0, {"name": "missing"})
        assert isinstance(result, str)

    def test_radius_m_parsed(self):
        result = validate_plot(0, {"lon": 2.35, "lat": 48.86, "radius_m": "150"})
        assert isinstance(result, dict)
        assert result["radius_m"] == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# treesight.eudr.usage
# ---------------------------------------------------------------------------


class TestParseIsoDatetime:
    def test_parses_iso_z(self):
        dt = parse_iso_datetime("2024-06-01T10:00:00Z")
        assert dt is not None
        assert dt.year == 2024

    def test_empty_returns_none(self):
        assert parse_iso_datetime("") is None

    def test_invalid_returns_none(self):
        assert parse_iso_datetime("not-a-date") is None


class TestMonthKey:
    def test_formats_correctly(self):
        dt = datetime(2024, 3, 15, tzinfo=UTC)
        assert month_key(dt) == "2024-03"


class TestLastNMonthKeys:
    def test_returns_n_keys(self):
        now = datetime(2024, 6, 1, tzinfo=UTC)
        keys = last_n_month_keys(3, now=now)
        assert len(keys) == 3
        assert keys[-1] == "2024-06"
        assert keys[0] == "2024-04"

    def test_crosses_year_boundary(self):
        now = datetime(2024, 2, 1, tzinfo=UTC)
        keys = last_n_month_keys(3, now=now)
        assert "2023-12" in keys


class TestPromptBuilders:
    def test_timelapse_prompt_includes_context_and_statistics(self):
        prompt, trends = build_timelapse_prompt(
            {
                "aoi_name": "North Field <1>",
                "date_range_start": "2020-01-01",
                "date_range_end": "2023-12-31",
                "latitude": 51.5,
                "longitude": -0.12,
                "ndvi_timeseries": [
                    {"mean": 0.4, "season": "summer", "year": 2022},
                    {"mean": 0.6, "season": "summer", "year": 2023},
                ],
                "weather_timeseries": [
                    {"month": "2022-01", "temperature": 4, "precipitation": 5},
                    {"month": "2023-07", "temperature": 22, "precipitation": 200},
                ],
            }
        )
        assert "Area of Interest: North Field 1" in prompt
        assert "Location: 51.50, -0.12" in prompt
        assert "NDVI Average" in prompt
        assert "Weather data" in prompt
        assert trends["ndvi_trajectory"] == "Improving"

    def test_eudr_prompt_omits_invalid_location(self):
        prompt, trends, post_cutoff = build_eudr_prompt(
            {
                "latitude": "invalid",
                "longitude": "also-invalid",
                "ndvi_timeseries": [
                    {"date": "2021-06-01", "mean": 0.5, "season": "summer", "year": 2021},
                    {"date": "2022-06-01", "mean": 0.4, "season": "summer", "year": 2022},
                ],
                "weather_timeseries": [],
            }
        )
        assert "Location:" not in prompt
        assert trends["ndvi_avg"] == pytest.approx(0.45)
        assert len(post_cutoff) == 2

    def test_eudr_prompt_returns_empty_result_before_cutoff(self):
        assert build_eudr_prompt({"ndvi_timeseries": [{"date": "2020-01-01"}]}) == (None, None, None)


class TestEudrUsagePayload:
    def test_assembles_from_injected_snapshots(self):
        payload = eudr_usage_payload(
            "user-1",
            records=[{"submitted_at": "2024-06-15T10:00:00Z", "aoi_count": 3, "billing_type": "overage"}],
            org={"org_id": "org-1"},
            billing={"period_parcels_used": 12, "included_parcels": 10},
        )
        assert payload["current"]["overageParcels"] == 2
        assert payload["history"][-1]["runs"] in (0, 1)


class TestStripeCheckout:
    def test_resolves_supported_currency(self):
        base_price, metered_price = resolve_eudr_prices("GBP")
        assert base_price is not None
        assert metered_price is not None

    def test_rejects_unsupported_currency(self):
        assert resolve_eudr_prices("JPY") == (None, None)

    def test_builds_subscription_kwargs(self):
        kwargs = build_eudr_checkout_kwargs(
            user_id="user-1",
            org_id="org-1",
            base_price="price-base",
            metered_price="price-metered",
            origin="https://example.test",
            currency="GBP",
        )
        assert kwargs["mode"] == "subscription"
        assert kwargs["line_items"] == [
            {"price": "price-base", "quantity": 1},
            {"price": "price-metered"},
        ]
        assert kwargs["metadata"] == {
            "user_id": "user-1",
            "org_id": "org-1",
            "product": "eudr",
            "currency": "GBP",
        }
        assert kwargs["success_url"] == "https://example.test/eudr/?subscribed=true"
        assert kwargs["cancel_url"] == "https://example.test/eudr/?billing=cancel"


# ---------------------------------------------------------------------------
# treesight.eudr.export
# ---------------------------------------------------------------------------


def _make_manifest(parcels: list[dict[str, Any]]) -> dict[str, Any]:
    return {"per_aoi_enrichment": parcels}


def _make_aoi(name: str, determination: dict | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "area_ha": 1.5,
        "center": {"lat": 51.5, "lon": -0.12},
        "determination": determination
        or {"screening_outcome": "no_signal_detected", "confidence": "high", "flags": []},
    }


class TestSummaryRowsFromManifest:
    def test_returns_row_per_parcel(self):
        manifest = _make_manifest([_make_aoi("Parcel A"), _make_aoi("Parcel B")])
        rows = summary_rows_from_manifest("run-1", "2024-01-01", manifest, None)
        assert len(rows) == 2
        assert rows[0]["parcel_name"] == "Parcel A"
        assert rows[0]["run_id"] == "run-1"

    def test_v2_nested_eudr_determination_takes_precedence(self):
        manifest = _make_manifest(
            [
                {
                    "name": "Parcel A",
                    "area_ha": 1.5,
                    "center": {"lat": 51.5, "lon": -0.12},
                    "determination": {"screening_outcome": "signal_detected", "confidence": "low", "flags": ["wrong"]},
                    "eudr": {
                        "determination": {
                            "screening_outcome": "no_signal_detected",
                            "confidence": "high",
                            "flags": [],
                        }
                    },
                }
            ]
        )

        rows = summary_rows_from_manifest("run-1", "2024-01-01", manifest, None)

        assert rows[0]["determination_status"] == "no_signal_detected"
        assert rows[0]["determination_confidence"] == "high"

    def test_empty_manifest_returns_empty(self):
        rows = summary_rows_from_manifest("run-1", "2024-01-01", {}, None)
        assert rows == []

    def test_overridden_flag_set(self):
        manifest = _make_manifest([_make_aoi("P")])
        record = {"parcel_overrides": {"0": {"reason": "Verified on-site", "reverted": False}}}
        rows = summary_rows_from_manifest("run-1", "2024-01-01", manifest, record)
        assert rows[0]["overridden"] == "yes"
        assert rows[0]["override_reason"] == "Verified on-site"

    def test_note_from_record(self):
        manifest = _make_manifest([_make_aoi("P")])
        record = {"parcel_notes": {"0": "Checked manually"}}
        rows = summary_rows_from_manifest("run-1", "2024-01-01", manifest, record)
        assert rows[0]["note"] == "Checked manually"


class TestBuildSummaryCsv:
    def test_csv_has_header(self):
        csv_str = build_summary_csv([])
        first_line = csv_str.splitlines()[0]
        assert "run_id" in first_line
        assert "parcel_name" in first_line

    def test_csv_row_count(self):
        rows = [
            {f: f"val-{f}" for f in SUMMARY_CSV_FIELDS},
            {f: f"val2-{f}" for f in SUMMARY_CSV_FIELDS},
        ]
        lines = build_summary_csv(rows).splitlines()
        assert len(lines) == 3  # header + 2 data rows
