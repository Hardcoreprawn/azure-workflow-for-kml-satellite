"""Unit tests for treesight.eudr.plots, treesight.eudr.usage, and treesight.eudr.export."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from treesight.eudr.export import SUMMARY_CSV_FIELDS, build_summary_csv, summary_rows_from_manifest
from treesight.eudr.plots import sanitise_name, validate_plot
from treesight.eudr.usage import last_n_month_keys, month_key, parse_iso_datetime


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
        "determination": determination or {"screening_outcome": "no_signal_detected", "confidence": "high", "flags": []},
    }


class TestSummaryRowsFromManifest:
    def test_returns_row_per_parcel(self):
        manifest = _make_manifest([_make_aoi("Parcel A"), _make_aoi("Parcel B")])
        rows = summary_rows_from_manifest("run-1", "2024-01-01", manifest, None)
        assert len(rows) == 2
        assert rows[0]["parcel_name"] == "Parcel A"
        assert rows[0]["run_id"] == "run-1"

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
