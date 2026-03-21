"""Historical weather data from Open-Meteo."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

OPEN_METEO_API = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    """Fetch historical weather from Open-Meteo and return structured data."""
    url = (
        f"{OPEN_METEO_API}"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_mean,precipitation_sum"
        f"&timezone=auto"
    )
    try:
        r = httpx.get(url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        r.raise_for_status()
        d = r.json()
        daily = d.get("daily", {})
        return {
            "dates": daily.get("time", []),
            "temp": daily.get("temperature_2m_mean", []),
            "precip": daily.get("precipitation_sum", []),
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return None


def aggregate_weather_monthly(weather: dict[str, Any]) -> dict[str, Any]:
    """Aggregate daily weather into monthly averages (mirrors frontend)."""
    dates = weather.get("dates", [])
    temps = weather.get("temp", [])
    precips = weather.get("precip", [])

    months: dict[str, dict[str, Any]] = {}
    for i, date in enumerate(dates):
        key = date[:7]  # YYYY-MM
        if key not in months:
            months[key] = {"temp": [], "precip": 0.0}
        if i < len(temps) and temps[i] is not None:
            months[key]["temp"].append(temps[i])
        if i < len(precips) and precips[i] is not None:
            months[key]["precip"] += precips[i]

    keys = sorted(months.keys())
    return {
        "labels": keys,
        "temp": [
            round(sum(months[k]["temp"]) / len(months[k]["temp"]), 1) if months[k]["temp"] else None
            for k in keys
        ],
        "precip": [round(months[k]["precip"], 1) for k in keys],
    }
