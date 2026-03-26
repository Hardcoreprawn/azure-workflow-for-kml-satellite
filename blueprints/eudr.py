"""EUDR compliance endpoints — coordinate conversion, assessment (M4 §4.9–4.10).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import contextlib
import re

import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response

bp = func.Blueprint()

# Limits
_MAX_PLOTS = 200
_MAX_BODY_BYTES = 65_536  # 64 KiB
_NAME_RE = re.compile(r"[^A-Za-z0-9\s\-_.]+")
_MAX_NAME_LEN = 100


def _sanitise_name(val: str) -> str:
    if not isinstance(val, str):
        return ""
    return _NAME_RE.sub("", val).strip()[:_MAX_NAME_LEN]


def _validate_plot(i: int, p: dict) -> dict | str:
    """Validate a single plot entry. Returns dict on success or error string."""
    if not isinstance(p, dict):
        return f"Plot {i} must be an object"

    name = _sanitise_name(p.get("name", f"Plot {i + 1}"))
    entry: dict = {"name": name}

    if "coordinates" in p:
        coords = p["coordinates"]
        if not isinstance(coords, list) or len(coords) < 3:
            return f"Plot {i} coordinates must have >= 3 points"
        for j, c in enumerate(coords):
            if not isinstance(c, list) or len(c) < 2:
                return f"Plot {i} coordinate {j} must be [lon, lat]"
        entry["coordinates"] = [[float(c[0]), float(c[1])] for c in coords]
    elif "lon" in p and "lat" in p:
        try:
            lon = float(p["lon"])
            lat = float(p["lat"])
        except (TypeError, ValueError):
            return f"Plot {i} lon/lat must be numbers"
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return f"Plot {i} coordinates out of range"
        entry["lon"] = lon
        entry["lat"] = lat
        if "radius_m" in p:
            with contextlib.suppress(TypeError, ValueError):
                entry["radius_m"] = float(p["radius_m"])
    else:
        return f"Plot {i} needs 'lon'+'lat' or 'coordinates'"

    return entry


@bp.route(
    route="convert-coordinates",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def convert_coordinates(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/convert-coordinates — convert coordinate plots to KML.

    Accepts a JSON body with an array of plots (points or polygons) and
    returns a downloadable KML document.

    Request body::

        {
            "doc_name": "My EUDR Plots",
            "buffer_m": 100,
            "plots": [
                {"name": "Plot A", "lon": 2.35, "lat": 48.86},
                {"name": "Plot B", "lon": 2.36, "lat": 48.87, "radius_m": 200},
                {"name": "Block C", "coordinates": [[lon,lat], [lon,lat], ...]}
            ]
        }

    Response: KML file as ``application/vnd.google-earth.kml+xml``.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    raw = req.get_body()
    if len(raw) > _MAX_BODY_BYTES:
        return error_response(400, f"Body too large (max {_MAX_BODY_BYTES} bytes)", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object", req=req)

    plots = body.get("plots", [])
    if not isinstance(plots, list) or not plots:
        return error_response(400, "'plots' must be a non-empty array", req=req)
    if len(plots) > _MAX_PLOTS:
        return error_response(400, f"Maximum {_MAX_PLOTS} plots per request", req=req)

    # Validate each plot
    validated = []
    for i, p in enumerate(plots):
        result = _validate_plot(i, p)
        if isinstance(result, str):
            return error_response(400, result, req=req)
        validated.append(result)

    from treesight.pipeline.eudr import coords_to_kml

    doc_name = _sanitise_name(body.get("doc_name", "EUDR Plots")) or "EUDR Plots"
    buffer_m = float(body.get("buffer_m", 100.0))

    kml_str = coords_to_kml(validated, doc_name=doc_name, buffer_m=buffer_m)

    headers = cors_headers(req)
    headers["Content-Disposition"] = f'attachment; filename="{doc_name}.kml"'

    return func.HttpResponse(
        kml_str,
        status_code=200,
        mimetype="application/vnd.google-earth.kml+xml",
        headers=headers,
    )
