"""Phase 1 — Ingestion logic (§3.1).

Pure business logic, no Azure Functions dependencies.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from treesight import __version__
from treesight.constants import AOI_METADATA_SCHEMA, AOI_METADATA_SCHEMA_VERSION
from treesight.geo import prepare_aoi
from treesight.log import log_phase
from treesight.models.aoi import AOI
from treesight.models.blob_event import BlobEvent
from treesight.models.feature import Feature
from treesight.storage.client import BlobStorageClient

logger = logging.getLogger(__name__)


def parse_kml_from_blob(blob_event: BlobEvent, storage: BlobStorageClient) -> list[Feature]:
    """Download KML/KMZ from blob storage and parse it."""
    from treesight.parsers import maybe_unzip

    raw_bytes = storage.download_bytes(blob_event.container_name, blob_event.blob_name)
    kml_bytes = maybe_unzip(raw_bytes)
    source_file = PurePosixPath(blob_event.blob_name).name

    # Try Fiona first, fall back to lxml
    try:
        from treesight.parsers.fiona_parser import parse_kml_fiona

        features = parse_kml_fiona(kml_bytes, source_file=source_file)
    except Exception:
        logger.warning(
            "Fiona parser failed for %s, falling back to lxml",
            blob_event.blob_name,
            exc_info=True,
        )
        from treesight.parsers.lxml_parser import parse_kml_lxml

        features = parse_kml_lxml(kml_bytes, source_file=source_file)

    log_phase("ingestion", "parse_kml", feature_count=len(features), blob_name=blob_event.blob_name)
    return features


def prepare_aois(features: list[Feature], buffer_m: float | None = None) -> list[AOI]:
    """Fan-out: prepare AOI for each feature."""
    aois = [prepare_aoi(f, buffer_m=buffer_m) for f in features]
    log_phase("ingestion", "prepare_aois", aoi_count=len(aois))
    return aois


def write_metadata(
    aoi: AOI,
    processing_id: str,
    timestamp: str,
    tenant_id: str,
    source_file: str,
    output_container: str,
    storage: BlobStorageClient,
    kml_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Write AOI metadata JSON and archive KML."""
    project_name = PurePosixPath(source_file).stem
    ts = timestamp or datetime.now(UTC).isoformat()

    metadata_doc: dict[str, Any] = {
        "$schema": AOI_METADATA_SCHEMA,
        "schema_version": AOI_METADATA_SCHEMA_VERSION,
        "processing_id": processing_id,
        "timestamp": ts,
        "tenant_id": tenant_id,
        "feature": {
            "name": aoi.feature_name,
            "source_file": aoi.source_file,
            "feature_index": aoi.feature_index,
            "description": "",
        },
        "geometry": {
            "crs": aoi.crs,
            "bbox": aoi.bbox,
            "buffered_bbox": aoi.buffered_bbox,
            "centroid": aoi.centroid,
            "area_ha": aoi.area_ha,
            "buffer_m": aoi.buffer_m,
            "exterior_ring_vertex_count": len(aoi.exterior_coords),
            "interior_ring_count": len(aoi.interior_coords),
            "area_warning": aoi.area_warning,
        },
        "extended_data": aoi.metadata,
        "analysis": {
            "source": "kml_satellite",
            "pipeline_version": __version__,
        },
    }

    safe_name = aoi.feature_name.replace(" ", "_").replace("/", "_")
    metadata_path = f"metadata/{project_name}/{ts}/{safe_name}.json"
    storage.upload_json(output_container, metadata_path, metadata_doc)

    kml_archive_path = f"kml/{project_name}/{ts}/{source_file}"
    if kml_bytes:
        storage.upload_bytes(
            output_container,
            kml_archive_path,
            kml_bytes,
            content_type="application/vnd.google-earth.kml+xml",
        )

    log_phase("ingestion", "write_metadata", metadata_path=metadata_path)
    return {
        "metadata": metadata_doc,
        "metadata_path": metadata_path,
        "kml_archive_path": kml_archive_path,
    }
