"""Coordinate-to-polygon parser (#601).

Accepts:
- Single lat,lon pair → point buffer polygon (circle approximation)
- Multiple lat,lon lines → polygon from coordinate list
- CSV text with lat/lon columns → multiple point-buffer AOIs

All output is ``list[Feature]``, identical to the KML parsers, so the
rest of the pipeline works unchanged.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re

from treesight.constants import METRES_PER_DEGREE_LATITUDE
from treesight.models.feature import Feature
from treesight.parsers import ensure_closed

logger = logging.getLogger(__name__)

# Default point-buffer radius in metres
DEFAULT_BUFFER_M = 500.0

# Number of vertices for the circle approximation
_CIRCLE_SEGMENTS = 32

# Maximum number of coordinate rows accepted
MAX_COORDINATE_ROWS = 500

# Regex for a lat,lon pair (supports comma, tab, semicolon, or whitespace separation)
_PAIR_RE = re.compile(
    r"^\s*"
    r"(?P<lat>[+-]?\d+(?:\.\d+)?)"
    r"\s*[,;\t ]\s*"
    r"(?P<lon>[+-]?\d+(?:\.\d+)?)"
    r"\s*$"
)


def _validate_lat_lon(lat: float, lon: float) -> None:
    """Raise ValueError if lat/lon is out of bounds."""
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"Longitude {lon} out of range [-180, 180]")


def _point_to_polygon(
    lat: float, lon: float, buffer_m: float = DEFAULT_BUFFER_M
) -> list[list[float]]:
    """Create a circle-approximation polygon around a point.

    Returns exterior ring as ``[[lon, lat], ...]`` (GeoJSON convention).
    """
    lat_offset = buffer_m / METRES_PER_DEGREE_LATITUDE
    lon_offset = buffer_m / (METRES_PER_DEGREE_LATITUDE * max(math.cos(math.radians(lat)), 1e-10))

    ring: list[list[float]] = []
    for i in range(_CIRCLE_SEGMENTS):
        angle = 2.0 * math.pi * i / _CIRCLE_SEGMENTS
        ring.append(
            [
                round(lon + lon_offset * math.cos(angle), 8),
                round(lat + lat_offset * math.sin(angle), 8),
            ]
        )
    return ensure_closed(ring)


def _parse_pairs(text: str) -> list[tuple[float, float]]:
    """Parse lines of lat,lon pairs from text. Returns ``[(lat, lon), ...]``."""
    pairs: list[tuple[float, float]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _PAIR_RE.match(line)
        if not m:
            raise ValueError(f"Cannot parse coordinate line: {line!r}")
        lat, lon = float(m.group("lat")), float(m.group("lon"))
        _validate_lat_lon(lat, lon)
        pairs.append((lat, lon))
    return pairs


def parse_coordinate_text(
    text: str,
    *,
    buffer_m: float = DEFAULT_BUFFER_M,
    source_file: str = "coordinates",
) -> list[Feature]:
    """Parse plain-text coordinate input into Features.

    Single pair → point buffer.
    Multiple pairs → if ≥ 3, treated as polygon vertices; otherwise
    each pair becomes a point buffer.

    Parameters
    ----------
    text : str
        The raw coordinate text (lines of lat,lon).
    buffer_m : float
        Buffer radius in metres for point inputs.
    source_file : str
        Source identifier attached to each Feature.

    Returns
    -------
    list[Feature]
        One or more Features ready for ``prepare_aoi``.
    """
    pairs = _parse_pairs(text)
    if not pairs:
        raise ValueError("No coordinates found in input")
    if len(pairs) > MAX_COORDINATE_ROWS:
        raise ValueError(f"Too many coordinates ({len(pairs)}); maximum is {MAX_COORDINATE_ROWS}")

    features: list[Feature] = []

    if len(pairs) == 1:
        # Single point → buffer polygon
        lat, lon = pairs[0]
        ring = _point_to_polygon(lat, lon, buffer_m)
        features.append(
            Feature(
                name=f"Point ({lat:.6f}, {lon:.6f})",
                exterior_coords=ring,
                source_file=source_file,
                feature_index=0,
            )
        )
    elif len(pairs) == 2:
        # Two points → each becomes a buffer polygon
        for i, (lat, lon) in enumerate(pairs):
            ring = _point_to_polygon(lat, lon, buffer_m)
            features.append(
                Feature(
                    name=f"Point ({lat:.6f}, {lon:.6f})",
                    exterior_coords=ring,
                    source_file=source_file,
                    feature_index=i,
                )
            )
    else:
        # ≥ 3 points → treat as polygon vertices
        # Coordinate convention: input is lat,lon but Feature uses [lon, lat]
        ring = [[lon, lat] for lat, lon in pairs]
        ring = ensure_closed(ring)
        features.append(
            Feature(
                name="Coordinate polygon",
                exterior_coords=ring,
                source_file=source_file,
                feature_index=0,
            )
        )

    return features


def parse_csv(
    csv_text: str,
    *,
    buffer_m: float = DEFAULT_BUFFER_M,
    source_file: str = "csv_upload",
) -> list[Feature]:
    """Parse CSV with lat/lon columns into point-buffer Features.

    The CSV must have columns identifiable as latitude and longitude.
    Accepted column names (case-insensitive): ``lat``, ``latitude``,
    ``lon``, ``lng``, ``longitude``, ``long``.

    Optionally a ``name`` column provides the feature name.

    Parameters
    ----------
    csv_text : str
        Raw CSV text content.
    buffer_m : float
        Buffer radius for point polygons.
    source_file : str
        Source identifier.

    Returns
    -------
    list[Feature]
        One Feature per CSV row.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")

    # Normalise header names
    headers = {h.strip().lower(): h for h in reader.fieldnames}
    lat_col = _find_column(headers, {"lat", "latitude"})
    lon_col = _find_column(headers, {"lon", "lng", "longitude", "long"})
    if lat_col is None or lon_col is None:
        raise ValueError(
            "CSV must have latitude and longitude columns "
            "(accepted: lat/latitude, lon/lng/longitude/long)"
        )

    name_col = _find_column(headers, {"name", "label", "aoi", "site"})

    features: list[Feature] = []
    for i, row in enumerate(reader):
        if i >= MAX_COORDINATE_ROWS:
            raise ValueError(f"Too many CSV rows ({i + 1}+); maximum is {MAX_COORDINATE_ROWS}")
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Row {i + 1}: invalid coordinate values") from exc

        _validate_lat_lon(lat, lon)

        fname = (
            str(row[name_col]).strip()
            if name_col and row.get(name_col)
            else f"Point ({lat:.6f}, {lon:.6f})"
        )

        ring = _point_to_polygon(lat, lon, buffer_m)
        features.append(
            Feature(
                name=fname,
                exterior_coords=ring,
                source_file=source_file,
                feature_index=i,
            )
        )

    if not features:
        raise ValueError("CSV contains no data rows")

    return features


def _find_column(headers: dict[str, str], candidates: set[str]) -> str | None:
    """Find the original column name matching one of the candidate names."""
    for norm, orig in headers.items():
        if norm in candidates:
            return orig
    return None
