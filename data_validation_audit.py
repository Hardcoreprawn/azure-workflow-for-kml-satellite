#!/usr/bin/env python3
"""
Data Validation Audit Framework for TreeSight Analysis

This tool conducts researcher-grade data integrity checks:
1. Verifies input data consistency
2. Validates backend calculations against inputs
3. Checks for LLM number hallucination
4. Flags data anomalies
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx


def validate_input_data(context: dict[str, Any]) -> tuple[bool, list[str]]:
    """Audit input data for logical consistency."""
    issues: list[str] = []

    ndvi_series = context.get("ndvi_timeseries", [])
    weather_series = context.get("weather_timeseries", [])

    # Check NDVI values are within valid range
    for i, entry in enumerate(ndvi_series):
        mean = entry.get("mean")
        min_val = entry.get("min")
        max_val = entry.get("max")

        if mean is None:
            issues.append(f"❌ NDVI entry {i}: missing 'mean' value")
        elif not (0 <= mean <= 1):
            issues.append(f"❌ NDVI entry {i}: mean={mean} out of range [0, 1]")

        if min_val is not None and max_val is not None:
            if not (min_val <= mean <= max_val):
                issues.append(
                    f"❌ NDVI entry {i}: mean={mean} not between min={min_val}, max={max_val}"
                )
            if min_val < 0 or max_val > 1:
                issues.append(f"❌ NDVI entry {i}: range [{min_val}, {max_val}] invalid")

    # Check temperature values are reasonable
    for i, entry in enumerate(weather_series):
        temp = entry.get("temperature")
        precip = entry.get("precipitation")

        if temp is not None:
            # Reasonable Earth bounds (Vostok: -89°C, Death Valley: 57°C)
            if temp < -90 or temp > 60:
                issues.append(
                    f"⚠️  WEATHER entry {i}: temperature={temp}°C outside observed Earth range"
                )

        if precip is not None:
            if precip < 0:
                issues.append(f"❌ WEATHER entry {i}: precipitation={precip}mm cannot be negative")
            if precip > 3000:  # Single month > 3000mm is extremely rare
                issues.append(
                    f"⚠️  WEATHER entry {i}: precipitation={precip}mm unusually high (>3000mm)"
                )

    # Check temporal ordering
    dates = [e.get("date") for e in ndvi_series if e.get("date")]
    if dates and len(dates) > 1:
        for j in range(len(dates) - 1):
            if dates[j] >= dates[j+1]:
                issues.append(f"❌ NDVI dates not in ascending order: {dates[j]} >= {dates[j+1]}")

    return len(issues) == 0, issues


def validate_backend_calculations(
    context: dict[str, Any], trend_data: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Check if backend calculations match expected values."""
    issues: list[str] = []

    ndvi_series = context.get("ndvi_timeseries", [])
    weather_series = context.get("weather_timeseries", [])

    # Validate NDVI calculations
    ndvi_means = [s.get("mean") for s in ndvi_series if s.get("mean") is not None]
    if len(ndvi_means) >= 2:
        expected_start = ndvi_means[0]
        expected_end = ndvi_means[-1]
        expected_pct = (
            (expected_end - expected_start) / expected_start * 100 if expected_start != 0 else 0
        )

        actual_start: float = trend_data.get("ndvi_start") or 0.0
        actual_end: float = trend_data.get("ndvi_end") or 0.0
        actual_pct: float = trend_data.get("ndvi_pct_change") or 0.0

        if abs(actual_start - expected_start) > 0.001:
            issues.append(f"❌ NDVI Start: backend={actual_start}, expected={expected_start}")
        if abs(actual_end - expected_end) > 0.001:
            issues.append(f"❌ NDVI End: backend={actual_end}, expected={expected_end}")
        if abs(actual_pct - expected_pct) > 0.1:
            issues.append(f"❌ NDVI %Change: backend={actual_pct}%, expected={expected_pct:.1f}%")

    # Validate temperature calculations
    temps = [s.get("temperature") for s in weather_series if s.get("temperature") is not None]
    if len(temps) >= 2:
        expected_start = temps[0]
        expected_end = temps[-1]
        expected_change = expected_end - expected_start

        actual_start: float = trend_data.get("temp_avg_start") or 0.0
        actual_end: float = trend_data.get("temp_avg_end") or 0.0
        actual_change: float = trend_data.get("temp_change") or 0.0

        if abs(actual_start - expected_start) > 0.1:
            issues.append(f"❌ Temp Start: backend={actual_start}, expected={expected_start}")
        if abs(actual_end - expected_end) > 0.1:
            issues.append(f"❌ Temp End: backend={actual_end}, expected={expected_end}")
        if abs(actual_change - expected_change) > 0.1:
            issues.append(f"❌ Temp Change: backend={actual_change}, expected={expected_change}")

    # Validate precipitation calculations
    precips = [s.get("precipitation") for s in weather_series if s.get("precipitation") is not None]
    if precips:
        expected_total = sum(precips)
        actual_total: float = trend_data.get("precip_total") or 0.0

        if abs(actual_total - expected_total) > 1:
            issues.append(f"❌ Precip Total: backend={actual_total}, expected={expected_total}")

    return len(issues) == 0, issues


def check_llm_hallucination(
    observations: list[dict[str, Any]], trend_data: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Detect if LLM is citing numbers that don't appear in trend_data."""
    issues: list[str] = []

    # Extract numbers that should be in the data
    reliable_numbers = {
        f"{trend_data.get('ndvi_pct_change', 0):.1f}",  # NDVI %
        f"{trend_data.get('precip_total', 0):.0f}",     # Precip mm
        f"{trend_data.get('temp_change', 0):.1f}",      # Temp °C
        f"{trend_data.get('temp_avg_start', 0):.1f}",   # Temp start
        f"{trend_data.get('temp_avg_end', 0):.1f}",     # Temp end
    }

    for obs in observations:
        desc = obs.get("description", "")
        # Find all percentage, temperature, and precipitation numbers
        found_numbers = re.findall(r'(-?\d+\.?\d*)\s*(?:%|°C|mm)', desc)

        for num_str in found_numbers:
            # Check if this number appears in trend data (with reasonable tolerance)
            num = float(num_str)
            is_reliable = any(
                abs(num - float(rel)) < 1.0 for rel in reliable_numbers if rel != "nan"
            )

            if not is_reliable and num > 0.1:  # Small numbers might be approximations
                issues.append(f"⚠️  LLM cites '{num_str}' not in trend data: {obs['category']}")

    return len(issues) == 0, issues


def run_audit(test_data: dict[str, Any]) -> None:
    """Execute full audit."""
    context = test_data.get("context", {})

    print("\n" + "=" * 80)
    print("🔬 TREESIGHT DATA VALIDATION AUDIT")
    print("=" * 80)

    # Step 1: Validate input
    print("\n[1/4] INPUT DATA CONSISTENCY CHECK")
    print("-" * 80)
    input_ok, input_issues = validate_input_data(context)

    if input_ok:
        print("✅ All input data is logically consistent")
    else:
        print("⚠️  Input data issues found:")
        for issue in input_issues:
            print(f"      {issue}")

    # Step 2: Send to API and get calculations
    print("\n[2/4] SENDING TO BACKEND...")
    print("-" * 80)
    try:
        client = httpx.Client(timeout=200.0)
        resp = client.post(
            "http://localhost:7071/api/timelapse-analysis",
            json=test_data,
            timeout=200.0
        )
        response_data = resp.json()
        trend_data = response_data.get("trend_data", {})
        observations = response_data.get("observations", [])
        print(f"✅ API returned {len(observations)} observations")
    except Exception as e:
        print(f"❌ API request failed: {e}")
        return

    # Step 3: Validate backend calculations
    print("\n[3/4] BACKEND CALCULATION VERIFICATION")
    print("-" * 80)
    calc_ok, calc_issues = validate_backend_calculations(context, trend_data)

    if calc_ok:
        print("✅ Backend calculations match input data exactly")
        ndvi_s = trend_data.get('ndvi_start', 0)
        ndvi_e = trend_data.get('ndvi_end', 0)
        ndvi_pct = trend_data.get('ndvi_pct_change', 0)
        temp_s = trend_data.get('temp_avg_start', 0)
        temp_e = trend_data.get('temp_avg_end', 0)
        temp_d = trend_data.get('temp_change', 0)
        precip_t = trend_data.get('precip_total', 0)
        print(f"   - NDVI: {ndvi_s:.3f} → {ndvi_e:.3f} ({ndvi_pct:.1f}%)")
        print(f"   - Temp: {temp_s:.1f}°C → {temp_e:.1f}°C (Δ{temp_d:.1f}°C)")
        print(f"   - Precip: {precip_t:.0f}mm total")
    else:
        print("❌ Backend calculations don't match input data:")
        for issue in calc_issues:
            print(f"      {issue}")

    # Step 4: Check for LLM hallucination
    print("\n[4/4] LLM RELIABILITY CHECK")
    print("-" * 80)
    llm_ok, llm_issues = check_llm_hallucination(observations, trend_data)

    if llm_ok:
        print("✅ LLM only cites numbers from verified trend data")
    else:
        print("⚠️  LLM may be fabricating or extrapolating numbers:")
        for issue in llm_issues:
            print(f"      {issue}")

    # Summary
    print("\n" + "=" * 80)
    print("📊 AUDIT SUMMARY")
    print("=" * 80)

    verdict = [
        ("Input Data", "✅ RELIABLE" if input_ok else "⚠️  REVIEW"),
        ("Backend Math", "✅ VERIFIED" if calc_ok else "❌ SUSPECT"),
        ("LLM Citations", "✅ SOUND" if llm_ok else "⚠️  CAUTION"),
    ]

    for category, status in verdict:
        print(f"{category:20s}: {status}")

    print("\n" + "=" * 80)
    if input_ok and calc_ok and llm_ok:
        print("✅ DATA RELIABILITY: PRODUCTION GRADE")
        print("   All values are sourced from input data. Analysis is trustworthy.")
    elif calc_ok and not llm_ok:
        print("⚠️  DATA RELIABILITY: USE WITH CAUTION")
        print("   Backend is correct, but LLM may be interpreting/extrapolating.")
    else:
        print("❌ DATA RELIABILITY: SUSPECT")
        print("   Calculation or input issues detected. Verify source data manually.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    # Example usage with user's data
    import sys

    if len(sys.argv) > 1:
        # Load from JSON file
        with open(sys.argv[1]) as f:
            test_data = json.load(f)
    else:
        # Use built-in test example
        test_data: dict[str, Any] = {
            "context": {
                "aoi_name": "DataAuditTest",
                "latitude": 36.90,
                "longitude": -120.06,
                "frame_count": 5,
                "date_range_start": "2020-01-01",
                "date_range_end": "2020-05-01",
                "ndvi_timeseries": [
                    {"date": "2020-01-01", "mean": 0.60, "min": 0.3, "max": 0.8},
                    {"date": "2020-02-01", "mean": 0.58, "min": 0.3, "max": 0.8},
                    {"date": "2020-03-01", "mean": 0.50, "min": 0.2, "max": 0.75},
                    {"date": "2020-04-01", "mean": 0.40, "min": 0.15, "max": 0.65},
                    {"date": "2020-05-01", "mean": 0.36, "min": 0.1, "max": 0.60},
                ],
                "weather_timeseries": [
                    {"month_index": 0, "temperature": 15.0, "precipitation": 80},
                    {"month_index": 1, "temperature": 16.0, "precipitation": 90},
                    {"month_index": 2, "temperature": 18.0, "precipitation": 100},
                    {"month_index": 3, "temperature": 20.0, "precipitation": 110},
                    {"month_index": 4, "temperature": 22.0, "precipitation": 120},
                ]
            }
        }

    run_audit(test_data)
