"""Primary KML parser using Fiona/GDAL (§7.1)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

from treesight.log import logger
from treesight.models.feature import Feature
from treesight.parsers import ensure_closed as _ensure_closed

_NAME_KEYS = frozenset({"name", "description"})


def parse_kml_fiona(kml_bytes: bytes, source_file: str = "") -> list[Feature]:
    """Parse KML bytes using Fiona (GDAL driver). Returns list of Features."""
    import fiona  # type: ignore[import-untyped]

    features: list[Feature] = []

    with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
        tmp.write(kml_bytes)
        tmp_path = tmp.name

    try:
        with fiona.open(tmp_path, driver="KML") as src:  # pyright: ignore[reportUnknownMemberType]
            for idx, record in enumerate(cast(list[dict[str, Any]], src)):
                geom: dict[str, Any] = record.get("geometry", {})
                props: dict[str, Any] = record.get("properties", {})
                geom_type: str = str(geom.get("type", ""))

                if geom_type == "Polygon":
                    features.append(_polygon_to_feature(geom, props, source_file, len(features)))
                elif geom_type == "MultiPolygon":
                    for poly_coords in geom.get("coordinates", []):
                        features.append(
                            _multi_polygon_part_to_feature(
                                poly_coords, props, source_file, len(features)
                            )
                        )
                else:
                    logger.warning(
                        "Skipping non-polygon geometry type=%s index=%d",
                        geom_type,
                        idx,
                    )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return features


def _extract_name_description(
    props: dict[str, Any],
    index: int,
) -> tuple[str, str]:
    """Extract name and description from feature properties."""
    name = str(props.get("Name") or props.get("name") or f"Unnamed Feature {index}")
    description = str(props.get("Description") or props.get("description") or "")
    return name, description


def _extract_metadata(props: dict[str, Any]) -> dict[str, str]:
    """Extract non-name/description properties as string metadata."""
    return {k: str(v) for k, v in props.items() if k.lower() not in _NAME_KEYS and v is not None}


def _coords_to_feature(
    rings: list[Any],
    props: dict[str, Any],
    source_file: str,
    index: int,
) -> Feature:
    """Build a Feature from a list of coordinate rings [exterior, *interiors]."""
    exterior = _normalise_ring(rings[0]) if rings else []
    interior = [_normalise_ring(ring) for ring in rings[1:]] if len(rings) > 1 else []

    name, description = _extract_name_description(props, index)
    metadata = _extract_metadata(props)
    exterior = _ensure_closed(exterior)

    return Feature(
        name=name,
        description=description,
        exterior_coords=exterior,
        interior_coords=interior,
        crs="EPSG:4326",
        metadata=metadata,
        source_file=source_file,
        feature_index=index,
    )


def _polygon_to_feature(
    geom: dict[str, Any],
    props: dict[str, Any],
    source_file: str,
    index: int,
) -> Feature:
    """Convert a Fiona Polygon geometry dict to a Feature."""
    return _coords_to_feature(geom.get("coordinates", []), props, source_file, index)


def _multi_polygon_part_to_feature(
    poly_coords: list[Any],
    props: dict[str, Any],
    source_file: str,
    index: int,
) -> Feature:
    """Convert a single polygon part from a MultiPolygon to a Feature."""
    return _coords_to_feature(poly_coords, props, source_file, index)


def _normalise_ring(ring: list[Any]) -> list[list[float]]:
    """Convert coordinate tuples to [lon, lat], discarding altitude."""
    normalised: list[list[float]] = []
    for coord in ring:
        if len(coord) >= 2:
            normalised.append([float(coord[0]), float(coord[1])])
    return normalised
