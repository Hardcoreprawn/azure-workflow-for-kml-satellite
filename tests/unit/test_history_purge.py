"""Tests for orchestration history purge policy logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kml_satellite.orchestrators.history_purge import (
    DEFAULT_PURGE_STATUSES,
    DEFAULT_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    build_purge_plan,
    parse_purge_statuses,
    parse_retention_days,
)


def test_parse_retention_days_default_for_missing() -> None:
    assert parse_retention_days(None) == DEFAULT_RETENTION_DAYS
    assert parse_retention_days("") == DEFAULT_RETENTION_DAYS


def test_parse_retention_days_default_for_invalid() -> None:
    assert parse_retention_days("abc") == DEFAULT_RETENTION_DAYS
    assert parse_retention_days("0") == DEFAULT_RETENTION_DAYS
    assert parse_retention_days("-7") == DEFAULT_RETENTION_DAYS


def test_parse_retention_days_clamps_high_values() -> None:
    assert parse_retention_days("99999") == MAX_RETENTION_DAYS


def test_parse_retention_days_accepts_valid() -> None:
    assert parse_retention_days("30") == 30


def test_parse_purge_statuses_default_when_missing() -> None:
    assert parse_purge_statuses(None) == list(DEFAULT_PURGE_STATUSES)
    assert parse_purge_statuses("") == list(DEFAULT_PURGE_STATUSES)


def test_parse_purge_statuses_filters_and_deduplicates() -> None:
    statuses = parse_purge_statuses("completed, FAILED,unknown, terminated ,failed")
    assert statuses == ["Completed", "Failed", "Terminated"]


def test_parse_purge_statuses_falls_back_if_all_invalid() -> None:
    assert parse_purge_statuses("wat, nope") == list(DEFAULT_PURGE_STATUSES)


def test_build_purge_plan_constructs_expected_window() -> None:
    now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)
    plan = build_purge_plan(
        now_utc=now,
        retention_days_raw="10",
        statuses_raw="Completed,Failed",
    )

    assert plan.retention_days == 10
    assert plan.created_time_from == datetime(1970, 1, 1, tzinfo=UTC)
    assert plan.created_time_to == now - timedelta(days=10)
    assert plan.runtime_statuses == ["Completed", "Failed"]
