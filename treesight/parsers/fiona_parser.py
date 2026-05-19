"""Primary KML parser using Fiona/GDAL (§7.1)."""

from __future__ import annotations

import concurrent.futures
import os
import tempfile
from pathlib import Path
from typing import Any, cast

# Disable PROJ network access and cap GDAL HTTP before fiona/GDAL initialises.
# Without these, GDAL silently blocks on network calls (datum grid downloads,
# schema validation) for minutes to hours when container egress is restricted.
os.environ.setdefault("PROJ_NETWORK", "OFF")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "30")
os.environ.setdefault("GDAL_MAX_HTTP_RETRY", "0")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

from treesight.log import logger
from treesight.models.feature import Feature
from treesight.parsers import ensure_closed as _ensure_closed

_NAME_KEYS = frozenset({"name", "description"})
_FIONA_TIMEOUT_SECONDS = 60


def _fiona_open_and_collect(tmp_path: str, source_file: str) -> list[dict[str, Any]]:
    """Open the KML via Fiona and collect raw record dicts. Runs in a worker thread."""
    import fiona  # type: ignore[import-untyped]  — fiona has no py.typed / type stubs

    records: list[dict[str, Any]] = []
    with fiona.open(tmp_path, driver="KML") as src:  # pyright: ignore[reportUnknownMemberType]
        for record in cast(list[dict[str, Any]], src):
            records.append(record)
    return records


def parse_kml_fiona(kml_bytes: bytes, source_file: str = "") -> list[Feature]:
    """Parse KML bytes using Fiona (GDAL driver). Returns list of Features."""
    features: list[Feature] = []

    with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
        tmp.write(kml_bytes)
        tmp_path = tmp.name

    try:
        logger.info(
            "fiona_parser: opening source=%s bytes=%d timeout=%ds",
            source_file or "inline",
            len(kml_bytes),
            _FIONA_TIMEOUT_SECONDS,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_fiona_open_and_collect, tmp_path, source_file)
            try:
                records = future.result(timeout=_FIONA_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError as exc:
                raise TimeoutError(
                    f"Fiona/GDAL parse timed out after {_FIONA_TIMEOUT_SECONDS}s "
                    f"for {source_file!r} — GDAL may be making a blocked network call"
                ) from exc

        for idx, record in enumerate(records):
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
                    "fiona_parser: skipping non-polygon type=%s index=%d source=%s",
                    geom_type,
                    idx,
                    source_file,
                )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    logger.info(
        "fiona_parser: done source=%s features=%d",
        source_file or "inline",
        len(features),
    )
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
    interior = [_ensure_closed(ring) for ring in interior]

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
