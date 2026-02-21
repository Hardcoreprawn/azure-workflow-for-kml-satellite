"""Pydantic metadata model conforming to PID Section 9.2.

Defines the per-AOI metadata JSON schema for the KML satellite imagery
pipeline.  This is the "flight recorder" for each processed polygon:
what was requested, what was received, how it was processed.

The schema is split into three nested sections:
- **geometry**: Polygon coordinates, bbox, buffered bbox, area, centroid
- **imagery**: Provider details, scene metadata (populated during M-2.x)
- **processing**: Pipeline execution details, timing, status

Engineering standards:
- PID 7.4.4: Idempotent and deterministic — same input produces same output
- PID 7.4.5: Explicit units — hectares, metres, EPSG codes
- PID 7.4.6: Observability — metadata is the audit trail

References:
- PID Section 9.2 (Metadata JSON Schema)
- PID FR-4.4, FR-4.6, FR-4.7
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

# Schema version for forward compatibility (PID 7.4.5: explicit)
SCHEMA_VERSION = "aoi-metadata-v1"


class GeometryMetadata(BaseModel):
    """Geometry section of the per-AOI metadata.

    Contains the polygon coordinates, bounding boxes, area, and centroid.
    All coordinates are WGS 84 (EPSG:4326).

    Attributes:
        type: GeoJSON geometry type, always ``"Polygon"``.
        coordinates: GeoJSON-style nested coordinate arrays
            ``[exterior_ring, *interior_rings]`` where each ring is a list
            of ``[lon, lat]`` pairs.
        centroid: Polygon centroid as ``[lon, lat]``.
        bounding_box: Tight bounding box
            ``[min_lon, min_lat, max_lon, max_lat]``.
        buffered_bounding_box: Bounding box expanded by ``buffer_m`` metres.
        area_hectares: Geodesic polygon area in hectares (PID 7.4.5).
        crs: Coordinate reference system EPSG code.
    """

    type: str = "Polygon"
    coordinates: list[list[list[float]]] = Field(default_factory=list)
    centroid: list[float] = Field(default_factory=list)
    bounding_box: list[float] = Field(default_factory=list)
    buffered_bounding_box: list[float] = Field(default_factory=list)
    area_hectares: float = 0.0
    crs: str = "EPSG:4326"


class ImageryMetadata(BaseModel):
    """Imagery section of the per-AOI metadata.

    Populated during imagery acquisition (M-2.x).  All fields default
    to empty/zero for the M-1.6 milestone — the schema is defined now
    so metadata JSON is always structurally complete.

    Attributes:
        provider: Imagery provider name (e.g. ``"maxar"``, ``"planet"``).
        scene_id: Provider-specific scene identifier.
        acquisition_date: Scene acquisition timestamp (ISO 8601).
        spatial_resolution_m: Ground sample distance in metres.
        crs: Scene CRS EPSG code (may differ from AOI CRS after reproject).
        cloud_cover_pct: Cloud cover percentage over the AOI.
        off_nadir_angle_deg: Off-nadir viewing angle in degrees.
        format: Image file format (e.g. ``"GeoTIFF"``).
        raw_blob_path: Blob path to the raw (unclipped) imagery.
        clipped_blob_path: Blob path to the clipped imagery.
    """

    provider: str = ""
    scene_id: str = ""
    acquisition_date: str | None = None
    spatial_resolution_m: float = 0.0
    crs: str = ""
    cloud_cover_pct: float = 0.0
    off_nadir_angle_deg: float = 0.0
    format: str = ""
    raw_blob_path: str = ""
    clipped_blob_path: str = ""


class ProcessingMetadata(BaseModel):
    """Processing section of the per-AOI metadata.

    Records how the AOI was processed: buffer distance, clipping status,
    timing, and any errors.

    Attributes:
        buffer_m: Buffer distance applied in metres.
        clipped: Whether the imagery was clipped to the AOI polygon.
        reprojected: Whether the imagery was reprojected.
        timestamp: Processing timestamp (ISO 8601).
        duration_s: Total processing duration in seconds.
        status: Processing status (``"success"``, ``"partial"``, ``"failed"``).
        errors: List of error messages encountered during processing.
    """

    buffer_m: float = 100.0
    clipped: bool = False
    reprojected: bool = False
    timestamp: str = ""
    duration_s: float = 0.0
    status: str = "pending"
    errors: list[str] = Field(default_factory=list)


class AOIMetadataRecord(BaseModel):
    """Top-level per-AOI metadata record (PID Section 9.2).

    This is the complete JSON document written to
    ``/metadata/{YYYY}/{MM}/{orchard-name}/{feature-name}.json``.

    Attributes:
        schema_version: Schema identifier for forward compatibility.
        processing_id: Orchestration instance ID (PID 7.4.4: traceability).
        kml_filename: Name of the source KML file.
        feature_name: Name of the feature / Placemark.
        project_name: Project name (from metadata or filename).
        tree_variety: Tree/crop variety (from KML ExtendedData, if present).
        geometry: Polygon geometry and derived measurements.
        imagery: Imagery acquisition details (populated in M-2.x).
        processing: Pipeline execution details.
    """

    schema_version: str = Field(default=SCHEMA_VERSION, alias="$schema")
    processing_id: str = ""
    kml_filename: str = ""
    feature_name: str = ""
    project_name: str = ""
    tree_variety: str = ""
    geometry: GeometryMetadata = Field(default_factory=GeometryMetadata)
    imagery: ImageryMetadata = Field(default_factory=ImageryMetadata)
    processing: ProcessingMetadata = Field(default_factory=ProcessingMetadata)

    model_config = {"populate_by_name": True}

    @classmethod
    def from_aoi(
        cls,
        aoi: object,
        *,
        processing_id: str = "",
        timestamp: str = "",
    ) -> AOIMetadataRecord:
        """Construct a metadata record from an AOI dataclass.

        This is the primary factory method, called by the ``write_metadata``
        activity after the ``prepare_aoi`` activity completes.

        Args:
            aoi: An ``AOI`` dataclass instance (from ``kml_satellite.models.aoi``).
            processing_id: Orchestration instance ID.
            timestamp: Processing timestamp (ISO 8601).  If empty, uses
                the current UTC time.

        Returns:
            A fully populated ``AOIMetadataRecord``.
        """
        from kml_satellite.models.aoi import AOI as AOIModel  # noqa: N811

        if not isinstance(aoi, AOIModel):
            msg = f"Expected AOI instance, got {type(aoi).__name__}"
            raise TypeError(msg)

        if not timestamp:
            timestamp = datetime.now(UTC).isoformat()

        # Build GeoJSON-style coordinates: [exterior, *holes]
        coords: list[list[list[float]]] = [
            [list(c) for c in aoi.exterior_coords],
        ]
        for ring in aoi.interior_coords:
            coords.append([list(c) for c in ring])

        # Extract project name from metadata, or derive from source file
        project_name = _extract_project_name(aoi.metadata, aoi.source_file)
        tree_variety = aoi.metadata.get("tree_variety", "")

        return cls(
            processing_id=processing_id,
            kml_filename=aoi.source_file,
            feature_name=aoi.feature_name,
            project_name=project_name,
            tree_variety=tree_variety,
            geometry=GeometryMetadata(
                type="Polygon",
                coordinates=coords,
                centroid=list(aoi.centroid),
                bounding_box=list(aoi.bbox),
                buffered_bounding_box=list(aoi.buffered_bbox),
                area_hectares=aoi.area_ha,
                crs=aoi.crs,
            ),
            processing=ProcessingMetadata(
                buffer_m=aoi.buffer_m,
                timestamp=timestamp,
                status="metadata_written",
            ),
        )

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise to a JSON string.

        Uses the ``$schema`` alias for the schema version field.
        """
        return self.model_dump_json(indent=indent, by_alias=True)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a plain dict (for Durable Functions transport)."""
        return self.model_dump(by_alias=True)  # type: ignore[return-value]


def _extract_project_name(
    metadata: dict[str, str],
    source_file: str,
) -> str:
    """Derive the project name from metadata or the filename.

    Tries (in order):
    1. ``metadata["project_name"]``
    2. ``metadata["orchard_name"]`` (backward compatibility)
    3. KML filename stem (without extension), sanitised

    Args:
        metadata: Key-value metadata from the KML feature.
        source_file: Name of the source KML file.

    Returns:
        A non-empty project name string.
    """
    for key in ("project_name", "orchard_name"):
        value = metadata.get(key, "").strip()
        if value:
            return value

    # Fall back to sanitised filename stem
    if source_file:
        from pathlib import PurePosixPath

        stem = PurePosixPath(source_file).stem
        return stem if stem else "unknown"

    return "unknown"
