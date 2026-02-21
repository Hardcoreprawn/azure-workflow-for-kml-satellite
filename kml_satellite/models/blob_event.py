"""Data model for Blob Storage Event Grid events.

Represents the payload received when Event Grid fires a
Microsoft.Storage.BlobCreated event for the kml-input container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from kml_satellite.core.constants import DEFAULT_OUTPUT_CONTAINER


@dataclass(frozen=True, slots=True)
class BlobEvent:
    """Parsed Event Grid blob-created event.

    Attributes:
        blob_url: Full URL of the created blob.
        container_name: Name of the container (e.g. ``kml-input``).
        blob_name: Name of the blob within the container.
        content_length: Size of the blob in bytes.
        content_type: MIME type of the blob.
        event_time: Timestamp of the event.
        correlation_id: Unique ID for tracing this event through the pipeline.
    """

    blob_url: str
    container_name: str
    blob_name: str
    content_length: int = 0
    content_type: str = ""
    event_time: str = ""
    correlation_id: str = field(default="")

    @property
    def tenant_id(self) -> str:
        """Extract tenant identifier from the container name.

        Pattern: ``{tenant_id}-input`` → tenant_id.
        Legacy ``kml-input`` → ``""`` (empty string).
        """
        if self.container_name.endswith("-input"):
            prefix = self.container_name[: -len("-input")]
            return "" if prefix == "kml" else prefix
        return ""

    @property
    def output_container(self) -> str:
        """Derive the output container name from tenant_id."""
        return f"{self.tenant_id}-output" if self.tenant_id else DEFAULT_OUTPUT_CONTAINER

    def to_dict(self) -> dict[str, str | int]:
        """Serialise to a dict for passing to Durable Functions orchestrator."""
        return {
            "blob_url": self.blob_url,
            "container_name": self.container_name,
            "blob_name": self.blob_name,
            "content_length": self.content_length,
            "content_type": self.content_type,
            "event_time": self.event_time,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "output_container": self.output_container,
        }

    @classmethod
    def from_event_grid_event(
        cls,
        event_data: dict[str, object],
        *,
        event_time: str | None = None,
        event_id: str = "",
    ) -> BlobEvent:
        """Construct from an Event Grid event's ``data`` payload.

        The Event Grid ``BlobCreated`` schema provides:
        - ``url``: Full blob URL
        - ``contentLength``: Size in bytes
        - ``contentType``: MIME type

        Container and blob name are extracted from the ``url`` field.
        """
        url = str(event_data.get("url", ""))
        content_length_value = event_data.get("contentLength", 0)
        content_length = 0
        if isinstance(content_length_value, int | str | float):
            try:
                content_length = int(content_length_value)
            except (TypeError, ValueError):
                content_length = 0
        content_type = str(event_data.get("contentType", ""))

        # Extract container and blob name from the URL.
        # URL format: https://<account>.blob.core.windows.net/<container>/<blob>
        container_name, blob_name = _parse_blob_url(url)

        return cls(
            blob_url=url,
            container_name=container_name,
            blob_name=blob_name,
            content_length=content_length,
            content_type=content_type,
            event_time=event_time if event_time is not None else datetime.now(tz=UTC).isoformat(),
            correlation_id=event_id,
        )


def _parse_blob_url(url: str) -> tuple[str, str]:
    """Extract (container_name, blob_name) from a Blob Storage URL.

    Handles both production URLs (``*.blob.core.windows.net``) and
    Azurite URLs (``127.0.0.1:10000/<account>``).

    Returns:
        Tuple of (container_name, blob_name). Returns empty strings if
        the URL cannot be parsed.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]

    if not path_parts:
        return ("", "")

    # Azurite URLs have the account name as the first path segment.
    # Production URLs have the account in the hostname.
    is_azurite = parsed.hostname in ("127.0.0.1", "localhost") or (
        parsed.port is not None and parsed.port == 10000
    )

    if is_azurite and len(path_parts) >= 3:
        # /devstoreaccount1/<container>/<blob>
        return (path_parts[1], "/".join(path_parts[2:]))

    if len(path_parts) >= 2:
        # /<container>/<blob>
        return (path_parts[0], "/".join(path_parts[1:]))

    return ("", "")
