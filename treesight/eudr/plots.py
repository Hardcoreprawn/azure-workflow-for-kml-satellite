"""EUDR plot validation helpers.

Pure functions for validating and sanitising coordinate plot inputs.
No HTTP or Azure Functions dependency.
"""

from __future__ import annotations

import contextlib
import re

_NAME_RE = re.compile(r"[^A-Za-z0-9\s\-_.]+")
_MAX_NAME_LEN = 100


def sanitise_name(val: str) -> str:
    """Sanitise a plot name: strip unsafe characters and truncate."""
    if not isinstance(val, str):
        return ""
    return _NAME_RE.sub("", val).strip()[:_MAX_NAME_LEN]


def validate_plot(i: int, p: dict) -> dict | str:
    """Validate a single plot entry. Returns a cleaned dict on success or an error string."""
    if not isinstance(p, dict):
        return f"Plot {i} must be an object"

    name = sanitise_name(p.get("name", f"Plot {i + 1}"))
    entry: dict = {"name": name}

    if "coordinates" in p:
        coords = p["coordinates"]
        if not isinstance(coords, list) or len(coords) < 3:
            return f"Plot {i} coordinates must have >= 3 points"
        for j, c in enumerate(coords):
            if not isinstance(c, list) or len(c) < 2:
                return f"Plot {i} coordinate {j} must be [lon, lat]"
            try:
                clon = float(c[0])
                clat = float(c[1])
            except (TypeError, ValueError):
                return f"Plot {i} coordinate {j} lon/lat must be numbers"
            if not (-180 <= clon <= 180 and -90 <= clat <= 90):
                return f"Plot {i} coordinate {j} out of range"
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
