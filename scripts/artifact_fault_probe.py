"""Exercise the strict oracle against isolated copies of real Azurite artifacts."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from rasterio.io import MemoryFile

from scripts.local_capacity import harness, verify_artifacts
from treesight.constants import LOCAL_AUDIT_MAX_ARTIFACT_BYTES


def altered_payload(payload: bytes, fault: str) -> bytes:
    if fault == "empty":
        return b""
    if fault == "corrupt":
        return b"not a raster"
    if fault == "truncated":
        return payload[:64]
    if fault in ("stale", "missing-reference"):
        document = json.loads(payload)
        if fault == "stale":
            document["processing_id"] = "another-run"
        else:
            document["ndvi_raster_paths"] = ["missing-raster"]
        return json.dumps(document).encode()
    with MemoryFile(payload) as memory, memory.open() as source:
        pixels, profile = source.read(), source.profile
    profile.pop("blockxsize", None)
    if fault == "wrong-pixels":
        pixels[:, 0, 0] = 17
    elif fault == "wrong-parcel":
        profile["transform"] = profile["transform"] * profile["transform"].translation(500, 500)
    else:
        raise ValueError(f"unknown fault: {fault}")
    with MemoryFile() as memory:
        with memory.open(**profile) as destination:
            destination.write(pixels)
        return memory.read()


def run_probes(result: dict) -> dict:
    report: dict = {"instanceId": result["instanceId"], "healthyVerifiedBlobs": verify_artifacts(result), "probes": []}
    prefix = f"artifact-fault-probe/{uuid4()}"
    with BlobServiceClient.from_connection_string(harness.AZURITE_CONN_STR) as service:
        container = service.get_container_client("kml-output")
        for fault in (
            "corrupt",
            "empty",
            "truncated",
            "wrong-pixels",
            "wrong-parcel",
            "stale",
            "missing-reference",
            "missing",
        ):
            case = deepcopy(result)
            output = case["output"]
            group = "metadataPaths" if fault == "stale" else "rawImageryPaths"
            original = output["enrichmentManifest"] if fault == "missing-reference" else output["artifacts"][group][0]
            path = f"{prefix}/{fault}/{original}"
            if fault == "missing-reference":
                output["enrichmentManifest"] = path
            else:
                output["artifacts"][group][0] = path
            created = False
            try:
                if fault != "missing":
                    payload = container.download_blob(
                        original, offset=0, length=LOCAL_AUDIT_MAX_ARTIFACT_BYTES + 1
                    ).readall()
                    container.upload_blob(path, altered_payload(payload, fault), overwrite=False)
                    created = True
                try:
                    verify_artifacts(case)
                except (ValueError, ResourceNotFoundError) as exc:
                    report["probes"].append({"fault": fault, "rejected": True, "reason": str(exc).splitlines()[0]})
                else:
                    raise AssertionError(f"oracle accepted injected {fault}")
            finally:
                if created:
                    container.delete_blob(path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_probes(json.loads(args.control.read_text())["result"])
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
