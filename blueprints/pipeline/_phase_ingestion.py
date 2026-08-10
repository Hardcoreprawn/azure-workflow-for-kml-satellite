"""Orchestrator phase 1 — ingestion: parse KML, fan-out AOI prep, claim-check store.

Extracted from orchestrator.py (#1292). No behavior change from the extraction.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from collections.abc import Generator
from typing import Any

import azure.durable_functions as df

from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_OUTPUT_CONTAINER
from treesight.pipeline.contracts import (
    ensure_list_of_dicts,
    ensure_nonempty_str_field,
    ensure_parse_kml_output,
)

from ._payloads import _collect_enrichment_coords, _collect_per_aoi_coords

_PhaseGen = Generator[Any, Any, dict[str, Any]]


def _phase_ingestion(
    context: df.DurableOrchestrationContext,
    inp: dict[str, Any],
    instance_id: str,
    ctx: dict[str, str],
) -> _PhaseGen:
    """Parse KML, fan-out AOI preparation, store claims, write metadata."""
    blob_name = inp.get("blob_name", "")

    context.set_custom_status({"phase": "ingestion", "step": "parsing_kml"})
    features = ensure_parse_kml_output((yield context.call_activity("parse_kml", inp)))

    if isinstance(features, list):
        feature_list = features
        offloaded = False
    else:
        loaded = ensure_list_of_dicts(
            (yield context.call_activity("load_offloaded_features", features)),
            name="load_offloaded_features",
        )
        feature_list = loaded
        offloaded = True

    # Gate: enforce tier's aoi_limit before expensive fan-out
    from treesight.pipeline.ingestion import enforce_aoi_limit

    enforce_aoi_limit(feature_count=len(feature_list), tier=inp.get("tier"))

    # Fan-out: prepare AOIs
    context.set_custom_status({"phase": "ingestion", "step": "preparing_aois", "features": len(feature_list)})
    aoi_tasks = [
        context.call_activity("prepare_aoi", {"feature": f, "buffer_m": inp.get("buffer_m")}) for f in feature_list
    ]
    aois = ensure_list_of_dicts((yield context.task_all(aoi_tasks)), name="prepare_aoi")

    # Claim-check: extract enrichment coords before offloading AOIs
    all_coords = _collect_enrichment_coords(aois)
    per_aoi_coords = _collect_per_aoi_coords(aois)

    # Extract area_ha per AOI for batch routing (before claim-check offload)
    aoi_area_by_name: dict[str, float] = {a.get("feature_name", ""): a.get("area_ha", 0.0) for a in aois}

    # Extract centroids for pipeline telemetry spread calculation (#400).
    # [0.0, 0.0] is treesight.geo.centroid's placeholder for a missing/empty
    # polygon (see blueprints/monitoring.py's identical check) -- including it
    # would wildly inflate max_spread_km with a fake distance to Null Island.
    aoi_centroids: list[list[float]] = [
        a["centroid"] for a in aois if a.get("centroid") and len(a["centroid"]) == 2 and a["centroid"] != [0.0, 0.0]
    ]

    # Claim-check: store full AOI dicts in blob storage, get lightweight refs
    context.set_custom_status({"phase": "ingestion", "step": "storing_claims", "aois": len(aois)})
    aoi_refs = ensure_list_of_dicts(
        (
            yield context.call_activity(
                "store_aoi_claims",
                {"instance_id": instance_id, "aois": aois},
            )
        ),
        name="store_aoi_claims",
        required_item_keys=("ref", "key"),
    )
    for index, ref in enumerate(aoi_refs):
        ensure_nonempty_str_field(ref["ref"], name="store_aoi_claims", field="ref", index=index)
        ensure_nonempty_str_field(ref["key"], name="store_aoi_claims", field="key", index=index)
    # Fan-out: write metadata (activities retrieve AOI from claim check)
    meta_tasks = [
        context.call_activity(
            "write_metadata",
            {
                "aoi_ref": ref["ref"],
                "processing_id": instance_id,
                "timestamp": ctx["timestamp"],
                "tenant_id": inp.get("tenant_id", ""),
                "source_file": blob_name,
                "output_container": inp.get("output_container", DEFAULT_OUTPUT_CONTAINER),
                "input_container": inp.get("container_name", DEFAULT_INPUT_CONTAINER),
            },
        )
        for ref in aoi_refs
    ]
    metadata_results = ensure_list_of_dicts(
        (yield context.task_all(meta_tasks)),
        name="write_metadata",
    )

    return {
        "ingestion": {
            "feature_count": len(feature_list),
            "offloaded": offloaded,
            "aoi_refs": aoi_refs,
            "aoi_count": len(aoi_refs),
            "metadata_results": metadata_results,
            "metadata_count": len(metadata_results),
        },
        "aoi_refs": aoi_refs,
        "all_coords": all_coords,
        "per_aoi_coords": per_aoi_coords,
        "aoi_area_by_name": aoi_area_by_name,
        "aoi_centroids": aoi_centroids,
    }
