from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.artifact_validation import validate_content


@pytest.mark.parametrize("fault", ["pixels", "nodata"])
def test_synthetic_content_rejects_readable_but_wrong_pixels(fault: str) -> None:
    from rasterio.io import MemoryFile

    from scripts.artifact_validation import validate_synthetic_raster
    from treesight.providers.stub import make_stub_geotiff

    payload = make_stub_geotiff([0, 0, 1, 1])
    validate_synthetic_raster(validate_content("raw.tif", payload))
    with MemoryFile(payload) as memory:
        with memory.open() as source:
            pixels, profile = source.read(), source.profile
    profile.pop("blockxsize", None)
    if fault == "pixels":
        pixels[:, 0, 0] = 17
    else:
        profile["nodata"] = 0
    with MemoryFile() as changed:
        with changed.open(**profile) as destination:
            destination.write(pixels)
        with pytest.raises(ValueError, match="synthetic"):
            validate_synthetic_raster(validate_content("wrong.tif", changed.read()))


@pytest.mark.parametrize("fault", ["schema", "missing-reference", "extensionless", "wrong-type", "singular"])
def test_manifest_schema_and_references_are_validated(fault: str) -> None:
    from scripts.artifact_validation import validate_manifest

    manifest = {
        "schema_version": "enrichment-manifest/v2",
        "run": {},
        "summary": {},
        "ndvi_raster_paths": ["enrichment/missing.tif"],
    }
    if fault == "schema":
        manifest["summary"] = "invalid"
    elif fault == "extensionless":
        manifest["ndvi_raster_paths"] = ["missing"]
    elif fault == "wrong-type":
        manifest["ndvi_raster_paths"] = ["meta.json"]
    elif fault == "singular":
        manifest["ndvi_raster_paths"] = []
        manifest["summary"] = {"frame_plan": [{"ndvi_raster_path": "missing"}]}
    with pytest.raises(ValueError, match="artifact"):
        validate_manifest(manifest, {"meta.json"})


def test_fixture_reconciliation_rejects_substituted_parcel(tmp_path) -> None:
    from scripts.artifact_validation import validate_fixture_metadata

    fixture = tmp_path / "fixture.kml"
    fixture.write_text(
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>A</name><Polygon>'
        "<outerBoundaryIs><LinearRing><coordinates>0,0 1,0 1,1 0,0</coordinates></LinearRing>"
        "</outerBoundaryIs></Polygon></Placemark></kml>"
    )
    with pytest.raises(ValueError, match="artifact"):
        validate_fixture_metadata([{"feature": {"name": "B", "feature_index": 0}}], fixture)


def test_json_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="artifact"):
        validate_content("metadata.json", b"[]")


@pytest.mark.parametrize("fault", ["none", "stale", "duplicate", "wrong_bounds", "manifest_missing", "manifest_error"])
def test_artifact_set_reconciles_run_parcel_and_geometry(fault: str) -> None:
    from scripts.artifact_validation import validate_artifact_set

    output = {
        "aoiCount": 1,
        "artifacts": {
            "metadataPaths": ["meta.json"],
            "rawImageryPaths": ["raw/AOI_0/one.tif"],
            "clippedImageryPaths": ["clip/AOI_0/one.tif"],
        },
        "enrichmentManifest": "manifest.json",
    }
    documents = {
        "meta.json": {
            "schema_version": "2.0.0",
            "processing_id": "run",
            "feature": {"name": "AOI_0", "feature_index": 0},
            "geometry": {"crs": "EPSG:4326", "buffered_bbox": [0, 0, 1, 1]},
        },
        "raw/AOI_0/one.tif": {"crs": "EPSG:4326", "bounds": [0, 0, 1, 1]},
        "clip/AOI_0/one.tif": {"crs": "EPSG:4326", "bounds": [0, 0, 1, 1]},
        "manifest.json": {
            "schema_version": "enrichment-manifest/v2",
            "summary": {"aoi_count": 1},
            "per_aoi_enrichment": [{"aoi_index": 0, "name": "AOI_0", "errors": []}],
        },
    }
    if fault == "stale":
        documents["meta.json"]["processing_id"] = "other-run"
    elif fault == "duplicate":
        output["artifacts"]["metadataPaths"].append("meta-copy.json")
        documents["meta-copy.json"] = deepcopy(documents["meta.json"])
    elif fault == "wrong_bounds":
        documents["clip/AOI_0/one.tif"]["bounds"] = [2, 2, 3, 3]
    elif fault == "manifest_missing":
        documents["manifest.json"]["per_aoi_enrichment"] = []
    elif fault == "manifest_error":
        documents["manifest.json"]["per_aoi_enrichment"][0]["errors"] = ["incomplete"]
    if fault == "none":
        validate_artifact_set(output, documents, "run")
    else:
        with pytest.raises(ValueError, match="artifact"):
            validate_artifact_set(output, documents, "run")
