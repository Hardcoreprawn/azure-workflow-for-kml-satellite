"""Satellite NDVI and weather trend calculations.

Pure functions: no I/O, no Azure Functions dependency.  All functions here
are unit-testable in isolation.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date
from numbers import Real
from typing import Any, TypeGuard

from treesight.constants import EUDR_CUTOFF_DATE

_EUDR_CUTOFF_DAY = date.fromisoformat(EUDR_CUTOFF_DATE)

# ---------------------------------------------------------------------------
# Prompt-injection sanitisation
# ---------------------------------------------------------------------------

# Strip anything that isn't alphanumeric, whitespace, hyphens, periods,
# commas, or parentheses.
_PROMPT_SAFE_RE = re.compile(r"[^A-Za-z0-9\s\-.,()]+")
_MAX_PROMPT_FIELD_LEN = 200


def is_valid_ndvi_mean(value: Any) -> TypeGuard[Real]:
    """Return whether a mean is finite and within the physical NDVI range."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        numeric_value = float(value)
    except OverflowError:
        return False
    return math.isfinite(numeric_value) and -1.0 <= numeric_value <= 1.0


def is_valid_ndvi_delta(value: Any) -> TypeGuard[Real]:
    """Return whether a change between two physical NDVI values is valid."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        numeric_value = float(value)
    except OverflowError:
        return False
    return math.isfinite(numeric_value) and -2.0 <= numeric_value <= 2.0


def is_valid_year(value: Any) -> TypeGuard[Real]:
    """Return whether a value is a finite integral year."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        numeric_value = float(value)
    except OverflowError:
        return False
    return math.isfinite(numeric_value) and numeric_value.is_integer()


def is_after_eudr_cutoff(date_value: Any, year_value: Any) -> bool:
    """Prefer an explicit ISO date; use an integral year only when date is absent."""
    if isinstance(date_value, str):
        try:
            observed_day = date.fromisoformat(date_value[:10])
        except ValueError:
            return False
        return observed_day > _EUDR_CUTOFF_DAY
    return is_valid_year(year_value) and float(year_value) > _EUDR_CUTOFF_DAY.year


def is_valid_ndvi_stats(value: Any) -> TypeGuard[dict[str, Any]]:
    """Return whether the available summary statistics are physically valid."""
    if not isinstance(value, dict) or not is_valid_ndvi_mean(value.get("mean")):
        return False

    mean = float(value["mean"])
    minimum = value.get("min")
    maximum = value.get("max")
    median = value.get("median")
    standard_deviation = value.get("std")

    for statistic in (minimum, maximum, median):
        if statistic is not None and not is_valid_ndvi_mean(statistic):
            return False
    if minimum is not None and float(minimum) > mean:
        return False
    if maximum is not None and float(maximum) < mean:
        return False
    if minimum is not None and maximum is not None and float(minimum) > float(maximum):
        return False
    if median is not None and minimum is not None and float(median) < float(minimum):
        return False
    if median is not None and maximum is not None and float(median) > float(maximum):
        return False
    if standard_deviation is not None:
        if not is_valid_ndvi_mean(standard_deviation) or float(standard_deviation) < 0.0:
            return False
        if minimum is not None and maximum is not None:
            maximum_possible_std = (float(maximum) - float(minimum)) / 2.0
            if float(standard_deviation) > maximum_possible_std + 0.0001:
                return False
    return True


def sanitise_for_prompt(value: str) -> str:
    """Sanitise a user-supplied string before embedding it in an LLM prompt."""
    if not isinstance(value, str):
        return ""
    cleaned = _PROMPT_SAFE_RE.sub("", value)
    return cleaned.strip()[:_MAX_PROMPT_FIELD_LEN]


# ---------------------------------------------------------------------------
# AI response helpers
# ---------------------------------------------------------------------------


def default_analysis(text: str) -> dict[str, Any]:
    """Create a default analysis structure from fallback text."""
    return {
        "observations": [
            {
                "category": "analysis",
                "severity": "normal",
                "description": text[:150],
                "recommendation": "Review full analysis above",
            }
        ],
        "summary": text[:200],
        "score": 0.5,
    }


# ---------------------------------------------------------------------------
# Trend statistics
# ---------------------------------------------------------------------------


def calculate_trends(
    ndvi_series: list[dict[str, Any]],
    weather_series: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate statistical trends from timeseries data.

    Handles seasonal NDVI variation correctly — compares same-season values
    year-over-year rather than sequential frames, and uses actual month
    labels for weather analysis.
    """
    trends: dict[str, Any] = {}

    if ndvi_series:
        ndvi_means: list[float] = []
        for entry in ndvi_series:
            if is_valid_ndvi_stats(entry):
                ndvi_means.append(float(entry["mean"]))

        if len(ndvi_means) >= 2:
            trends["ndvi_avg"] = round(sum(ndvi_means) / len(ndvi_means), 4)
            trends["ndvi_max_val"] = round(max(ndvi_means), 4)
            trends["ndvi_min_val"] = round(min(ndvi_means), 4)

            trends["ndvi_std_dev"] = round(statistics.pstdev(ndvi_means), 4)
            trends["ndvi_volatility"] = (
                "High" if trends["ndvi_std_dev"] > 0.15 else "Moderate" if trends["ndvi_std_dev"] > 0.08 else "Low"
            )

        # --- Year-over-year same-season comparison ---
        season_bins: dict[str, list[tuple[int, float]]] = {}
        for s in ndvi_series:
            season_key = s.get("season")
            year = s.get("year")
            if is_valid_ndvi_stats(s) and season_key and is_valid_year(year):
                season_bins.setdefault(season_key, []).append((int(float(year)), float(s["mean"])))

        yoy_changes: list[float] = []
        events: list[str] = []
        for season_key, pairs in sorted(season_bins.items()):
            pairs.sort(key=lambda p: p[0])
            if len(pairs) >= 2:
                first_val = pairs[0][1]
                last_val = pairs[-1][1]
                yoy_changes.append(last_val - first_val)

                for idx in range(1, len(pairs)):
                    delta = pairs[idx][1] - pairs[idx - 1][1]
                    if abs(delta) > 0.1:
                        direction = "recovery" if delta > 0 else "decline"
                        events.append(
                            f"{season_key.capitalize()} {pairs[idx][0]}: "
                            f"NDVI {direction} of {delta:+.3f} vs {pairs[idx - 1][0]}"
                        )

        if yoy_changes:
            trends["ndvi_yoy_avg_change"] = round(sum(yoy_changes) / len(yoy_changes), 4)
            trends["ndvi_trajectory"] = (
                "Improving"
                if trends["ndvi_yoy_avg_change"] > 0.02
                else "Declining"
                if trends["ndvi_yoy_avg_change"] < -0.02
                else "Stable"
            )
        elif len(ndvi_means) >= 2:
            trends["ndvi_start"] = round(ndvi_means[0], 4)
            trends["ndvi_end"] = round(ndvi_means[-1], 4)
            trends["ndvi_change"] = round(trends["ndvi_end"] - trends["ndvi_start"], 4)
            if trends["ndvi_start"] != 0:
                trends["ndvi_pct_change"] = round(trends["ndvi_change"] / trends["ndvi_start"] * 100, 1)
            else:
                trends["ndvi_pct_change"] = 0.0
            trends["ndvi_trajectory"] = (
                "Improving"
                if trends["ndvi_change"] > 0.02
                else "Declining"
                if trends["ndvi_change"] < -0.02
                else "Stable"
            )

        trends["significant_events"] = events[:5]

        season_summary: dict[str, dict[str, Any]] = {}
        for season_key, pairs in sorted(season_bins.items()):
            vals: list[float] = [p[1] for p in pairs]
            season_summary[season_key] = {
                "avg": round(sum(vals) / len(vals), 3),
                "min": round(min(vals), 3),
                "max": round(max(vals), 3),
                "n_years": len(vals),
            }
        if season_summary:
            trends["ndvi_by_season"] = season_summary

    if weather_series:
        temps: list[float] = [float(s["temperature"]) for s in weather_series if s.get("temperature") is not None]
        precips: list[float] = [float(s["precipitation"]) for s in weather_series if s.get("precipitation") is not None]
        months: list[str] = [str(s["month"]) for s in weather_series if s.get("month")]

        if len(temps) >= 2:
            trends["temp_avg"] = round(sum(temps) / len(temps), 1)
            trends["temp_min"] = round(min(temps), 1)
            trends["temp_max"] = round(max(temps), 1)

            if months and len(months) >= 2:
                trends["weather_period"] = f"{months[0]} to {months[-1]}"
                try:
                    first_parts = months[0].split("-")
                    last_parts = months[-1].split("-")
                    real_span = (int(last_parts[0]) - int(first_parts[0])) * 12 + (
                        int(last_parts[1]) - int(first_parts[1])
                    )
                except (ValueError, IndexError):
                    real_span = len(months)
            else:
                real_span = len(temps)

            temp_change = temps[-1] - temps[0]
            abs_change = abs(temp_change)
            trends["temp_change"] = round(temp_change, 1)

            if real_span >= 6 and abs_change >= 5:
                trends["temp_change_source"] = "Seasonal pattern (expected)"
            elif real_span < 3 and abs_change >= 3:
                trends["temp_change_source"] = "Potential anomaly (rapid change in short period)"
            elif abs_change >= 10:
                trends["temp_change_source"] = "Potential anomaly (extreme change)"
            else:
                trends["temp_change_source"] = "Normal variation"

        if precips:
            trends["precip_total"] = round(sum(precips), 1)
            trends["precip_avg"] = round(sum(precips) / len(precips), 1)

            dry_months: list[str] = []
            wet_months: list[str] = []
            for ws in weather_series:
                p = ws.get("precipitation")
                m: str = str(ws.get("month", "?"))
                if p is not None:
                    if p < 10:
                        dry_months.append(m)
                    elif p > 150:
                        wet_months.append(m)
            if dry_months:
                trends["dry_months"] = dry_months[:6]
            if wet_months:
                trends["wet_months"] = wet_months[:6]

    return trends
