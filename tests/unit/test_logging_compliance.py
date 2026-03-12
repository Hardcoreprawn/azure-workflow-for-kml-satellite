"""Logging compliance tests — structured log format verification. (Issue #16)

Verifies that key pipeline activities emit correctly structured log
messages with required context fields.  All tests use pytest's built-in
``caplog`` fixture — no Azure, no network calls.

Logging contract (enforced here):
    1. orchestrator_function start log contains ``instance=`` and ``correlation_id=``
    2. orchestrator_function complete log contains ``instance=`` and ``features=``
    3. acquire_imagery start log contains ``feature=`` and ``provider=``
    4. acquire_imagery best-scene log contains ``feature=`` and ``cloud=``
    5. acquire_imagery order log contains ``order_id=`` and ``provider=``
    6. acquire_imagery no-results warning contains ``feature=``
    7. post_process_imagery start log contains ``order=`` and ``feature=``
    8. post_process_imagery complete log contains ``order=`` and ``clipped=``

Log format convention (pipe-delimited key=value):
    All structured entries follow the pattern:
        "<action verb> | key1=val1 | key2=val2"

References:
    PID 7.4.6  (Observability — structured logging at activity boundaries)
    Issue #16  (Logging and alerting)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from kml_satellite.activities.acquire_imagery import ImageryAcquisitionError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_field(record_messages: list[str], field_prefix: str) -> bool:
    """Return True if any captured log message contains ``field_prefix``."""
    return any(field_prefix in msg for msg in record_messages)


def _messages_at_level(caplog: pytest.LogCaptureFixture, level: int = logging.INFO) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= level]


# ---------------------------------------------------------------------------
# acquire_imagery logging
# ---------------------------------------------------------------------------


class TestAcquireImageryLogging:
    """Structured log verification for acquire_imagery."""

    _AOI_DICT: ClassVar[dict[str, Any]] = {
        "feature_name": "Merlot Block C",
        "source_file": "vineyard.kml",
        "feature_index": 0,
        "exterior_coords": [[-73.0, 41.0], [-72.8, 41.0], [-72.8, 40.8], [-73.0, 41.0]],
        "bbox": [-73.0, 40.8, -72.8, 41.0],
        "buffered_bbox": [-73.01, 40.79, -72.79, 41.01],
        "area_ha": 50.0,
        "centroid": [-72.9, 40.9],
    }

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_start_log_has_feature_and_provider(
        self,
        mock_get_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Start log must include feature= and provider=."""
        from kml_satellite.activities.acquire_imagery import acquire_imagery
        from kml_satellite.providers.base import ProviderSearchError

        mock_provider = MagicMock()
        mock_provider.search.side_effect = ProviderSearchError(
            "planetary_computer", "forced stop", retryable=False
        )
        mock_get_provider.return_value = mock_provider

        with (
            caplog.at_level(logging.INFO, logger="kml_satellite.activities.acquire_imagery"),
            pytest.raises(ImageryAcquisitionError),
        ):
            acquire_imagery(self._AOI_DICT)

        msgs = _messages_at_level(caplog)
        assert _has_field(msgs, "feature="), "Start log must include feature="
        assert _has_field(msgs, "provider="), "Start log must include provider="

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_best_scene_log_has_feature_and_cloud(
        self,
        mock_get_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Best-scene log must include feature= and cloud=."""
        from kml_satellite.activities.acquire_imagery import acquire_imagery
        from kml_satellite.providers.base import ProviderOrderError

        mock_scene = MagicMock()
        mock_scene.scene_id = "SCENE_001"
        mock_scene.cloud_cover_pct = 3.5
        mock_scene.spatial_resolution_m = 10.0
        mock_scene.acquisition_date = datetime(2026, 1, 10, tzinfo=UTC)
        mock_scene.asset_url = None

        mock_provider = MagicMock()
        mock_provider.search.return_value = [mock_scene]
        mock_provider.order.side_effect = ProviderOrderError(
            "planetary_computer", "order backend down", retryable=True
        )
        mock_get_provider.return_value = mock_provider

        with (
            caplog.at_level(logging.INFO, logger="kml_satellite.activities.acquire_imagery"),
            pytest.raises(ImageryAcquisitionError),
        ):
            acquire_imagery(self._AOI_DICT)

        msgs = _messages_at_level(caplog)
        assert _has_field(msgs, "feature="), "Best-scene log must include feature="
        assert _has_field(msgs, "cloud="), "Best-scene log must include cloud="

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_order_submitted_log_has_order_id_and_provider(
        self,
        mock_get_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Order-submitted log must include order_id= and provider=."""
        from kml_satellite.activities.acquire_imagery import acquire_imagery

        mock_scene = MagicMock()
        mock_scene.scene_id = "SCENE_002"
        mock_scene.cloud_cover_pct = 0.0
        mock_scene.spatial_resolution_m = 5.0
        mock_scene.acquisition_date = datetime(2026, 1, 14, tzinfo=UTC)
        mock_scene.asset_url = None

        mock_order = MagicMock()
        mock_order.order_id = "pc-SCENE_002"
        mock_order.scene_id = "SCENE_002"
        mock_order.provider = "planetary_computer"

        mock_provider = MagicMock()
        mock_provider.search.return_value = [mock_scene]
        mock_provider.order.return_value = mock_order
        mock_get_provider.return_value = mock_provider

        with caplog.at_level(logging.INFO, logger="kml_satellite.activities.acquire_imagery"):
            acquire_imagery(self._AOI_DICT)

        msgs = _messages_at_level(caplog)
        assert _has_field(msgs, "order_id="), "Order log must include order_id="
        assert _has_field(msgs, "provider="), "Order log must include provider="

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_no_results_warning_contains_feature(
        self,
        mock_get_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No-results path must emit a warning mentioning the feature name."""
        from kml_satellite.activities.acquire_imagery import acquire_imagery

        mock_provider = MagicMock()
        mock_provider.search.return_value = []
        mock_get_provider.return_value = mock_provider

        with (
            caplog.at_level(logging.WARNING, logger="kml_satellite.activities.acquire_imagery"),
            pytest.raises(ImageryAcquisitionError),
        ):
            acquire_imagery(self._AOI_DICT)

        warning_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("Merlot Block C" in msg for msg in warning_msgs), (
            "No-results warning must contain the feature name"
        )


# ---------------------------------------------------------------------------
# post_process_imagery logging
# ---------------------------------------------------------------------------


class TestPostProcessImageryLogging:
    """Structured log verification for post_process_imagery."""

    _DOWNLOAD_RESULT: ClassVar[dict[str, Any]] = {
        "order_id": "pc-SCENE_X",
        "scene_id": "SCENE_X",
        "provider": "planetary_computer",
        "aoi_feature_name": "Cabernet Row 7",
        "blob_path": "imagery/raw/2026/03/vineyard/row7.tif",
        "container": "kml-output",
        "size_bytes": 8192,
        "content_type": "image/tiff",
    }

    _AOI: ClassVar[dict[str, Any]] = {
        "feature_name": "Cabernet Row 7",
        "source_file": "vineyard.kml",
        "exterior_coords": [
            [151.0, -34.0],
            [151.1, -34.0],
            [151.1, -34.1],
            [151.0, -34.0],
        ],
        "interior_coords": [],
        "bbox": [151.0, -34.1, 151.1, -34.0],
        "centroid": [151.05, -34.05],
        "area_ha": 20.0,
        "buffered_bbox": [150.999, -34.101, 151.101, -33.999],
        "crs": "EPSG:4326",
    }

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_start_log_has_order_and_feature(
        self,
        mock_process: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Start log must include order= and feature=."""
        from kml_satellite.activities.post_process_imagery import post_process_imagery

        mock_process.return_value = {
            "clipped": False,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": self._DOWNLOAD_RESULT["blob_path"],
            "output_size_bytes": 0,
            "clip_error": "",
        }

        with caplog.at_level(logging.INFO, logger="kml_satellite.activities.post_process_imagery"):
            post_process_imagery(self._DOWNLOAD_RESULT, self._AOI)

        msgs = _messages_at_level(caplog)
        assert _has_field(msgs, "order="), "Start log must include order="
        assert _has_field(msgs, "feature="), "Start log must include feature="

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_complete_log_has_order_and_clipped(
        self,
        mock_process: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Completion log must include order= and clipped=."""
        from kml_satellite.activities.post_process_imagery import post_process_imagery

        mock_process.return_value = {
            "clipped": True,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/clipped/2026/03/vineyard/row7.tif",
            "output_size_bytes": 4096,
            "clip_error": "",
        }

        with caplog.at_level(logging.INFO, logger="kml_satellite.activities.post_process_imagery"):
            post_process_imagery(self._DOWNLOAD_RESULT, self._AOI)

        msgs = _messages_at_level(caplog)
        assert _has_field(msgs, "order="), "Complete log must include order="
        assert _has_field(msgs, "clipped="), "Complete log must include clipped="


# ---------------------------------------------------------------------------
# orchestrator logging — instance and correlation_id presence
# ---------------------------------------------------------------------------


# Generator helpers for patching durable phases.
# `yield from gen_returning(value)` in the orchestrator evaluates to `value`.
def _gen_returning(value: Any):  # type: ignore[return]
    return value
    yield  # pragma: no cover


_INGESTION_FIXTURE: dict[str, Any] = {
    "feature_count": 0,
    "offloaded": False,
    "aois": [],
    "aoi_count": 0,
    "metadata_results": [],
    "metadata_count": 0,
}
_ACQUISITION_FIXTURE: dict[str, Any] = {
    "imagery_outcomes": [],
    "ready_count": 0,
    "failed_count": 0,
}
_FULFILLMENT_FIXTURE: dict[str, Any] = {
    "download_results": [],
    "downloads_completed": 0,
    "downloads_succeeded": 0,
    "downloads_failed": 0,
    "post_process_results": [],
    "pp_completed": 0,
    "pp_clipped": 0,
    "pp_reprojected": 0,
    "pp_failed": 0,
}


def _run_orchestrator_logged(ctx: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """Run the orchestrator with all phases mocked to return immediately."""
    from kml_satellite.orchestrators.kml_pipeline import orchestrator_function

    with (
        patch(
            "kml_satellite.orchestrators.kml_pipeline.run_ingestion_phase",
            side_effect=lambda *_, **__: _gen_returning(_INGESTION_FIXTURE),
        ),
        patch(
            "kml_satellite.orchestrators.kml_pipeline.run_acquisition_phase",
            side_effect=lambda *_, **__: _gen_returning(_ACQUISITION_FIXTURE),
        ),
        patch(
            "kml_satellite.orchestrators.kml_pipeline.run_fulfillment_phase",
            side_effect=lambda *_, **__: _gen_returning(_FULFILLMENT_FIXTURE),
        ),
        patch(
            "kml_satellite.orchestrators.kml_pipeline.build_pipeline_summary",
            return_value={"status": "completed"},
        ),
        caplog.at_level(logging.INFO, logger="kml_satellite.orchestrators.kml_pipeline"),
    ):
        gen = orchestrator_function(ctx)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass


class TestOrchestratorLogging:
    """Orchestrator start/complete logs must carry instance= and correlation_id=."""

    _BLOB_EVENT: ClassVar[dict[str, Any]] = {
        "blob_url": "https://st.blob.core.windows.net/kml-input/orchard.kml",
        "container_name": "kml-input",
        "blob_name": "orchard.kml",
        "content_length": 1024,
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": "2026-03-01T10:00:00",
        "correlation_id": "evt-test-corr-001",
    }

    def _build_context(self) -> MagicMock:
        ctx = MagicMock()
        ctx.get_input.return_value = self._BLOB_EVENT
        ctx.instance_id = "orch-log-test-001"
        ctx.is_replaying = False
        ctx.current_utc_datetime = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
        return ctx

    def test_start_log_contains_instance_and_correlation_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Orchestrator start log must include instance= and correlation_id=."""
        ctx = self._build_context()
        _run_orchestrator_logged(ctx, caplog)

        msgs = _messages_at_level(caplog)
        assert _has_field(msgs, "instance="), "Orchestrator start log must include instance="
        assert _has_field(msgs, "correlation_id="), (
            "Orchestrator start log must include correlation_id="
        )

    def test_complete_log_contains_instance_and_features(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Orchestrator completion log must include instance= and features=."""
        ctx = self._build_context()
        _run_orchestrator_logged(ctx, caplog)

        msgs = _messages_at_level(caplog)
        completed_msgs = [msg for msg in msgs if "Orchestrator completed" in msg]
        assert completed_msgs, "Expected an 'Orchestrator completed' log message"

        completion_msg = completed_msgs[0]
        assert "instance=" in completion_msg, "Orchestrator completion log must include instance="
        assert "features=" in completion_msg, "Orchestrator completion log must include features="
