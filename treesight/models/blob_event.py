"""BlobEvent domain model (§2.3).

The trigger payload when a KML file is uploaded to storage.
"""

from __future__ import annotations

from pydantic import BaseModel, computed_field

from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_OUTPUT_CONTAINER


class BlobEvent(BaseModel):
    """Event payload for a KML blob creation in storage.

    Attributes:
        blob_url: Full URL of the created blob.
        container_name: Container name (e.g. ``kml-input``).
        blob_name: Blob path within container.
        content_length: Size in bytes.
        content_type: MIME type.
        event_time: ISO 8601 timestamp of event.
        correlation_id: Unique trace ID (from event ID).
    """

    blob_url: str
    container_name: str
    blob_name: str
    content_length: int
    content_type: str
    event_time: str
    correlation_id: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tenant_id(self) -> str:
        """Extract tenant ID from container name.

        Pattern: ``{tenant_id}-input`` → ``tenant_id``.
        Legacy ``kml-input`` → ``""``.
        """
        if self.container_name == DEFAULT_INPUT_CONTAINER:
            return ""
        if self.container_name.endswith("-input"):
            return self.container_name.removesuffix("-input")
        return ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_container(self) -> str:
        """Derive output container from tenant ID."""
        tid = self.tenant_id
        if tid:
            return f"{tid}-output"
        return DEFAULT_OUTPUT_CONTAINER
