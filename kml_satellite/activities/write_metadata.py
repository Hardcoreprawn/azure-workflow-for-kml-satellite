"""Write metadata activity — generate and store per-AOI metadata JSON.

This activity takes a processed AOI and an orchestration context, builds
a metadata JSON document conforming to PID Section 9.2, writes it to
Blob Storage at the deterministic path, and optionally archives the
original KML file.

Engineering standards:
- PID 7.4.4 Idempotent: same input produces same output path (overwrites)
- PID 7.4.5 Explicit: typed models, named constants, explicit units
- PID 7.4.6 Observability: structured logging at activity boundaries (FR-2.3)
- PID 7.4.8 Hamilton Standard: defensive validation, no silent failures

References:
- PID FR-4.4 (metadata stored under /metadata/ prefix)
- PID FR-4.6 (metadata JSON per AOI)
- PID FR-4.7 (storage hierarchy by date/orchard)
- PID Section 9.2 (Metadata JSON Schema)
- PID Section 10.1 (Container & Path Layout)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kml_satellite.core.constants import OUTPUT_CONTAINER
from kml_satellite.models.metadata import AOIMetadataRecord
from kml_satellite.utils.blob_paths import build_metadata_path

if TYPE_CHECKING:
    from kml_satellite.models.aoi import AOI

from kml_satellite.core.exceptions import PipelineError

logger = logging.getLogger("kml_satellite.activities.write_metadata")


class MetadataWriteError(PipelineError):
    """Raised when metadata writing fails."""

    default_stage = "write_metadata"
    default_code = "METADATA_WRITE_FAILED"


def write_metadata(
    aoi: AOI,
    *,
    processing_id: str = "",
    timestamp: str = "",
    blob_service_client: object | None = None,
) -> dict[str, object]:
    """Build and store a metadata JSON document for a processed AOI.

    Args:
        aoi: A processed AOI from the ``prepare_aoi`` activity.
        processing_id: Orchestration instance ID for traceability (PID 7.4.4).
        timestamp: Processing timestamp (ISO 8601). Defaults to current UTC.
        blob_service_client: Optional ``BlobServiceClient`` for writing to
            Blob Storage.  If ``None``, metadata is built and returned
            without writing (useful for testing and local dev).

    Returns:
        A dict containing:
        - ``metadata``: The full metadata record as a dict
        - ``metadata_path``: The blob path where metadata was (or would be) written
        - ``kml_archive_path``: The blob path for the KML archive

    Raises:
        MetadataWriteError: If blob upload fails.
    """
    if not timestamp:
        timestamp = datetime.now(UTC).isoformat()

    # Parse timestamp for path generation
    try:
        ts = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        ts = datetime.now(UTC)
        timestamp = ts.isoformat()

    # Build the metadata record (PID Section 9.2)
    record = AOIMetadataRecord.from_aoi(aoi, processing_id=processing_id, timestamp=timestamp)

    # Extract orchard name for path generation
    orchard_name = record.orchard_name

    # Build deterministic blob paths (PID 7.4.4, Section 10.1)
    metadata_path = build_metadata_path(
        aoi.feature_name,
        orchard_name,
        timestamp=ts,
    )

    from kml_satellite.utils.blob_paths import build_kml_archive_path

    kml_archive_path = build_kml_archive_path(
        aoi.source_file,
        orchard_name,
        timestamp=ts,
    )

    # Serialise to JSON
    metadata_json = record.to_json()

    # Write to Blob Storage if a client is provided
    if blob_service_client is not None:
        _upload_metadata(blob_service_client, metadata_path, metadata_json)

    logger.info(
        "Metadata written | feature=%s | path=%s | processing_id=%s",
        aoi.feature_name,
        metadata_path,
        processing_id,
    )

    return {
        "metadata": record.to_dict(),
        "metadata_path": metadata_path,
        "kml_archive_path": kml_archive_path,
    }


def _upload_metadata(
    blob_service_client: object,
    metadata_path: str,
    metadata_json: str,
) -> None:
    """Upload metadata JSON to Blob Storage.

    Uses overwrite=True for idempotent writes (PID 7.4.4).

    Args:
        blob_service_client: An Azure ``BlobServiceClient`` instance.
        metadata_path: Blob path within the output container.
        metadata_json: Serialised JSON string.

    Raises:
        MetadataWriteError: If the upload fails.
    """
    try:
        from azure.storage.blob import BlobServiceClient

        if not isinstance(blob_service_client, BlobServiceClient):
            msg = f"Expected BlobServiceClient, got {type(blob_service_client).__name__}"
            raise MetadataWriteError(msg)

        blob_client = blob_service_client.get_blob_client(
            container=OUTPUT_CONTAINER,
            blob=metadata_path,
        )
        blob_client.upload_blob(
            metadata_json.encode("utf-8"),
            overwrite=True,  # PID 7.4.4: idempotent writes
        )
    except MetadataWriteError:
        raise
    except Exception as exc:
        msg = f"Failed to upload metadata to {metadata_path}: {exc}"
        raise MetadataWriteError(msg) from exc
