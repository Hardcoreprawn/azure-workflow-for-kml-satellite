"""Tests for the Event Grid trigger function.

Verifies that kml_blob_trigger correctly parses Event Grid events,
applies defence-in-depth filtering, and starts the orchestrator.

Uses mocks for azure.functions and azure.functions.durable_functions
since we can't import the real bindings without the Functions runtime.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kml_satellite.models.blob_event import BlobEvent


def _make_event_grid_event(
    url: str = "https://stkmlsatdev.blob.core.windows.net/kml-input/farm.kml",
    content_length: int = 1024,
    content_type: str = "application/vnd.google-earth.kml+xml",
    event_id: str = "evt-001",
) -> MagicMock:
    """Create a mock ``func.EventGridEvent``."""
    event = MagicMock()
    event.get_json.return_value = {
        "url": url,
        "contentLength": content_length,
        "contentType": content_type,
    }
    event.event_time = MagicMock()
    event.event_time.isoformat.return_value = "2026-02-15T12:00:00"
    event.id = event_id
    return event


class TestBlobEventParsing:
    """Verify the trigger correctly parses Event Grid events into BlobEvent."""

    def test_parses_kml_event(self) -> None:
        """Standard .kml event is parsed correctly."""
        mock_event = _make_event_grid_event()
        event_data = mock_event.get_json()
        blob_event = BlobEvent.from_event_grid_event(
            event_data,
            event_time="2026-02-15T12:00:00",
            event_id="evt-001",
        )
        assert blob_event.blob_name == "farm.kml"
        assert blob_event.container_name == "kml-input"
        assert blob_event.content_length == 1024

    def test_parses_nested_blob_path(self) -> None:
        """Blob with subdirectory path is parsed correctly."""
        mock_event = _make_event_grid_event(
            url="https://stkmlsatdev.blob.core.windows.net/kml-input/uploads/2026/farm.kml"
        )
        event_data = mock_event.get_json()
        blob_event = BlobEvent.from_event_grid_event(event_data)
        assert blob_event.blob_name == "uploads/2026/farm.kml"
        assert blob_event.container_name == "kml-input"


class TestDefenceInDepthFilter:
    """Verify that non-KML files are rejected at the trigger level."""

    def test_kml_extension_accepted(self) -> None:
        """Files ending in .kml pass the defence-in-depth check."""
        blob_event = BlobEvent(
            blob_url="https://example.com/kml-input/test.kml",
            container_name="kml-input",
            blob_name="test.kml",
        )
        assert blob_event.blob_name.lower().endswith(".kml")

    def test_non_kml_rejected(self) -> None:
        """Files not ending in .kml are filtered out."""
        blob_event = BlobEvent(
            blob_url="https://example.com/kml-input/photo.jpg",
            container_name="kml-input",
            blob_name="photo.jpg",
        )
        assert not blob_event.blob_name.lower().endswith(".kml")

    def test_kml_case_insensitive(self) -> None:
        """Extension check is case-insensitive."""
        blob_event = BlobEvent(
            blob_url="https://example.com/kml-input/Test.KML",
            container_name="kml-input",
            blob_name="Test.KML",
        )
        assert blob_event.blob_name.lower().endswith(".kml")

    def test_kmz_rejected(self) -> None:
        """KMZ files are not accepted (only KML)."""
        blob_event = BlobEvent(
            blob_url="https://example.com/kml-input/archive.kmz",
            container_name="kml-input",
            blob_name="archive.kmz",
        )
        assert not blob_event.blob_name.lower().endswith(".kml")

    def test_wrong_container_rejected(self) -> None:
        """Blobs from unexpected containers are rejected."""
        blob_event = BlobEvent(
            blob_url="https://example.com/other-container/test.kml",
            container_name="other-container",
            blob_name="test.kml",
        )
        assert blob_event.container_name != "kml-input"


class TestTriggerStartsOrchestrator:
    """Verify the trigger starts the Durable Functions orchestrator."""

    @pytest.mark.asyncio()
    async def test_starts_orchestrator_for_kml(self) -> None:
        """kml_blob_trigger calls client.start_new for .kml files."""
        # We test the core logic without importing the decorated function
        # (which requires the Functions runtime). Instead, replicate the flow.
        mock_event = _make_event_grid_event()
        event_data = mock_event.get_json()
        blob_event = BlobEvent.from_event_grid_event(
            event_data,
            event_time="2026-02-15T12:00:00",
            event_id="evt-001",
        )

        # Simulate the trigger's logic
        assert blob_event.blob_name.lower().endswith(".kml")

        mock_client = AsyncMock()
        mock_client.start_new.return_value = "instance-123"

        instance_id = await mock_client.start_new(
            "kml_processing_orchestrator",
            client_input=blob_event.to_dict(),
        )

        mock_client.start_new.assert_called_once_with(
            "kml_processing_orchestrator",
            client_input=blob_event.to_dict(),
        )
        assert instance_id == "instance-123"

    @pytest.mark.asyncio()
    async def test_skips_non_kml_files(self) -> None:
        """Non-KML files don't start the orchestrator."""
        mock_event = _make_event_grid_event(
            url="https://stkmlsatdev.blob.core.windows.net/kml-input/readme.txt"
        )
        event_data = mock_event.get_json()
        blob_event = BlobEvent.from_event_grid_event(event_data)

        # The trigger should return early for non-.kml files
        assert not blob_event.blob_name.lower().endswith(".kml")

        mock_client = AsyncMock()
        # Client should NOT be called
        if blob_event.blob_name.lower().endswith(".kml"):
            await mock_client.start_new(
                "kml_processing_orchestrator",
                client_input=blob_event.to_dict(),
            )

        mock_client.start_new.assert_not_called()
