"""AI-powered frame analysis and annotations (Phase 3 - Item #9, M1.6).

Uses Azure AI Foundry with Ollama fallback via treesight.ai.

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json
import logging
import re
import statistics
from typing import Any

import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response
from treesight.ai import generate_analysis
from treesight.constants import EUDR_CUTOFF_DATE
from treesight.security.rate_limit import get_client_ip, pipeline_limiter

# Prompt-injection defence: strip anything that isn't alphanumeric,
# whitespace, hyphens, periods, commas, or parentheses.
_PROMPT_SAFE_RE = re.compile(r"[^A-Za-z0-9\s\-.,()]+")
_MAX_PROMPT_FIELD_LEN = 200


def _sanitise_for_prompt(value: str) -> str:
    """Sanitise a user-supplied string before embedding it in an LLM prompt."""
    if not isinstance(value, str):
        return ""
    cleaned = _PROMPT_SAFE_RE.sub("", value)
    return cleaned.strip()[:_MAX_PROMPT_FIELD_LEN]


bp = func.Blueprint()

# Maximum size (bytes) for the JSON body on AI endpoints to prevent cost abuse
_MAX_AI_BODY_BYTES = 32_768  # 32 KiB
# Maximum number of NDVI timeseries entries
_MAX_TIMESERIES_ENTRIES = 120

logger = logging.getLogger(__name__)


def _run_analysis(
    req: func.HttpRequest,
    *,
    run_fn,
    require_ndvi: bool = False,
    rate_limit: bool = True,
    error_msg: str = "Analysis failed",
) -> func.HttpResponse:
    """Shared pipeline: auth \u2192 rate-limit \u2192 parse \u2192 generate \u2192 respond."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    if rate_limit and not pipeline_limiter.is_allowed(get_client_ip(req)):
        return error_response(
            429, "Too many requests \u2014 please wait before trying again", req=req
        )

    raw_body = req.get_body()
    if len(raw_body) > _MAX_AI_BODY_BYTES:
        return error_response(
            400, f"Request body too large (max {_MAX_AI_BODY_BYTES} bytes)", req=req
        )

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    context = body.get("context", {})

    if require_ndvi:
        if not context or not context.get("ndvi_timeseries"):
            return error_response(400, "Missing 'context' with ndvi_timeseries", req=req)
        ndvi_ts = context.get("ndvi_timeseries", [])
        if not isinstance(ndvi_ts, list) or len(ndvi_ts) > _MAX_TIMESERIES_ENTRIES:
            return error_response(
                400,
                f"ndvi_timeseries must be a list of at most {_MAX_TIMESERIES_ENTRIES} entries",
                req=req,
            )
    else:
        if not context:
            return error_response(400, "Missing 'context' with satellite metadata", req=req)

    try:
        return run_fn(req, context)
    except Exception:
        logger.exception(error_msg)
        return error_response(500, error_msg, req=req)


def _frame_logic(req: func.HttpRequest, context: dict) -> func.HttpResponse:
    """Build frame-analysis prompt and call AI."""
    context_lines: list[str] = []
    if context.get("aoi_name"):
        aoi_name = _sanitise_for_prompt(context["aoi_name"])
        if aoi_name:
            context_lines.append(f"Area of Interest: {aoi_name}")
    if context.get("date"):
        date_val = _sanitise_for_prompt(context["date"])
        if date_val:
            context_lines.append(f"Date: {date_val}")
    if context.get("latitude") and context.get("longitude"):
        context_lines.append(f"Location: {context['latitude']:.2f}, {context['longitude']:.2f}")

    context_lines.append("\n=== Vegetation Health ===")
    if context.get("ndvi_mean") is not None:
        context_lines.append(f"NDVI (current): {context['ndvi_mean']:.3f}")
    if context.get("ndvi_previous") is not None:
        context_lines.append(f"NDVI (previous): {context['ndvi_previous']:.3f}")
        ndvi_change = context["ndvi_mean"] - context["ndvi_previous"]
        pct = ndvi_change / context["ndvi_previous"] * 100
        context_lines.append(f"NDVI Change: {ndvi_change:+.3f} ({pct:+.1f}%)")
    if context.get("ndvi_min") is not None:
        context_lines.append(f"NDVI Range: {context['ndvi_min']:.3f} to {context['ndvi_max']:.3f}")

    context_lines.append("\n=== Weather Context ===")
    if context.get("temperature") is not None:
        context_lines.append(f"Temperature: {context['temperature']:.1f}°C")
    if context.get("precipitation") is not None:
        context_lines.append(f"Precipitation (90 days): {context['precipitation']:.0f}mm")

    context_str = "\n".join(context_lines)

    prompt = f"""You are an expert geospatial analyst. Analyze this satellite \
image metadata and provide structured observations about the area's \
vegetation health, land use, and any concerning trends.

{context_str}

Provide analysis as JSON with exactly this structure (respond ONLY with valid JSON):
{{
  "observations": [
    {{
      "category": "vegetation_health",
      "severity": "critical|high|moderate|low|normal",
      "description": "Specific observation",
      "recommendation": "Suggested action"
    }}
  ],
  "summary": "2-3 sentence executive summary",
  "score": 0.5
}}

Categories: vegetation_health, water, clearing, anomaly, or trend.
Keep descriptions concise. Recommend at-risk areas for closer monitoring."""

    analysis = generate_analysis(prompt)
    if analysis is None:
        analysis = _default_analysis("AI analysis unavailable — all providers failed")

    return func.HttpResponse(
        json.dumps(analysis),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(route="frame-analysis", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def frame_analysis(req: func.HttpRequest) -> func.HttpResponse:
    """Analyze satellite frame metadata using local LLM.

    Generates observations about:
    - Vegetation health and changes (via NDVI)
    - Temporal trends
    - Weather conditions
    - Anomalies or areas of concern

    Request body:
    {
        "context": {
            "aoi_name": "Mountsorrel",
            "date": "2023-02-15",
            "ndvi_mean": 0.52,
            "ndvi_previous": 0.58,
            "ndvi_min": 0.2,
            "ndvi_max": 0.8,
            "temperature": 9.5,
            "precipitation": 72,
            "latitude": 52.21,
            "longitude": -0.62
        }
    }

    Response:
    {
        "observations": [
            {
                "category": "vegetation_health",
                "severity": "moderate",
                "description": "...",
                "recommendation": "..."
            }
        ],
        "summary": "...",
        "score": 0.65
    }
    """
    return _run_analysis(req, run_fn=_frame_logic, error_msg="Analysis failed")


def _default_analysis(text: str) -> dict[str, Any]:
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


def _timelapse_logic(req: func.HttpRequest, context: dict) -> func.HttpResponse:
    """Build timelapse-analysis prompt and call AI."""
    ndvi_series = context.get("ndvi_timeseries", [])
    weather_series = context.get("weather_timeseries", [])

    # Calculate trend statistics
    trend_info = _calculate_trends(ndvi_series, weather_series)

    # Build analysis prompt with temporal context
    context_lines: list[str] = []
    if context.get("aoi_name"):
        aoi_name = _sanitise_for_prompt(context["aoi_name"])
        if aoi_name:
            context_lines.append(f"Area of Interest: {aoi_name}")
    if context.get("date_range_start") and context.get("date_range_end"):
        start = _sanitise_for_prompt(context["date_range_start"])
        end = _sanitise_for_prompt(context["date_range_end"])
        if start and end:
            context_lines.append(f"Analysis Period: {start} to {end}")
    if context.get("latitude") and context.get("longitude"):
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

    # Season breakdown
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

    prompt = f"""You are an expert geospatial analyst reviewing \
satellite timelapse data spanning multiple years. Analyze these \
observations and provide accurate, evidence-based findings.

{context_str}

Provide structured analysis as JSON (respond ONLY with valid JSON, \
no markdown):
{{
  "observations": [
    {{
      "category": "vegetation_health|trend|temperature|precipitation|anomaly",
      "severity": "critical|high|moderate|low|normal",
      "description": "Specific observation backed by the data above",
      "recommendation": "Suggested action or monitoring focus"
    }}
  ],
  "summary": "2-3 sentence executive summary of findings",
  "score": 0.0,
  "key_finding": "Most significant finding"
}}

CRITICAL RULES:
- The NDVI data is SEASONAL. Winter NDVI is naturally lower \
than summer — do NOT treat this as vegetation loss.
- Only flag YEAR-OVER-YEAR same-season changes as concerning \
(e.g. Summer 2023 vs Summer 2022).
- Temperature variation over 6+ months is SEASONAL, not anomalous.
- The "Significant Events" section lists real year-over-year \
deviations — use these as your primary evidence.
- The "Multi-year Trajectory" and per-season breakdown are the \
most reliable indicators.
- Set "score" between 0.0 (critical decline) and 1.0 (excellent \
health) based on the trajectory and data.
- Keep observations SPECIFIC — cite actual values from the data."""

    # Call AI provider (Azure AI Foundry → Ollama → graceful degradation)
    analysis = generate_analysis(prompt)
    if analysis is None:
        analysis = _default_analysis("AI analysis unavailable — all providers failed")

    # Add calculated trend info to response
    analysis["trend_data"] = trend_info

    return func.HttpResponse(
        json.dumps(analysis),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="timelapse-analysis",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def timelapse_analysis(req: func.HttpRequest) -> func.HttpResponse:
    """Analyze entire satellite timelapse series for trends and anomalies.

    Analyzes temporal patterns in:
    - Vegetation health progression
    - Weather trends
    - Anomalies or unexpected changes
    - Overall trajectory assessment

    Request body:
    {
        "context": {
            "aoi_name": "Mountsorrel",
            "latitude": 52.21,
            "longitude": -0.62,
            "date_range_start": "2023-01-15",
            "date_range_end": "2023-12-31",
            "frame_count": 12,
            "ndvi_timeseries": [
                {"date": "2023-01-15", "mean": 0.32, "min": 0.1, "max": 0.65},
                {"date": "2023-02-15", "mean": 0.38, "min": 0.15, "max": 0.72}
            ],
            "weather_timeseries": [
                {"month_index": 0, "temperature": 5.2, "precipitation": 84},
                {"month_index": 1, "temperature": 6.1, "precipitation": 72}
            ]
        }
    }

    Response:
    {
        "observations": [
            {
                "category": "trend",
                "severity": "moderate",
                "description": "...",
                "recommendation": "..."
            }
        ],
        "summary": "...",
        "score": 0.72,
        "trend_analysis": {...}
    }
    """
    return _run_analysis(
        req, run_fn=_timelapse_logic, require_ndvi=True, error_msg="Analysis failed"
    )


def _calculate_trends(
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
        # All means (including None placeholders for alignment)
        ndvi_means: list[float] = [
            float(s["mean"]) for s in ndvi_series if s.get("mean") is not None
        ]

        if len(ndvi_means) >= 2:
            trends["ndvi_avg"] = round(sum(ndvi_means) / len(ndvi_means), 4)
            trends["ndvi_max_val"] = round(max(ndvi_means), 4)
            trends["ndvi_min_val"] = round(min(ndvi_means), 4)

            # Volatility (standard deviation)
            trends["ndvi_std_dev"] = round(statistics.pstdev(ndvi_means), 4)
            trends["ndvi_volatility"] = (
                "High"
                if trends["ndvi_std_dev"] > 0.15
                else "Moderate"
                if trends["ndvi_std_dev"] > 0.08
                else "Low"
            )

        # --- Year-over-year same-season comparison (avoids seasonal false alarms) ---
        season_bins: dict[str, list[tuple[int, float]]] = {}
        for s in ndvi_series:
            mean_val = s.get("mean")
            season_key = s.get("season")
            year = s.get("year")
            if mean_val is not None and season_key and year:
                season_bins.setdefault(season_key, []).append((int(year), float(mean_val)))

        yoy_changes: list[float] = []
        events: list[str] = []
        for season_key, pairs in sorted(season_bins.items()):
            pairs.sort(key=lambda p: p[0])  # sort by year
            if len(pairs) >= 2:
                first_val = pairs[0][1]
                last_val = pairs[-1][1]
                yoy_change = last_val - first_val
                yoy_changes.append(yoy_change)

                # Detect significant year-over-year drops/spikes within same season
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
            # Fallback if no season metadata
            trends["ndvi_start"] = round(ndvi_means[0], 4)
            trends["ndvi_end"] = round(ndvi_means[-1], 4)
            trends["ndvi_change"] = round(trends["ndvi_end"] - trends["ndvi_start"], 4)
            if trends["ndvi_start"] != 0:
                trends["ndvi_pct_change"] = round(
                    trends["ndvi_change"] / trends["ndvi_start"] * 100, 1
                )
            else:
                trends["ndvi_pct_change"] = 0.0
            trends["ndvi_trajectory"] = (
                "Improving"
                if trends["ndvi_change"] > 0.02
                else "Declining"
                if trends["ndvi_change"] < -0.02
                else "Stable"
            )

        # Limit to top events
        trends["significant_events"] = events[:5]

        # --- Per-season summary table for the LLM ---
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
        temps: list[float] = [
            float(s["temperature"]) for s in weather_series if s.get("temperature") is not None
        ]
        precips: list[float] = [
            float(s["precipitation"]) for s in weather_series if s.get("precipitation") is not None
        ]
        months: list[str] = [str(s["month"]) for s in weather_series if s.get("month")]

        if len(temps) >= 2:
            trends["temp_avg"] = round(sum(temps) / len(temps), 1)
            trends["temp_min"] = round(min(temps), 1)
            trends["temp_max"] = round(max(temps), 1)

            # Use actual month labels for time span if available
            if months and len(months) >= 2:
                trends["weather_period"] = f"{months[0]} to {months[-1]}"
                # Parse year-month to compute real span
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

            # Temperature change classification using actual time span
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

            # Identify dry months (<10mm) and wet months (>150mm)
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


# ---------------------------------------------------------------------------
# EUDR compliance assessment (M4 §4.9)
# ---------------------------------------------------------------------------

_EUDR_CUTOFF = EUDR_CUTOFF_DATE


def _eudr_logic(req: func.HttpRequest, context: dict) -> func.HttpResponse:
    """Build EUDR assessment prompt and call AI."""
    ndvi_ts = context.get("ndvi_timeseries", [])

    # Filter to post-2020 data only — require a valid date or year
    post_cutoff = [
        s
        for s in ndvi_ts
        if (isinstance(s.get("date"), str) and s["date"] > _EUDR_CUTOFF)
        or (isinstance(s.get("year"), (int, float)) and s["year"] > 2020)
    ]
    if not post_cutoff:
        return error_response(400, "No post-2020 NDVI data available for EUDR assessment", req=req)

    weather_series = context.get("weather_timeseries", [])
    trend_info = _calculate_trends(post_cutoff, weather_series)

    # Build EUDR-specific prompt
    context_lines: list[str] = []
    if context.get("aoi_name"):
        aoi_name = _sanitise_for_prompt(context["aoi_name"])
        if aoi_name:
            context_lines.append(f"Area of Interest: {aoi_name}")
    lat_raw = context.get("latitude")
    lon_raw = context.get("longitude")
    if lat_raw is not None and lon_raw is not None:
        try:
            latitude = float(lat_raw)
            longitude = float(lon_raw)
        except (TypeError, ValueError):
            return error_response(
                400,
                "Invalid latitude/longitude; values must be numeric.",
                req=req,
            )
        context_lines.append(f"Location: {latitude:.4f}, {longitude:.4f}")
    context_lines.append(f"EUDR Reference Date: {_EUDR_CUTOFF} (EU Regulation 2023/1115 Art. 2)")
    context_lines.append(f"Analysis Period: post-{_EUDR_CUTOFF} ({len(post_cutoff)} observations)")

    context_lines.append("\n=== Post-2020 Vegetation Data ===")
    if trend_info.get("ndvi_avg") is not None:
        context_lines.append(f"NDVI Average: {trend_info['ndvi_avg']:.3f}")
    if trend_info.get("ndvi_min_val") is not None:
        context_lines.append(
            f"NDVI Range: {trend_info['ndvi_min_val']:.3f} to {trend_info['ndvi_max_val']:.3f}"
        )
    if trend_info.get("ndvi_trajectory"):
        context_lines.append(f"Trajectory: {trend_info['ndvi_trajectory']}")
    if trend_info.get("ndvi_yoy_avg_change") is not None:
        context_lines.append(f"Avg Year-over-Year Change: {trend_info['ndvi_yoy_avg_change']:+.4f}")

    if trend_info.get("ndvi_by_season"):
        context_lines.append("\n  Per-season post-2020 NDVI:")
        for skey, sdata in trend_info["ndvi_by_season"].items():
            context_lines.append(
                f"    {skey.capitalize()}: avg={sdata['avg']:.3f} "
                f"(range {sdata['min']:.3f}–{sdata['max']:.3f})"
            )

    context_lines.append("\n=== Significant Events (post-2020) ===")
    if trend_info.get("significant_events"):
        for event in trend_info["significant_events"]:
            context_lines.append(f"• {event}")
    else:
        context_lines.append("• No significant deviations detected")

    context_str = "\n".join(context_lines)

    prompt = f"""You are an expert geospatial analyst conducting an EU \
Deforestation Regulation (EUDR) due-diligence assessment. The EUDR \
(Regulation 2023/1115) requires operators to demonstrate that commodities \
were produced on land not subject to deforestation after 31 December 2020.

{context_str}

Provide a structured EUDR compliance assessment as JSON (respond ONLY \
with valid JSON, no markdown):
{{
  "deforestation_free": true,
  "confidence": "high|medium|low",
  "conclusion": "Clear 1-sentence conclusion starting with the site name",
  "evidence": [
    {{
      "indicator": "Specific data point or observation",
      "interpretation": "What this means for EUDR compliance"
    }}
  ],
  "risk_factors": ["Any identified risks or caveats"],
  "methodology": "Brief description of assessment methodology",
  "recommendation": "Next steps for the operator",
  "disclaimer": "Regulatory disclaimer"
}}

CRITICAL RULES:
- Lead with the BINARY conclusion: deforestation_free = true or false.
- Set confidence to "high" only when ALL seasons show stable or improving \
vegetation with no significant year-over-year declines.
- Set confidence to "low" if data is sparse (<4 observations) or if \
any significant decline events were detected.
- "deforestation_free" should be false if ANY same-season NDVI decline \
exceeds 0.15 (indicating possible canopy loss).
- Always include a disclaimer that satellite analysis alone does not \
constitute full EUDR due diligence.
- Cite actual NDVI values from the data as evidence.
- Compare SAME SEASONS across years — seasonal variation is NOT deforestation."""

    analysis = generate_analysis(prompt)
    if analysis is None:
        analysis = {
            "deforestation_free": None,
            "confidence": "unavailable",
            "conclusion": "AI analysis unavailable — all providers failed",
            "evidence": [],
            "risk_factors": ["Automated assessment could not be completed"],
            "methodology": "N/A",
            "recommendation": "Manual review required",
            "disclaimer": "This is an automated preliminary assessment only.",
        }

    analysis["trend_data"] = trend_info
    analysis["eudr_cutoff_date"] = _EUDR_CUTOFF
    analysis["observations_analysed"] = len(post_cutoff)

    return func.HttpResponse(
        json.dumps(analysis),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="eudr-assessment",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def eudr_assessment(req: func.HttpRequest) -> func.HttpResponse:
    """AI-generated EUDR deforestation-free due-diligence statement.

    Analyses post-2020 NDVI timeseries data and produces a structured
    compliance assessment leading with a clear yes/no conclusion.

    Request body mirrors ``timelapse-analysis`` but adds ``eudr_mode: true``.
    """
    return _run_analysis(
        req,
        run_fn=_eudr_logic,
        require_ndvi=True,
        rate_limit=False,
        error_msg="EUDR assessment failed",
    )
