"""AI-powered timelapse analysis and EUDR assessment — HTTP dispatch shell.

Uses Azure AI Foundry with Ollama fallback via treesight.ai.
Pure business logic lives in treesight/analysis/.

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import json
import logging

import azure.functions as func

from blueprints._decorators import rate_limit, validate_body_size
from blueprints._helpers import cors_headers, error_response, require_auth
from treesight.ai import generate_analysis
from treesight.analysis.prompts import build_eudr_prompt, build_timelapse_prompt
from treesight.analysis.trends import default_analysis
from treesight.security.rate_limit import get_pipeline_limiter  # factory, not instance

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
    error_msg: str = "Analysis failed",
) -> func.HttpResponse:
    """Shared pipeline: parse → validate context → generate → respond.

    Auth, CORS preflight, rate-limit, and body-size are handled by the
    calling route's decorators (``@require_auth``, ``@rate_limit``,
    ``@validate_body_size``).
    """
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


def _timelapse_handler(req: func.HttpRequest, context: dict) -> func.HttpResponse:
    """Build timelapse-analysis prompt and call AI."""
    prompt, trend_info = build_timelapse_prompt(context)

    analysis = generate_analysis(prompt)
    if analysis is None:
        analysis = default_analysis("AI analysis unavailable — all providers failed")

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
@require_auth
@rate_limit(get_pipeline_limiter)
@validate_body_size(_MAX_AI_BODY_BYTES)
def timelapse_analysis(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
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
    return _run_analysis(req, run_fn=_timelapse_handler, require_ndvi=True, error_msg="Analysis failed")


def _eudr_handler(req: func.HttpRequest, context: dict) -> func.HttpResponse:
    """Build EUDR assessment prompt and call AI."""
    lat_raw = context.get("latitude")
    lon_raw = context.get("longitude")
    if lat_raw is not None and lon_raw is not None:
        try:
            float(lat_raw)
            float(lon_raw)
        except (TypeError, ValueError):
            return error_response(400, "Invalid latitude/longitude; values must be numeric.", req=req)

    prompt, trend_info, post_cutoff = build_eudr_prompt(context)
    if prompt is None:
        return error_response(400, "No post-2020 NDVI data available for EUDR assessment", req=req)

    from treesight.constants import EUDR_CUTOFF_DATE

    analysis = generate_analysis(prompt)
    if analysis is None:
        analysis = {
            "screening_outcome": "insufficient_evidence",
            "confidence": "unavailable",
            "conclusion": "AI analysis unavailable — all providers failed",
            "evidence": [],
            "risk_factors": ["Automated assessment could not be completed"],
            "methodology": "N/A",
            "recommendation": "Manual review required",
            "disclaimer": "This is an automated preliminary assessment only.",
        }

    analysis["trend_data"] = trend_info
    analysis["eudr_cutoff_date"] = EUDR_CUTOFF_DATE
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
@require_auth
@validate_body_size(_MAX_AI_BODY_BYTES)
def eudr_assessment(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """AI-generated EUDR deforestation-free due-diligence statement.

    Analyses post-2020 NDVI timeseries data and produces a structured
    compliance assessment leading with a clear yes/no conclusion.

    Request body mirrors ``timelapse-analysis`` but adds ``eudr_mode: true``.
    """
    return _run_analysis(
        req,
        run_fn=_eudr_handler,
        require_ndvi=True,
        error_msg="EUDR assessment failed",
    )
