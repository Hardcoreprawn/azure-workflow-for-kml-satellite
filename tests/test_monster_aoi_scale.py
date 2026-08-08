"""Scale gate: prove 200+ AOI KML processing without OOM, timeout, or dropped events.

This test file implements the Stage 2 exit criterion from issue #437:
"200+ concurrent AOIs process reliably without OOM or timeout".

Note: this exercises KML input specifically (``parse_kml_lxml`` on raw KML
bytes) -- KMZ unzip handling is covered by the parser test suite, not here.

Test structure
--------------
1. ``TestParseMonster200`` — parse-level assertions: verify the monster KML produces
   exactly 200 distinct, valid AOIs with positive area and no exceptions.
2. ``TestEnrichmentFanOut200`` — fan-out scale assertions: run the parallel enrichment
   loop over all 200 AOIs with mocked I/O, assert no AOIs are dropped, and capture
   timing percentiles (p50/p95/p99) as a documented baseline.

Both test classes run without any network or Azure dependencies.  The integration
test at the bottom (``TestPipelineSmokeMonster``) is marked ``pytest.mark.integration``
and requires Azurite + local Functions host.

Run with::

    uv run pytest tests/test_monster_aoi_scale.py -v

Skip integration tests::

    uv run pytest tests/test_monster_aoi_scale.py -v -m "not integration"
"""

from __future__ import annotations

import statistics
import time
import typing
from unittest.mock import MagicMock, patch

import pytest

from treesight.geo import prepare_aoi
from treesight.parsers.lxml_parser import parse_kml_lxml
from treesight.pipeline.enrichment.mosaic import _coords_to_bbox
from treesight.pipeline.enrichment.runner import run_enrichment

_EXPECTED_AOI_COUNT = 200
# Generous wall-clock ceiling — CI machines are slow; the target is «no runaway growth».
_MAX_PARSE_SECONDS = 15.0
_MAX_FANOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(data: list[float], pct: float) -> float:
    """Return the ``pct``-th percentile of ``data`` (0–100)."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    lo = int(k)
    hi = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[lo]
    return sorted_data[lo] + (k - lo) * (sorted_data[hi] - sorted_data[lo])


def _make_stub_enrich(timings: list[float]):
    """Return a drop-in replacement for ``_enrich_single_aoi`` that records per-AOI timings."""

    def _stub(entry: dict, **kwargs) -> dict:
        t0 = time.perf_counter()
        coords = entry.get("coords", [])
        # No-op: mirror production's _coords_to_bbox() shape (closed 5-point
        # ring), not an arbitrary coords[:4] slice, so a structural bug in
        # real bbox handling wouldn't be masked by a differently-shaped stub.
        result = {
            "name": entry.get("name", ""),
            "coords": coords,
            "bbox": _coords_to_bbox(coords) if coords else [],
            "area_ha": entry.get("area_ha", 0.0),
        }
        timings.append(time.perf_counter() - t0)
        return result

    return _stub


def _build_per_aoi_coords(monster_kml_bytes: bytes) -> list[dict]:
    """Parse the monster KML and return ``per_aoi_coords`` entries for ``run_enrichment``."""
    features = parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
    aois = [prepare_aoi(f) for f in features]
    return [
        {
            "name": a.feature_name,
            "coords": list(a.exterior_coords),
            "area_ha": a.area_ha,
        }
        for a in aois
    ]


# ---------------------------------------------------------------------------
# Phase 1 — Parse-level scale assertions
# ---------------------------------------------------------------------------


class TestParseMonster200:
    """Prove the 200-AOI KML parses correctly without OOM or exception."""

    def test_parses_200_features(self, monster_kml_bytes: bytes) -> None:
        """Exactly 200 Placemark elements must be returned."""
        features = parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
        assert len(features) == _EXPECTED_AOI_COUNT, (
            f"Expected {_EXPECTED_AOI_COUNT} features, got {len(features)}"
        )

    def test_all_aois_have_positive_area(self, monster_kml_bytes: bytes) -> None:
        """Every AOI must have area_ha > 0 — no degenerate polygons."""
        features = parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
        aois = [prepare_aoi(f) for f in features]
        degenerate = [a.feature_name for a in aois if a.area_ha <= 0]
        assert not degenerate, f"AOIs with zero/negative area: {degenerate}"

    def test_all_aois_have_distinct_bboxes(self, monster_kml_bytes: bytes) -> None:
        """No two AOIs occupy the same bounding box — no coordinate collisions."""
        features = parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
        aois = [prepare_aoi(f) for f in features]
        bboxes = [tuple(round(v, 6) for v in a.bbox) for a in aois]
        assert len(set(bboxes)) == len(bboxes), (
            f"Duplicate bboxes detected — {len(bboxes) - len(set(bboxes))} collisions"
        )

    def test_all_aois_have_positive_perimeter(self, monster_kml_bytes: bytes) -> None:
        """Every AOI must have a positive perimeter."""
        features = parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
        aois = [prepare_aoi(f) for f in features]
        assert all(a.perimeter_km > 0 for a in aois)

    def test_all_feature_names_present(self, monster_kml_bytes: bytes) -> None:
        """Every Placemark must carry a non-empty name."""
        features = parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
        unnamed = [f for f in features if not f.name]
        assert not unnamed, f"{len(unnamed)} features have empty names"

    def test_parse_completes_within_time_limit(self, monster_kml_bytes: bytes) -> None:
        """Parsing 200 AOIs must complete in under 15 seconds."""
        t0 = time.perf_counter()
        parse_kml_lxml(monster_kml_bytes, source_file="monster_200.kml")
        elapsed = time.perf_counter() - t0
        assert elapsed < _MAX_PARSE_SECONDS, (
            f"Parsing 200 AOIs took {elapsed:.2f}s — exceeds {_MAX_PARSE_SECONDS}s ceiling"
        )


# ---------------------------------------------------------------------------
# Phase 2 — Fan-out enrichment scale assertions
# ---------------------------------------------------------------------------


class TestEnrichmentFanOut200:
    """Prove the parallel enrichment fan-out handles 200 AOIs reliably."""

    # Shared minimal frame plan used across all test methods in this class.
    _FRAME_PLAN: typing.ClassVar[list[dict]] = [
        {
            "start": "2024-01-01",
            "end": "2024-03-01",
            "year": 2024,
            "season": "summer",
            "collection": "sentinel-2-l2a",
            "is_naip": False,
        }
    ]

    @pytest.fixture(autouse=True)
    def _block_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fail fast if any test in this class opens a real network socket."""
        import socket

        def _deny(*args, **kwargs):
            raise AssertionError("Network access is not allowed in scale tests.")

        monkeypatch.setattr(socket, "create_connection", _deny)
        monkeypatch.setattr(socket, "getaddrinfo", _deny)

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_all_200_aois_processed(
        self,
        mock_frame_plan,
        mock_weather,
        mock_flood,
        mock_mosaic,
        mock_change,
        monster_kml_bytes: bytes,
    ) -> None:
        """Fan-out must return a result for every AOI — no silent drops."""
        mock_frame_plan.return_value = self._FRAME_PLAN
        mock_mosaic.return_value = ([], [])

        per_aoi_coords = _build_per_aoi_coords(monster_kml_bytes)
        assert len(per_aoi_coords) == _EXPECTED_AOI_COUNT

        timings: list[float] = []
        storage = MagicMock()

        with patch(
            "treesight.pipeline.enrichment.runner._enrich_single_aoi",
            _make_stub_enrich(timings),
        ):
            result = run_enrichment(
                coords=per_aoi_coords[0]["coords"],
                project_name="monster_scale_test",
                timestamp="20240101T000000",
                output_container="output",
                storage=storage,
                per_aoi_coords=per_aoi_coords,
            )

        assert "per_aoi_enrichment" in result, "per_aoi_enrichment key missing from result"
        per_aoi = result["per_aoi_enrichment"]

        # Every slot must be populated — no None, no empty {} from a dropped future.
        dropped = [i for i, r in enumerate(per_aoi) if r is None or r == {}]
        assert not dropped, f"Dropped AOI indices (expected 0): {dropped[:10]}"

        assert len(per_aoi) == _EXPECTED_AOI_COUNT, (
            f"Expected {_EXPECTED_AOI_COUNT} results, got {len(per_aoi)}"
        )
        assert len(timings) == _EXPECTED_AOI_COUNT, (
            f"Timing capture mismatch: recorded {len(timings)} timings "
            f"for {_EXPECTED_AOI_COUNT} AOIs"
        )

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_no_errors_in_results(
        self,
        mock_frame_plan,
        mock_weather,
        mock_flood,
        mock_mosaic,
        mock_change,
        monster_kml_bytes: bytes,
    ) -> None:
        """None of the 200 AOI results should carry an ``error`` key from the safe-wrapper."""
        mock_frame_plan.return_value = self._FRAME_PLAN
        mock_mosaic.return_value = ([], [])

        per_aoi_coords = _build_per_aoi_coords(monster_kml_bytes)
        storage = MagicMock()

        with patch(
            "treesight.pipeline.enrichment.runner._enrich_single_aoi",
            _make_stub_enrich([]),
        ):
            result = run_enrichment(
                coords=per_aoi_coords[0]["coords"],
                project_name="monster_scale_test",
                timestamp="20240101T000000",
                output_container="output",
                storage=storage,
                per_aoi_coords=per_aoi_coords,
            )

        errored = [
            r.get("name", f"idx-{i}")
            for i, r in enumerate(result["per_aoi_enrichment"])
            if "error" in r
        ]
        assert not errored, f"AOIs with enrichment errors: {errored}"

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_fanout_timing_and_baseline(
        self,
        mock_frame_plan,
        mock_weather,
        mock_flood,
        mock_mosaic,
        mock_change,
        monster_kml_bytes: bytes,
    ) -> None:
        """Total wall-clock and per-AOI percentiles must stay within documented ceilings.

        Baseline documented in docs/scale_baseline.md.
        """
        mock_frame_plan.return_value = self._FRAME_PLAN
        mock_mosaic.return_value = ([], [])

        per_aoi_coords = _build_per_aoi_coords(monster_kml_bytes)
        timings: list[float] = []
        storage = MagicMock()

        wall_start = time.perf_counter()
        with patch(
            "treesight.pipeline.enrichment.runner._enrich_single_aoi",
            _make_stub_enrich(timings),
        ):
            run_enrichment(
                coords=per_aoi_coords[0]["coords"],
                project_name="monster_scale_test",
                timestamp="20240101T000000",
                output_container="output",
                storage=storage,
                per_aoi_coords=per_aoi_coords,
            )
        wall_elapsed = time.perf_counter() - wall_start

        assert len(timings) == _EXPECTED_AOI_COUNT, (
            f"Timing capture mismatch: recorded {len(timings)} timings "
            f"for {_EXPECTED_AOI_COUNT} AOIs -- percentiles below would be meaningless"
        )

        p50 = _percentile(timings, 50)
        p95 = _percentile(timings, 95)
        p99 = _percentile(timings, 99)

        # --- Assertions ---
        assert wall_elapsed < _MAX_FANOUT_SECONDS, (
            f"Fan-out for {_EXPECTED_AOI_COUNT} AOIs took {wall_elapsed:.2f}s "
            f"— exceeds {_MAX_FANOUT_SECONDS}s ceiling"
        )
        # p99 ceiling: each individual AOI stub should finish in well under a second.
        assert p99 < 1.0, f"Per-AOI p99 = {p99 * 1000:.1f} ms exceeds 1 000 ms"

        # Emit metrics to stdout so they appear in test output / CI logs.
        print(
            f"\n[scale-baseline] 200-AOI fan-out | "
            f"wall={wall_elapsed:.3f}s | "
            f"p50={p50 * 1000:.1f}ms | "
            f"p95={p95 * 1000:.1f}ms | "
            f"p99={p99 * 1000:.1f}ms | "
            f"mean={statistics.mean(timings) * 1000:.1f}ms"
        )

    @patch("treesight.pipeline.enrichment.runner._run_change_detection_phase")
    @patch("treesight.pipeline.enrichment.runner._run_mosaic_ndvi_phase")
    @patch("treesight.pipeline.enrichment.runner._run_flood_fire_phase")
    @patch("treesight.pipeline.enrichment.runner._run_weather_phase")
    @patch("treesight.pipeline.enrichment.runner.build_frame_plan")
    def test_result_has_enrichment_duration(
        self,
        mock_frame_plan,
        mock_weather,
        mock_flood,
        mock_mosaic,
        mock_change,
        monster_kml_bytes: bytes,
    ) -> None:
        """The manifest must carry ``enrichment_duration_seconds`` from the orchestrator."""
        mock_frame_plan.return_value = self._FRAME_PLAN
        mock_mosaic.return_value = ([], [])

        per_aoi_coords = _build_per_aoi_coords(monster_kml_bytes)
        storage = MagicMock()

        with patch(
            "treesight.pipeline.enrichment.runner._enrich_single_aoi",
            _make_stub_enrich([]),
        ):
            result = run_enrichment(
                coords=per_aoi_coords[0]["coords"],
                project_name="monster_scale_test",
                timestamp="20240101T000000",
                output_container="output",
                storage=storage,
                per_aoi_coords=per_aoi_coords,
            )

        assert "enrichment_duration_seconds" in result
        assert result["enrichment_duration_seconds"] >= 0


# ---------------------------------------------------------------------------
# Integration test — requires Azurite + local Functions host
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPipelineSmokeMonster:
    """Connectivity guard for the 200-AOI monster KML integration run.

    Only proves Azurite and the local Functions host are reachable -- it does
    not upload the monster file or assert pipeline outputs. Skipped
    automatically unless both dependencies are running.

    Run with::

        make dev-all  # in another terminal
        uv run pytest tests/test_monster_aoi_scale.py -v -m integration
    """

    def _azurite_reachable(self) -> bool:
        try:
            from _azurite import azurite_blob_reachable  # module ships with the repo

            return azurite_blob_reachable()
        except ImportError:
            # Helper module absent — treat as "not running" without masking bugs.
            return False
        except Exception:
            # Connection error or similar transient failure.
            return False

    def _func_host_reachable(self) -> bool:
        try:
            import httpx

            resp = httpx.get("http://localhost:7071/api/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def test_skipped_when_dependencies_absent(self) -> None:
        """Guard: skip rather than fail if either Azurite or the Functions host is down."""
        if not self._azurite_reachable() or not self._func_host_reachable():
            pytest.skip("Azurite or Functions host not running — start with: make dev-all")

        # If dependencies ARE present, this test just confirms we can reach them.
        assert self._azurite_reachable()
        assert self._func_host_reachable()
