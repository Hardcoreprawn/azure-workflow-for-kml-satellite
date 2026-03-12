"""Concurrent stress tests for live pipeline validation (Issue #14).

These tests upload 20 KML files concurrently and verify:
- each upload maps to a unique orchestration instance
- all runs reach terminal Completed state
- metadata artifacts are collision-free across concurrent runs
- metadata blobs exist and are non-empty

The test is marked both e2e and slow, and uses the same environment-driven
skip model as test_live_pipeline.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from statistics import mean
from typing import Any

import pytest

from tests.integration.test_live_pipeline import (
    _OUTPUT_CONTAINER,
    _blob_exists,
    _blob_service,
    _live,
    _run_pipeline,
)

LOGGER = logging.getLogger(__name__)

_MAX_CONCURRENCY = 20
_WORKLOAD_KMLS: list[str] = [
    "01_single_polygon_orchard.kml",
    "02_multipolygon_orchard_blocks.kml",
    "03_multi_feature_vineyard.kml",
    "04_complex_polygon_with_hole.kml",
    "05_irregular_polygon_steep_terrain.kml",
    "06_large_area_plantation.kml",
    "07_small_area_garden.kml",
    "08_no_extended_data.kml",
    "09_folder_nested_features.kml",
    "10_schema_typed_extended_data.kml",
    "uk-mountsorrel-halstead-road-park.kml",
    "uk-mountsorrel-millenium-green.kml",
    "uk-mountsorrel-wood-lane-quarry.kml",
    "uk-newton-linford-bradgate-country-park.kml",
    "uk-oakworth-griff-wood.kml",
    "01_single_polygon_orchard.kml",
    "03_multi_feature_vineyard.kml",
    "04_complex_polygon_with_hole.kml",
    "06_large_area_plantation.kml",
    "09_folder_nested_features.kml",
]


@dataclass(frozen=True)
class StressRunResult:
    workload_idx: int
    kml_filename: str
    instance_id: str
    runtime_status: str
    pipeline_status: str
    aoi_count: int
    metadata_count: int
    metadata_paths: list[str]
    duration_s: float


def _run_one(workload_idx: int, kml_filename: str) -> StressRunResult:
    started = time.monotonic()
    instance_id, payload = _run_pipeline(kml_filename)
    elapsed = time.monotonic() - started

    output: dict[str, Any] = payload.get("output") or {}
    artifacts: dict[str, Any] = output.get("artifacts") or {}

    return StressRunResult(
        workload_idx=workload_idx,
        kml_filename=kml_filename,
        instance_id=instance_id,
        runtime_status=str(payload.get("runtimeStatus") or ""),
        pipeline_status=str(output.get("status") or ""),
        aoi_count=int(output.get("aoiCount") or 0),
        metadata_count=int(output.get("metadataCount") or 0),
        metadata_paths=list(artifacts.get("metadataPaths") or []),
        duration_s=elapsed,
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Compute an inclusive nearest-rank percentile for a non-empty list."""
    assert values, "values must be non-empty"
    assert 0 <= percentile <= 1, "percentile must be in [0, 1]"
    sorted_values = sorted(values)
    rank = int((len(sorted_values) - 1) * percentile)
    return sorted_values[rank]


@pytest.mark.e2e
@pytest.mark.slow
class TestLiveConcurrentStress:
    """AC-10: pipeline should process >=20 concurrent uploads without conflicts."""

    @_live
    def test_20_concurrent_uploads_are_isolated_and_complete(
        self, record_property: pytest.RecordProperty
    ) -> None:
        """Run 20 concurrent uploads and verify correctness + basic throughput metrics."""
        started = time.monotonic()
        results: list[StressRunResult] = []

        with ThreadPoolExecutor(max_workers=_MAX_CONCURRENCY) as pool:
            futures = [
                pool.submit(_run_one, idx, filename)
                for idx, filename in enumerate(_WORKLOAD_KMLS, start=1)
            ]
            for future in as_completed(futures):
                results.append(future.result())

        total_elapsed_s = time.monotonic() - started

        assert len(results) == len(_WORKLOAD_KMLS), (
            f"Expected {len(_WORKLOAD_KMLS)} completed runs, got {len(results)}"
        )

        not_completed = [r for r in results if r.runtime_status != "Completed"]
        assert not not_completed, "Some orchestrations did not reach Completed: " + ", ".join(
            f"idx={r.workload_idx} kml={r.kml_filename} status={r.runtime_status}"
            for r in not_completed
        )

        instance_ids = [r.instance_id for r in results]
        assert len(instance_ids) == len(set(instance_ids)), (
            "Duplicate orchestration instance IDs detected under concurrency"
        )

        all_metadata_paths: list[str] = []
        for run in results:
            assert run.metadata_count >= 1, (
                f"No metadata produced for idx={run.workload_idx} kml={run.kml_filename}; "
                f"pipeline_status={run.pipeline_status}"
            )
            assert len(run.metadata_paths) == len(set(run.metadata_paths)), (
                f"Duplicate metadata paths within run idx={run.workload_idx}: {run.metadata_paths}"
            )
            all_metadata_paths.extend(run.metadata_paths)

        assert len(all_metadata_paths) == len(set(all_metadata_paths)), (
            "Metadata path collisions detected across concurrent runs"
        )

        blob_svc = _blob_service()
        missing = [
            p for p in all_metadata_paths if not _blob_exists(blob_svc, _OUTPUT_CONTAINER, p)
        ]
        assert not missing, "Some metadata artifacts are missing or empty: " + ", ".join(
            missing[:10]
        )

        durations = [r.duration_s for r in results]
        throughput = len(results) / total_elapsed_s if total_elapsed_s > 0 else 0.0
        p50 = _percentile(durations, 0.50)
        p95 = _percentile(durations, 0.95)
        max_duration = max(durations)

        LOGGER.info(
            "Stress run metrics | uploads=%d | total_s=%.2f | throughput=%.2f/s | "
            "mean_s=%.2f | p50_s=%.2f | p95_s=%.2f | max_s=%.2f",
            len(results),
            total_elapsed_s,
            throughput,
            mean(durations),
            p50,
            p95,
            max_duration,
        )

        record_property("concurrent_uploads", len(results))
        record_property("total_duration_s", round(total_elapsed_s, 2))
        record_property("throughput_per_s", round(throughput, 4))
        record_property("duration_mean_s", round(mean(durations), 2))
        record_property("duration_p50_s", round(p50, 2))
        record_property("duration_p95_s", round(p95, 2))
        record_property("duration_max_s", round(max_duration, 2))
