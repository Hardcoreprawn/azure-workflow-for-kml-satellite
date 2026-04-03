"""Mosaic registration with Planetary Computer."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

PC_API = "https://planetarycomputer.microsoft.com/api/data/v1"


def _coords_to_bbox(
    coords: list[list[float]],
    pad: float = 0.02,
) -> list[list[float]]:
    """Compute a bounding box polygon from AOI coords.

    Coordinates are ``[lon, lat]`` pairs.
    """
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lat = min(lats) - pad
    max_lat = max(lats) + pad
    min_lon = min(lons) - pad
    max_lon = max(lons) + pad
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def register_mosaic(
    collection: str,
    date_start: str,
    date_end: str,
    bbox: list[list[float]],
    extra_filters: list[dict[str, Any]] | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """Register a Planetary Computer mosaic and return the search ID.

    Returns ``None`` if registration fails (error is logged as a warning).
    """
    filter_args: list[dict[str, Any]] = [
        {
            "op": "t_intersects",
            "args": [{"property": "datetime"}, {"interval": [date_start, date_end]}],
        },
        {
            "op": "s_intersects",
            "args": [
                {"property": "geometry"},
                {"type": "Polygon", "coordinates": [bbox]},
            ],
        },
    ]
    if extra_filters:
        filter_args.extend(extra_filters)

    sortby = (
        [{"field": "datetime", "direction": "desc"}]
        if collection == "naip"
        else [{"field": "eo:cloud_cover", "direction": "asc"}]
    )

    body: dict[str, Any] = {
        "collections": [collection],
        "filter-lang": "cql2-json",
        "filter": {"op": "and", "args": filter_args},
        "sortby": sortby,
    }

    if client is not None:
        try:
            r = client.post(f"{PC_API}/mosaic/register", json=body)
            r.raise_for_status()
            return r.json().get("searchid")
        except Exception as exc:
            logger.warning("Mosaic registration failed for %s: %s", collection, exc)
            return None

    with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as http:
        try:
            r = http.post(f"{PC_API}/mosaic/register", json=body)
            r.raise_for_status()
            return r.json().get("searchid")
        except Exception as exc:
            logger.warning("Mosaic registration failed for %s: %s", collection, exc)
            return None
