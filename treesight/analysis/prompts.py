"""AI prompt builders for satellite analysis and EUDR assessment.

Pure functions: accept data dicts and return prompt strings and
structured analysis dicts.  No HTTP or Azure Functions dependency.
"""

from __future__ import annotations

from typing import Any

from treesight.analysis.trends import calculate_trends, sanitise_for_prompt
from treesight.constants import EUDR_CUTOFF_DATE

_EUDR_CUTOFF = EUDR_CUTOFF_DATE


def build_timelapse_prompt(context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build the LLM prompt for timelapse vegetation analysis.

    Returns the prompt string ready to pass to ``generate_analysis``.
    """
    ndvi_series = context.get("ndvi_timeseries", [])
    weather_series = context.get("weather_timeseries", [])
    trend_info = calculate_trends(ndvi_series, weather_series)

    context_lines: list[str] = []
    if context.get("aoi_name"):
        aoi_name = sanitise_for_prompt(context["aoi_name"])
        if aoi_name:
            context_lines.append(f"Area of Interest: {aoi_name}")
    if context.get("date_range_start") and context.get("date_range_end"):
        start = sanitise_for_prompt(context["date_range_start"])
        end = sanitise_for_prompt(context["date_range_end"])
        if start and end:
            context_lines.append(f"Analysis Period: {start} to {end}")
    if context.get("latitude") is not None and context.get("longitude") is not None:
        context_lines.append(f"Location: {context['latitude']:.2f}, {context['longitude']:.2f}")

    n_frames = context.get("frame_count", len(ndvi_series))
    context_lines.append(f"\nObservations: {n_frames} satellite frames analyzed")

    context_lines.append("\n=== NDVI Vegetation Analysis ===")
    if trend_info.get("ndvi_avg") is not None:
        context_lines.append(f"NDVI Average: {trend_info['ndvi_avg']:.3f}")
    if trend_info.get("ndvi_min_val") is not None:
        lo = trend_info["ndvi_min_val"]
        hi = trend_info["ndvi_max_val"]
        context_lines.append(f"NDVI Range: {lo:.3f} to {hi:.3f}")
    if trend_info.get("ndvi_volatility"):
        vol = trend_info["ndvi_volatility"]
        std = trend_info.get("ndvi_std_dev", 0)
        context_lines.append(f"Volatility: {vol} (σ={std:.3f})")
    if trend_info.get("ndvi_trajectory"):
        context_lines.append(f"Multi-year Trajectory: {trend_info['ndvi_trajectory']}")
    if trend_info.get("ndvi_yoy_avg_change") is not None:
        yoy = trend_info["ndvi_yoy_avg_change"]
        context_lines.append(f"Avg Year-over-Year Change (same season): {yoy:+.4f}")
    elif trend_info.get("ndvi_change") is not None:
        chg = trend_info["ndvi_change"]
        pct = trend_info.get("ndvi_pct_change", 0)
        context_lines.append(f"Overall Change: {chg:+.3f} ({pct:+.1f}%)")

    if trend_info.get("ndvi_by_season"):
        context_lines.append("\n  Per-season NDVI averages:")
        for skey, sdata in trend_info["ndvi_by_season"].items():
            context_lines.append(
                f"    {skey.capitalize()}: avg={sdata['avg']:.3f} "
                f"(range {sdata['min']:.3f}–{sdata['max']:.3f}, {sdata['n_years']} years)"
            )

    context_lines.append("\n=== Weather Context ===")
    if trend_info.get("weather_period"):
        context_lines.append(f"Weather data: {trend_info['weather_period']}")
    if trend_info.get("temp_avg") is not None:
        t_avg = trend_info["temp_avg"]
        t_lo = trend_info.get("temp_min", 0)
        t_hi = trend_info.get("temp_max", 0)
        context_lines.append(f"Temperature: avg {t_avg:.1f}°C (range {t_lo:.1f} to {t_hi:.1f}°C)")
    if trend_info.get("temp_change") is not None:
        t_chg = trend_info["temp_change"]
        t_src = trend_info.get("temp_change_source", "unknown")
        context_lines.append(f"Temperature Change: {t_chg:+.1f}°C — {t_src}")
    if trend_info.get("precip_total") is not None:
        p_tot = trend_info["precip_total"]
        p_avg = trend_info.get("precip_avg", 0)
        context_lines.append(f"Total Precipitation: {p_tot:.0f}mm (avg {p_avg:.0f}mm/month)")
    if trend_info.get("dry_months"):
        dry = ", ".join(str(m) for m in trend_info["dry_months"])
        context_lines.append(f"Dry months (<10mm): {dry}")
    if trend_info.get("wet_months"):
        wet = ", ".join(str(m) for m in trend_info["wet_months"])
        context_lines.append(f"Wet months (>150mm): {wet}")

    context_lines.append("\n=== Significant Year-over-Year Events ===")
    if trend_info.get("significant_events"):
        for event in trend_info["significant_events"]:
            context_lines.append(f"• {event}")
    else:
        context_lines.append("• No significant deviations detected between same-season years")

    context_str = "\n".join(context_lines)

    return (
        f"You are an expert geospatial analyst reviewing "
        f"satellite timelapse data spanning multiple years. Analyze these "
        f"observations and provide accurate, evidence-based findings.\n\n"
        f"{context_str}\n\n"
        f"Provide structured analysis as JSON (respond ONLY with valid JSON, "
        f"no markdown):\n"
        f'{{\n'
        f'  "observations": [\n'
        f'    {{\n'
        f'      "category": "vegetation_health|trend|temperature|precipitation|anomaly",\n'
        f'      "severity": "critical|high|moderate|low|normal",\n'
        f'      "description": "Specific observation backed by the data above",\n'
        f'      "recommendation": "Suggested action or monitoring focus"\n'
        f"    }}\n"
        f"  ],\n"
        f'  "summary": "2-3 sentence executive summary of findings",\n'
        f'  "score": 0.0,\n'
        f'  "key_finding": "Most significant finding"\n'
        f"}}\n\n"
        f"CRITICAL RULES:\n"
        f"- The NDVI data is SEASONAL. Winter NDVI is naturally lower "
        f"than summer — do NOT treat this as vegetation loss.\n"
        f"- Only flag YEAR-OVER-YEAR same-season changes as concerning "
        f"(e.g. Summer 2023 vs Summer 2022).\n"
        f"- Temperature variation over 6+ months is SEASONAL, not anomalous.\n"
        f"- The \"Significant Events\" section lists real year-over-year "
        f"deviations — use these as your primary evidence.\n"
        f"- The \"Multi-year Trajectory\" and per-season breakdown are the "
        f"most reliable indicators.\n"
        f"- Set \"score\" between 0.0 (critical decline) and 1.0 (excellent "
        f"health) based on the trajectory and data.\n"
        f"- Keep observations SPECIFIC — cite actual values from the data."
    ), trend_info


def build_eudr_prompt(
    context: dict[str, Any],
) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | tuple[None, None, None]:
    """Build the LLM prompt for EUDR deforestation-free assessment.

    Returns ``(prompt, trend_info, post_cutoff)`` on success, or
    ``(None, None, None)`` when there is no post-2020 NDVI data.
    """
    ndvi_ts = context.get("ndvi_timeseries", [])

    post_cutoff = [
        s
        for s in ndvi_ts
        if (isinstance(s.get("date"), str) and s["date"] > _EUDR_CUTOFF)
        or (isinstance(s.get("year"), (int, float)) and s["year"] > 2020)
    ]
    if not post_cutoff:
        return None, None, None

    weather_series = context.get("weather_timeseries", [])
    trend_info = calculate_trends(post_cutoff, weather_series)

    context_lines: list[str] = []
    if context.get("aoi_name"):
        aoi_name = sanitise_for_prompt(context["aoi_name"])
        if aoi_name:
            context_lines.append(f"Area of Interest: {aoi_name}")
    lat_raw = context.get("latitude")
    lon_raw = context.get("longitude")
    if lat_raw is not None and lon_raw is not None:
        location: str | None = None
        try:
            latitude = float(lat_raw)
            longitude = float(lon_raw)
            location = f"Location: {latitude:.4f}, {longitude:.4f}"
        except (TypeError, ValueError):
            location = None
        if location:
            context_lines.append(location)
    context_lines.append(f"EUDR Reference Date: {_EUDR_CUTOFF} (EU Regulation 2023/1115 Art. 2)")
    context_lines.append(f"Analysis Period: post-{_EUDR_CUTOFF} ({len(post_cutoff)} observations)")

    context_lines.append("\n=== Post-2020 Vegetation Data ===")
    if trend_info.get("ndvi_avg") is not None:
        context_lines.append(f"NDVI Average: {trend_info['ndvi_avg']:.3f}")
    if trend_info.get("ndvi_min_val") is not None:
        context_lines.append(f"NDVI Range: {trend_info['ndvi_min_val']:.3f} to {trend_info['ndvi_max_val']:.3f}")
    if trend_info.get("ndvi_trajectory"):
        context_lines.append(f"Trajectory: {trend_info['ndvi_trajectory']}")
    if trend_info.get("ndvi_yoy_avg_change") is not None:
        context_lines.append(f"Avg Year-over-Year Change: {trend_info['ndvi_yoy_avg_change']:+.4f}")

    if trend_info.get("ndvi_by_season"):
        context_lines.append("\n  Per-season post-2020 NDVI:")
        for skey, sdata in trend_info["ndvi_by_season"].items():
            context_lines.append(
                f"    {skey.capitalize()}: avg={sdata['avg']:.3f} (range {sdata['min']:.3f}–{sdata['max']:.3f})"
            )

    context_lines.append("\n=== Significant Events (post-2020) ===")
    if trend_info.get("significant_events"):
        for event in trend_info["significant_events"]:
            context_lines.append(f"• {event}")
    else:
        context_lines.append("• No significant deviations detected")

    context_str = "\n".join(context_lines)

    prompt = (
        f"You are an expert geospatial analyst conducting an EU "
        f"Deforestation Regulation (EUDR) due-diligence assessment. The EUDR "
        f"(Regulation 2023/1115) requires operators to demonstrate that commodities "
        f"were produced on land not subject to deforestation after 31 December 2020.\n\n"
        f"{context_str}\n\n"
        f"Provide a structured satellite screening assessment as JSON (respond ONLY "
        f"with valid JSON, no markdown):\n"
        f'{{\n'
        f'  "screening_outcome": "no_signal_detected|signal_detected|insufficient_evidence",\n'
        f'  "confidence": "high|medium|low",\n'
        f'  "conclusion": "Clear 1-sentence conclusion starting with the site name",\n'
        f'  "evidence": [\n'
        f'    {{\n'
        f'      "indicator": "Specific data point or observation",\n'
        f'      "interpretation": "What this means for EUDR evidence"\n'
        f"    }}\n"
        f"  ],\n"
        f'  "risk_factors": ["Any identified risks or caveats"],\n'
        f'  "methodology": "Brief description of assessment methodology",\n'
        f'  "recommendation": "Next steps for the operator",\n'
        f'  "disclaimer": "Regulatory disclaimer"\n'
        f"}}\n\n"
        f"CRITICAL RULES:\n"
        f'- Use screening_outcome "no_signal_detected" when ALL seasons show stable or '
        f"improving vegetation with no significant year-over-year declines.\n"
        f'- Use "signal_detected" if ANY same-season NDVI decline exceeds 0.15 '
        f"(indicating possible canopy loss) or other deforestation indicators are present.\n"
        f'- Use "insufficient_evidence" if data is sparse (<4 observations).\n'
        f'- Set confidence to "high" only when ALL seasons show stable or improving '
        f"vegetation with no significant year-over-year declines.\n"
        f'- Set confidence to "low" if data is sparse (<4 observations) or if '
        f"any significant decline events were detected.\n"
        f"- Always include a disclaimer that satellite screening alone does not "
        f"constitute full EUDR due diligence or an operator risk conclusion.\n"
        f"- Cite actual NDVI values from the data as evidence.\n"
        f"- Compare SAME SEASONS across years — seasonal variation is NOT deforestation."
    )

    return prompt, trend_info, post_cutoff
