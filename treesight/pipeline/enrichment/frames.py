"""Frame planning — season/year matrix and NAIP detection."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

# Seasonal definitions matching the frontend
SEASONS: list[dict[str, Any]] = [
    {"key": "winter", "label": "Winter", "months": [12, 1, 2]},
    {"key": "spring", "label": "Spring", "months": [3, 4, 5]},
    {"key": "summer", "label": "Summer", "months": [6, 7, 8]},
    {"key": "autumn", "label": "Autumn", "months": [9, 10, 11]},
]

# Monthly definitions for monthly cadence (Pro/Team tiers)
MONTHS: list[dict[str, Any]] = [
    {"key": f"m{m:02d}", "label": f"Month {m}", "month": m} for m in range(1, 13)
]

SEASONAL_YEARS = list(range(2018, date.today().year + 1))
LANDSAT_YEARS = list(range(2013, 2018))  # Pre-Sentinel-2 historical baseline
NAIP_ONLY_YEARS = [2012, 2014, 2016]
# NAIP imagery releases lag ~2 years; update this set when new vintages
# are published on Planetary Computer (typically even-numbered years).
NAIP_SUMMERS = {
    "2012-summer",
    "2014-summer",
    "2016-summer",
    "2018-summer",
    "2020-summer",
    "2022-summer",
}


def _aoi_has_naip(coords: list[list[float]]) -> bool:
    """Check if all coords fall within CONUS (NAIP coverage).

    Coordinates are ``[lon, lat]`` pairs per project convention
    (see :pymod:`treesight.constants`).
    """
    for c in coords:
        lon, lat = c[0], c[1]
        if lat < 24 or lat > 50 or lon < -125 or lon > -66:
            return False
    return True


def _season_window(year: int, season: dict[str, Any]) -> dict[str, str]:
    """Compute date window for a season/year, matching frontend logic."""
    if season["key"] == "winter":
        _, feb_end = calendar.monthrange(year, 2)
        return {"start": f"{year - 1}-12-01", "end": f"{year}-02-{feb_end}"}
    m0 = season["months"][0]
    m2 = season["months"][2]
    start = f"{year}-{m0:02d}-01"
    _, end_day = calendar.monthrange(year, m2)
    end = f"{year}-{m2:02d}-{end_day}"
    return {"start": start, "end": end}


def _month_window(year: int, month: int) -> dict[str, str]:
    """Compute date window for a single calendar month."""
    start = date(year, month, 1)
    # First day of next month minus 1 day = last day of this month
    end = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _build_landsat_frames() -> list[dict[str, Any]]:
    """Generate seasonal frames for Landsat C2 L2 historical baseline (2013-2017)."""
    frames: list[dict[str, Any]] = []
    for yr in LANDSAT_YEARS:
        for s in SEASONS:
            w = _season_window(yr, s)
            frames.append(
                {
                    "year": yr,
                    "season": s["key"],
                    "start": w["start"],
                    "end": w["end"],
                    "collection": "landsat-c2-l2",
                    "asset": "red",
                    "is_naip": False,
                }
            )
    return frames


def _build_monthly_frames() -> list[dict[str, Any]]:
    """Generate monthly frames for Pro/Team cadence."""
    frames: list[dict[str, Any]] = []
    for yr in SEASONAL_YEARS:
        for m_def in MONTHS:
            w = _month_window(yr, m_def["month"])
            frames.append(
                {
                    "year": yr,
                    "season": m_def["key"],
                    "start": w["start"],
                    "end": w["end"],
                    "collection": "sentinel-2-l2a",
                    "asset": "visual",
                    "is_naip": False,
                }
            )
    return frames


def _build_seasonal_frames(has_naip: bool) -> list[dict[str, Any]]:
    """Generate seasonal frames (4/year) with optional NAIP overlay."""
    frames: list[dict[str, Any]] = []
    for yr in SEASONAL_YEARS:
        for s in SEASONS:
            w = _season_window(yr, s)
            naip_key = f"{yr}-{s['key']}"
            use_naip = has_naip and naip_key in NAIP_SUMMERS
            frames.append(
                {
                    "year": yr,
                    "season": s["key"],
                    "start": w["start"],
                    "end": w["end"],
                    "collection": "naip" if use_naip else "sentinel-2-l2a",
                    "asset": "image" if use_naip else "visual",
                    "is_naip": use_naip,
                }
            )
    return frames


def build_frame_plan(
    coords: list[list[float]],
    *,
    date_start: str | None = None,
    date_end: str | None = None,
    cadence: str = "maximum",
    max_history_years: int | None = None,
) -> list[dict[str, Any]]:
    """Build the ordered frame list — mirrors frontend buildFramePlan().

    Parameters
    ----------
    date_start : str, optional
        ISO date (``YYYY-MM-DD``).  Frames ending before this date are excluded.
    date_end : str, optional
        ISO date (``YYYY-MM-DD``).  Frames starting after this date are excluded.
    cadence : str
        Temporal resolution: ``seasonal`` (4/year), ``monthly`` (12/year),
        or ``maximum`` (all available, default).
    max_history_years : int, optional
        Cap the date range to the most recent N years.  ``None`` means
        no cap (full history).
    """
    # Apply max_history_years cap
    if max_history_years is not None and not date_start:
        cutoff_year = date.today().year - max_history_years
        date_start = f"{cutoff_year}-01-01"

    frames: list[dict[str, Any]] = []
    has_naip = _aoi_has_naip(coords)

    if has_naip and cadence != "monthly":
        summer = SEASONS[2]
        for yr in NAIP_ONLY_YEARS:
            w = _season_window(yr, summer)
            frames.append(
                {
                    "year": yr,
                    "season": "summer",
                    "start": w["start"],
                    "end": w["end"],
                    "collection": "naip",
                    "asset": "image",
                    "is_naip": True,
                }
            )

    if cadence == "monthly":
        frames.extend(_build_monthly_frames())
    else:
        frames.extend(_build_landsat_frames())
        frames.extend(_build_seasonal_frames(has_naip))

    # Apply date range filter
    if date_start or date_end:
        frames = [
            f
            for f in frames
            if not (date_start and f["end"] < date_start)
            and not (date_end and f["start"] > date_end)
        ]

    return frames
