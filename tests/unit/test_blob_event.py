"""Tests for the BlobEvent model.

Covers:
- Construction from Event Grid event data
- URL parsing (production + Azurite formats)
- Serialisation to/from dict
- Edge cases (empty URLs, missing fields)
"""

from __future__ import annotations

import pytest

from kml_satellite.models.blob_event import BlobEvent, _parse_blob_url

# ---------------------------------------------------------------------------
# URL Parsing
# ---------------------------------------------------------------------------


class TestParseBlobUrl:
    """Verify container/blob extraction from blob URLs."""

    def test_production_url(self) -> None:
        """Standard Azure Blob Storage URL."""
        container, blob = _parse_blob_url(
            "https://stkmlsatdev.blob.core.windows.net/kml-input/farm.kml"
        )
        assert container == "kml-input"
        assert blob == "farm.kml"

    def test_production_url_nested_blob(self) -> None:
        """Blob with a folder path inside the container."""
        container, blob = _parse_blob_url(
            "https://stkmlsatdev.blob.core.windows.net/kml-input/2026/02/farm.kml"
        )
        assert container == "kml-input"
        assert blob == "2026/02/farm.kml"

    def test_azurite_url(self) -> None:
        """Azurite development storage URL (localhost:10000)."""
        container, blob = _parse_blob_url(
            "http://127.0.0.1:10000/devstoreaccount1/kml-input/farm.kml"
        )
        assert container == "kml-input"
        assert blob == "farm.kml"

    def test_azurite_localhost_url(self) -> None:
        """Azurite URL using 'localhost' hostname."""
        container, blob = _parse_blob_url(
            "http://localhost:10000/devstoreaccount1/kml-input/test.kml"
        )
        assert container == "kml-input"
        assert blob == "test.kml"

    def test_empty_url(self) -> None:
        """Empty string URL returns empty tuple."""
        container, blob = _parse_blob_url("")
        assert container == ""
        assert blob == ""

    def test_url_no_path(self) -> None:
        """URL with no path segments."""
        container, blob = _parse_blob_url("https://example.com")
        assert container == ""
        assert blob == ""


# ---------------------------------------------------------------------------
# BlobEvent Construction
# ---------------------------------------------------------------------------


class TestBlobEventFromEventGrid:
    """Verify construction from Event Grid event payload."""

    @pytest.fixture()
    def sample_event_data(self) -> dict[str, object]:
        """Minimal Event Grid BlobCreated event data."""
        return {
            "url": "https://stkmlsatdev.blob.core.windows.net/kml-input/orchard.kml",
            "contentLength": 2048,
            "contentType": "application/vnd.google-earth.kml+xml",
        }

    def test_basic_construction(self, sample_event_data: dict[str, object]) -> None:
        """All fields populated from event data."""
        event = BlobEvent.from_event_grid_event(
            sample_event_data,
            event_time="2026-02-15T12:00:00",
            event_id="abc-123",
        )
        assert event.blob_url == sample_event_data["url"]
        assert event.container_name == "kml-input"
        assert event.blob_name == "orchard.kml"
        assert event.content_length == 2048
        assert event.content_type == "application/vnd.google-earth.kml+xml"
        assert event.event_time == "2026-02-15T12:00:00"
        assert event.correlation_id == "abc-123"

    def test_missing_optional_fields(self) -> None:
        """Missing optional fields default gracefully."""
        event = BlobEvent.from_event_grid_event(
            {"url": "https://stkmlsatdev.blob.core.windows.net/kml-input/test.kml"},
        )
        assert event.content_length == 0
        assert event.content_type == ""
        assert event.correlation_id == ""
        # event_time should be auto-populated
        assert event.event_time != ""

    def test_empty_event_data(self) -> None:
        """Totally empty event data doesn't crash."""
        event = BlobEvent.from_event_grid_event({})
        assert event.blob_url == ""
        assert event.container_name == ""
        assert event.blob_name == ""

    def test_invalid_content_length_returns_zero(self) -> None:
        """Non-numeric contentLength string defaults to 0."""
        event = BlobEvent.from_event_grid_event(
            {
                "url": "https://stkmlsatdev.blob.core.windows.net/kml-input/test.kml",
                "contentLength": "not-a-number",
            },
        )
        assert event.content_length == 0


# ---------------------------------------------------------------------------
# BlobEvent Serialisation
# ---------------------------------------------------------------------------


class TestBlobEventSerialization:
    """Verify round-trip serialisation for Durable Functions."""

    def test_to_dict(self) -> None:
        """to_dict produces all expected keys."""
        event = BlobEvent(
            blob_url="https://example.com/kml-input/test.kml",
            container_name="kml-input",
            blob_name="test.kml",
            content_length=1024,
            content_type="application/xml",
            event_time="2026-02-15T12:00:00",
            correlation_id="xyz-789",
        )
        d = event.to_dict()
        assert d["blob_url"] == "https://example.com/kml-input/test.kml"
        assert d["container_name"] == "kml-input"
        assert d["blob_name"] == "test.kml"
        assert d["content_length"] == 1024
        assert d["content_type"] == "application/xml"
        assert d["event_time"] == "2026-02-15T12:00:00"
        assert d["correlation_id"] == "xyz-789"

    def test_to_dict_keys_complete(self) -> None:
        """to_dict output has exactly the expected keys."""
        event = BlobEvent(
            blob_url="",
            container_name="",
            blob_name="",
        )
        expected_keys = {
            "blob_url",
            "container_name",
            "blob_name",
            "content_length",
            "content_type",
            "event_time",
            "correlation_id",
            "tenant_id",
            "output_container",
        }
        assert set(event.to_dict().keys()) == expected_keys

    def test_frozen_immutability(self) -> None:
        """BlobEvent is frozen (immutable)."""
        event = BlobEvent(blob_url="u", container_name="c", blob_name="b")
        with pytest.raises(AttributeError):
            event.blob_url = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tenant ID Extraction
# ---------------------------------------------------------------------------


class TestTenantIdExtraction:
    """Verify tenant_id and output_container derivation from container_name."""

    def test_acme_input_extracts_acme(self) -> None:
        """container_name='acme-input' → tenant_id='acme'."""
        event = BlobEvent(blob_url="", container_name="acme-input", blob_name="")
        assert event.tenant_id == "acme"

    def test_kml_input_extracts_empty(self) -> None:
        """container_name='kml-input' → tenant_id='' (legacy)."""
        event = BlobEvent(blob_url="", container_name="kml-input", blob_name="")
        assert event.tenant_id == ""

    def test_multi_part_tenant(self) -> None:
        """container_name='my-company-input' → tenant_id='my-company'."""
        event = BlobEvent(blob_url="", container_name="my-company-input", blob_name="")
        assert event.tenant_id == "my-company"

    def test_no_input_suffix_extracts_empty(self) -> None:
        """container_name='random' → tenant_id=''."""
        event = BlobEvent(blob_url="", container_name="random", blob_name="")
        assert event.tenant_id == ""

    def test_empty_container_extracts_empty(self) -> None:
        """container_name='' → tenant_id=''."""
        event = BlobEvent(blob_url="", container_name="", blob_name="")
        assert event.tenant_id == ""

    def test_output_container_with_tenant(self) -> None:
        """container_name='acme-input' → output_container='acme-output'."""
        event = BlobEvent(blob_url="", container_name="acme-input", blob_name="")
        assert event.output_container == "acme-output"

    def test_output_container_without_tenant(self) -> None:
        """container_name='kml-input' → output_container='kml-output'."""
        event = BlobEvent(blob_url="", container_name="kml-input", blob_name="")
        assert event.output_container == "kml-output"

    def test_to_dict_includes_tenant_fields(self) -> None:
        """to_dict() includes tenant_id and output_container."""
        event = BlobEvent(blob_url="", container_name="acme-input", blob_name="")
        d = event.to_dict()
        assert d["tenant_id"] == "acme"
        assert d["output_container"] == "acme-output"
