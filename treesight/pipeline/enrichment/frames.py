"""Frame planning — season/year matrix and NAIP detection."""

from __future__ import annotations

from typing import Any

# Seasonal definitions matching the frontend
SEASONS: list[dict[str, Any]] = [
    {"key": "winter", "label": "Winter", "months": [12, 1, 2]},
    {"key": "spring", "label": "Spring", "months": [3, 4, 5]},
    {"key": "summer", "label": "Summer", "months": [6, 7, 8]},
    {"key": "autumn", "label": "Autumn", "months": [9, 10, 11]},
]
SEASONAL_YEARS = list(range(2018, 2027))
NAIP_ONLY_YEARS = [2012, 2014, 2016]
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
        return {"start": f"{year - 1}-12-01", "end": f"{year}-02-28"}
    m0 = season["months"][0]
    m2 = season["months"][2]
    start = f"{year}-{m0:02d}-01"
    # Last day of end month
    if m2 == 2:
        end_day = 28
    elif m2 in (4, 6, 9, 11):
        end_day = 30
    else:
        end_day = 31
    end = f"{year}-{m2:02d}-{end_day}"
    return {"start": start, "end": end}


def build_frame_plan(coords: list[list[float]]) -> list[dict[str, Any]]:
    """Build the ordered frame list — mirrors frontend buildFramePlan()."""
    frames: list[dict[str, Any]] = []
    has_naip = _aoi_has_naip(coords)
    summer = SEASONS[2]

    if has_naip:
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
