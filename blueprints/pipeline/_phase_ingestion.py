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
        feature_count = len(features)
        prepare_inputs = [{"feature": feature} for feature in features]
        offloaded = False
    else:
        feature_count = features["count"]
        prepare_inputs = [{"features_ref": features["ref"], "feature_index": index} for index in range(feature_count)]
        offloaded = True

    # Gate: enforce tier's aoi_limit before expensive fan-out
    from treesight.pipeline.ingestion import enforce_aoi_limit

    enforce_aoi_limit(feature_count=feature_count, tier=inp.get("tier"))

    # Fan-out: prepare AOIs
    context.set_custom_status({"phase": "ingestion", "step": "preparing_aois", "features": feature_count})
    aoi_tasks = [
        context.call_activity(
            "prepare_aoi",
            {
                **prepare_input,
                "buffer_m": inp.get("buffer_m"),
                "instance_id": instance_id,
            },
        )
        for prepare_input in prepare_inputs
    ]
    aois = ensure_list_of_dicts(
        (yield context.task_all(aoi_tasks)),
        name="prepare_aoi",
        required_item_keys=("aoi_ref", "feature_name", "bbox", "area_ha", "centroid"),
    )

    # Claim-check: extract enrichment coords before offloading AOIs
    all_coords = _collect_enrichment_coords(aois)

    # Extract area_ha per AOI for batch routing (before claim-check offload)
    aoi_area_by_name: dict[str, float] = {a.get("feature_name", ""): a.get("area_ha", 0.0) for a in aois}

    # Extract centroids for pipeline telemetry spread calculation (#400).
    # [0.0, 0.0] is treesight.geo.centroid's placeholder for a missing/empty
    # polygon (see blueprints/monitoring.py's identical check) -- including it
    # would wildly inflate max_spread_km with a fake distance to Null Island.
    aoi_centroids: list[list[float]] = [
        a["centroid"] for a in aois if a.get("centroid") and len(a["centroid"]) == 2 and a["centroid"] != [0.0, 0.0]
    ]

    aoi_refs = ensure_list_of_dicts(
        [{"ref": aoi["aoi_ref"], "key": aoi.get("feature_name") or f"item_{index}"} for index, aoi in enumerate(aois)],
        name="prepare_aoi",
        required_item_keys=("ref", "key"),
    )
    for index, ref in enumerate(aoi_refs):
        ensure_nonempty_str_field(ref["ref"], name="prepare_aoi", field="ref", index=index)
        ensure_nonempty_str_field(ref["key"], name="prepare_aoi", field="key", index=index)
    per_aoi_coords = _collect_per_aoi_coords(aois, aoi_refs=aoi_refs)
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
            "feature_count": feature_count,
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
