"""Bounded content checks for local synthetic reliability exercises."""

from __future__ import annotations

import json
from collections import Counter
from functools import cache
from pathlib import Path, PurePosixPath

import numpy as np
from rasterio.errors import RasterioIOError
from rasterio.io import MemoryFile

from treesight.constants import (
    LOCAL_AUDIT_BOUNDS_TOLERANCE,
    LOCAL_AUDIT_MAX_ARTIFACT_BYTES,
    LOCAL_AUDIT_MAX_RASTER_VALUES,
)
from treesight.models.enrichment_manifest import EnrichmentManifestV2
from treesight.parsers.lxml_parser import parse_kml_lxml
from treesight.providers.stub import make_stub_geotiff


def validate_content(path: str, payload: bytes) -> dict:
    if not payload or len(payload) > LOCAL_AUDIT_MAX_ARTIFACT_BYTES:
        raise ValueError(f"artifact outside byte limit: {path}")
    if PurePosixPath(path).suffix == ".json":
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"invalid JSON artifact: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"expected object artifact: {path}")
        return value
    if PurePosixPath(path).suffix != ".tif":
        raise ValueError(f"unsupported artifact format: {path}")
    try:
        with MemoryFile(payload) as memory, memory.open() as raster:
            if not raster.crs or not 0 < raster.width * raster.height * raster.count <= LOCAL_AUDIT_MAX_RASTER_VALUES:
                raise ValueError(f"invalid raster artifact shape or CRS: {path}")
            pixels = raster.read(masked=True)
            if not pixels.count() or not np.isfinite(pixels.compressed()).all():
                raise ValueError(f"invalid raster artifact pixels: {path}")
            return {
                "bounds": list(raster.bounds),
                "crs": raster.crs.to_string(),
                "shape": [raster.count, raster.height, raster.width],
                "dtypes": list(raster.dtypes),
                "nodata": raster.nodata,
                "minimum": float(pixels.min()),
                "maximum": float(pixels.max()),
                "validValues": int(pixels.count()),
            }
    except RasterioIOError as exc:
        raise ValueError(f"invalid raster artifact: {path}") from exc


def validate_artifact_set(output: dict, documents: dict[str, dict], instance_id: str) -> None:
    metadata = [documents[path] for path in output["artifacts"]["metadataPaths"]]
    try:
        identities = [(item["feature"]["feature_index"], item["feature"]["name"]) for item in metadata]
        expected_indices = set(range(output["aoiCount"]))
        if len(identities) != len(expected_indices) or {index for index, _ in identities} != expected_indices:
            raise ValueError("artifact metadata parcel set mismatch")
        if any(item["schema_version"] != "2.0.0" or item["processing_id"] != instance_id for item in metadata):
            raise ValueError("artifact metadata schema or run mismatch")
        manifest = documents[output["enrichmentManifest"]]
        aois = manifest["per_aoi_enrichment"]
        actual = [(aoi["aoi_index"], aoi["name"]) for aoi in aois]
        if manifest["schema_version"] != "enrichment-manifest/v2" or manifest["summary"]["aoi_count"] != len(metadata):
            raise ValueError("artifact manifest schema or count mismatch")
        if len(actual) != len(identities) or set(actual) != set(identities) or any(aoi["errors"] for aoi in aois):
            raise ValueError("artifact manifest parcel mismatch or enrichment error")
        _validate_raster_associations(output, documents, metadata)
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed artifact schema") from exc


def _validate_raster_associations(output: dict, documents: dict[str, dict], metadata: list[dict]) -> None:
    parcels = {item["feature"]["name"]: item for item in metadata}
    if len(parcels) != len(metadata):
        raise ValueError("artifact fixture names must be unique for path reconciliation")
    for group in ("rawImageryPaths", "clippedImageryPaths"):
        paths = output["artifacts"][group]
        observed = {PurePosixPath(path).parent.name for path in paths}
        if observed != set(parcels):
            raise ValueError("artifact raster parcel set mismatch")
        for path in paths:
            geometry = parcels[PurePosixPath(path).parent.name]["geometry"]
            raster = documents[path]
            if raster["crs"] != geometry["crs"] or not np.allclose(
                raster["bounds"], geometry["buffered_bbox"], rtol=0, atol=LOCAL_AUDIT_BOUNDS_TOLERANCE
            ):
                raise ValueError(f"artifact raster geometry mismatch: {path}")
    raw = {PurePosixPath(path).parts[-2:] for path in output["artifacts"]["rawImageryPaths"]}
    clipped = {PurePosixPath(path).parts[-2:] for path in output["artifacts"]["clippedImageryPaths"]}
    if raw != clipped:
        raise ValueError("artifact raw/clipped scene mismatch")


def validate_fixture_metadata(metadata: list[dict], fixture: Path) -> None:
    features = parse_kml_lxml(fixture.read_bytes(), source_file=fixture.name)
    expected = {(feature.feature_index, feature.name): feature for feature in features}
    actual = {(item["feature"]["feature_index"], item["feature"]["name"]): item for item in metadata}
    if len(actual) != len(metadata) or set(actual) != set(expected):
        raise ValueError("artifact identities differ from submitted fixture")
    for identity, feature in expected.items():
        coords = np.asarray(feature.exterior_coords)
        bounds = [*coords.min(axis=0), *coords.max(axis=0)]
        if not np.allclose(actual[identity]["geometry"]["bbox"], bounds, rtol=0, atol=LOCAL_AUDIT_BOUNDS_TOLERANCE):
            raise ValueError("artifact geometry differs from submitted fixture")


def validate_fixture_outputs(output: dict, documents: dict[str, dict], fixture: Path) -> None:
    metadata = [documents[path] for path in output["artifacts"]["metadataPaths"]]
    validate_fixture_metadata(metadata, fixture)
    expected = {item["feature"]["name"]: 7 for item in metadata}
    for group in ("rawImageryPaths", "clippedImageryPaths"):
        counts = Counter(PurePosixPath(path).parent.name for path in output["artifacts"][group])
        if counts != expected:
            raise ValueError("artifact per-parcel scene count mismatch")
        for path in output["artifacts"][group]:
            validate_synthetic_raster(documents[path])
    manifest_path = PurePosixPath(output["enrichmentManifest"])
    run = documents[str(manifest_path)].get("run", {})
    if run.get("project_name") != fixture.stem or run.get("timestamp") != manifest_path.parent.name:
        raise ValueError("artifact manifest run identity mismatch")
    validate_manifest(documents[str(manifest_path)], set(documents))


@cache
def _synthetic_signature() -> dict:
    return validate_content("expected.tif", make_stub_geotiff())


def validate_synthetic_raster(document: dict) -> None:
    expected = _synthetic_signature()
    fields = ("shape", "dtypes", "nodata", "minimum", "maximum", "validValues")
    if any(document.get(field) != expected[field] for field in fields):
        raise ValueError("artifact differs from expected synthetic raster content")


def validate_manifest(manifest: dict, verified_paths: set[str]) -> None:
    try:
        EnrichmentManifestV2.model_validate(manifest)
    except ValueError as exc:
        raise ValueError("invalid artifact manifest schema") from exc
    pending = [manifest]
    for _ in range(LOCAL_AUDIT_MAX_ARTIFACT_BYTES):
        if not pending:
            return
        value = pending.pop()
        if isinstance(value, dict):
            _validate_raster_references(value.get("ndvi_raster_paths", []), verified_paths)
            _validate_raster_references([value.get("ndvi_raster_path"), value.get("artifact_path")], verified_paths)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and value.endswith((".tif", ".json")) and value not in verified_paths:
            raise ValueError(f"unverified artifact manifest reference: {value}")
    raise ValueError("artifact manifest exceeds validation budget")


def _validate_raster_references(paths: list, verified_paths: set[str]) -> None:
    if not isinstance(paths, list):
        raise ValueError("invalid artifact raster reference list")
    for path in paths:
        if path is not None and (not isinstance(path, str) or not path.endswith(".tif") or path not in verified_paths):
            raise ValueError("unverified artifact raster reference")
