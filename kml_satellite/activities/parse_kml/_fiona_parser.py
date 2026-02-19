"""Fiona-based KML parser (primary) — Issue #60.

Parses KML files using fiona (OGR KML driver). Handles Polygon,
MultiPolygon, and GeometryCollection geometry types with graceful
degradation on individual feature validation failures (PID 7.4.2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kml_satellite.activities.parse_kml._normalization import (
    coords_to_tuples,
    extract_metadata_from_props,
)
from kml_satellite.activities.parse_kml._validation import (
    InvalidCoordinateError,
    KmlValidationError,
    validate_coordinates,
    validate_polygon_ring,
    validate_shapely_geometry,
)
from kml_satellite.models.feature import Feature

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("kml_satellite.activities.parse_kml")


def parse_with_fiona(kml_path: Path, source_filename: str) -> list[Feature]:
    """Parse KML using fiona (OGR KML driver).

    Only Polygon and MultiPolygon geometry types are extracted.
    Validation failures on individual features are logged and skipped
    (PID 7.4.2: graceful degradation).
    """
    import fiona

    features: list[Feature] = []

    with fiona.open(str(kml_path), driver="KML") as collection:
        crs_str = _extract_crs_from_fiona(collection)

        for idx, record in enumerate(collection):
            geom = record.get("geometry")
            props = record.get("properties", {}) or {}

            if geom is None:
                continue

            geom_type = geom.get("type", "")

            if geom_type == "Polygon":
                feature = _try_fiona_polygon(geom, props, source_filename, idx, crs_str)
                if feature is not None:
                    features.append(feature)

            elif geom_type == "MultiPolygon":
                coords_list = geom.get("coordinates", [])
                for sub_idx, poly_coords in enumerate(coords_list):
                    sub_geom = {"type": "Polygon", "coordinates": poly_coords}
                    feature = _try_fiona_polygon(
                        sub_geom,
                        props,
                        source_filename,
                        idx,
                        crs_str,
                        sub_index=sub_idx,
                    )
                    if feature is not None:
                        features.append(feature)

            elif geom_type == "GeometryCollection":
                geometries = geom.get("geometries", [])
                sub_idx = 0
                for sub_geom in geometries:
                    if sub_geom.get("type") == "Polygon":
                        feature = _try_fiona_polygon(
                            sub_geom,
                            props,
                            source_filename,
                            idx,
                            crs_str,
                            sub_index=sub_idx,
                        )
                        if feature is not None:
                            features.append(feature)
                        sub_idx += 1

    return features


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_fiona_polygon(
    geom: dict[str, object],
    props: dict[str, object],
    source_filename: str,
    feature_index: int,
    crs: str,
    *,
    sub_index: int | None = None,
) -> Feature | None:
    """Attempt to convert a fiona polygon, returning None on validation failure."""
    placemark_name = str(
        props.get("Name", "") or props.get("name", "") or f"Feature {feature_index}"
    )
    display_name = placemark_name
    if sub_index is not None:
        display_name = f"{placemark_name} (part {sub_index})"

    try:
        return _fiona_polygon_to_feature(
            geom,
            props,
            source_filename,
            feature_index,
            crs,
            sub_index=sub_index,
        )
    except (KmlValidationError, InvalidCoordinateError) as exc:
        logger.warning(
            "Skipping invalid feature '%s' in %s: %s",
            display_name,
            source_filename,
            exc,
        )
        return None


def _extract_crs_from_fiona(collection: object) -> str:
    """Extract CRS string from a fiona collection.

    Raises:
        KmlValidationError: If the CRS is not WGS 84.
    """
    crs = getattr(collection, "crs", None)
    if crs is None:
        return "EPSG:4326"

    epsg = getattr(crs, "to_epsg", lambda: None)()

    if epsg is not None and epsg != 4326:
        msg = f"Unexpected CRS: EPSG:{epsg} (expected EPSG:4326 for KML)"
        raise KmlValidationError(msg)

    return "EPSG:4326"


def _fiona_polygon_to_feature(
    geom: dict[str, object],
    props: dict[str, object],
    source_filename: str,
    feature_index: int,
    crs: str,
    *,
    sub_index: int | None = None,
) -> Feature | None:
    """Convert a fiona polygon geometry + properties into a Feature."""
    coords_list = geom.get("coordinates", [])
    if not isinstance(coords_list, list | tuple) or not coords_list:
        return None

    exterior_raw = coords_list[0]
    interior_raw = coords_list[1:] if len(coords_list) > 1 else []

    exterior = coords_to_tuples(exterior_raw)
    interior = [coords_to_tuples(ring) for ring in interior_raw]

    placemark_name = str(props.get("Name", "") or props.get("name", "") or "")
    description = str(props.get("Description", "") or props.get("description", "") or "")

    display_name = placemark_name or f"Feature {feature_index}"
    if sub_index is not None:
        display_name = f"{display_name} (part {sub_index})"

    validate_coordinates(exterior, display_name)
    for hole_ring in interior:
        validate_coordinates(hole_ring, f"{display_name} (hole)")

    exterior = validate_polygon_ring(exterior, display_name)
    interior = [validate_polygon_ring(ring, f"{display_name} (hole)") for ring in interior]

    validate_shapely_geometry(exterior, interior, display_name)

    metadata = extract_metadata_from_props(props)

    return Feature(
        name=placemark_name,
        description=description,
        exterior_coords=exterior,
        interior_coords=interior,
        crs=crs,
        metadata=metadata,
        source_file=source_filename,
        feature_index=feature_index,
    )
