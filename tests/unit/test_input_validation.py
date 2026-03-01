"""Tests for KML input validation at the ingress boundary (Issue #105).

Tests the file size and content checks that enforce zero-assumption
input handling per PID 7.4.1 (Zero-Assumption Input Handling).

References:
    Issue #105  (Add KML input validation)
    PID 7.4.1   (Zero-Assumption Input Handling)
    PID 7.4.2   (Fail Loudly, Fail Safely)
"""

from __future__ import annotations

import pytest

from kml_satellite.core.exceptions import ContractError
from kml_satellite.core.ingress import validate_blob_input
from kml_satellite.models.blob_event import BlobEvent


class TestValidateBlobInputFileSize:
    """Test file size validation for KML blobs."""

    def test_valid_file_size_within_limits(self) -> None:
        """Allow blobs within the configured size limit."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/test.kml",
            container_name="kml-input",
            blob_name="test.kml",
            content_length=5 * 1024 * 1024,  # 5 MiB, well under 10 MiB default
            content_type="application/vnd.google-earth.kml+xml",
        )
        # Should not raise
        validate_blob_input(blob)

    def test_rejects_empty_blob(self) -> None:
        """Reject blobs with zero content length."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/empty.kml",
            container_name="kml-input",
            blob_name="empty.kml",
            content_length=0,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"zero|empty|content_length"):
            validate_blob_input(blob)

    def test_rejects_negative_content_length(self) -> None:
        """Reject blobs with negative content length (should not occur from Event Grid)."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/neg.kml",
            container_name="kml-input",
            blob_name="neg.kml",
            content_length=-100,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"negative|content_length|invalid"):
            validate_blob_input(blob)

    def test_rejects_oversized_blob(self) -> None:
        """Reject blobs exceeding the configured maximum size."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/huge.kml",
            container_name="kml-input",
            blob_name="huge.kml",
            content_length=15 * 1024 * 1024,  # 15 MiB, over 10 MiB limit
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"exceeds|maximum|size"):
            validate_blob_input(blob)

    def test_accepts_max_allowed_size(self) -> None:
        """Allow blobs exactly at the size limit (boundary condition)."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/max.kml",
            container_name="kml-input",
            blob_name="max.kml",
            content_length=10 * 1024 * 1024,  # Exactly 10 MiB
            content_type="application/vnd.google-earth.kml+xml",
        )
        # Should not raise
        validate_blob_input(blob)

    def test_rejects_just_over_max_size(self) -> None:
        """Reject blobs one byte over the size limit (boundary condition)."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/over.kml",
            container_name="kml-input",
            blob_name="over.kml",
            content_length=10 * 1024 * 1024 + 1,  # One byte over 10 MiB
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"exceeds|maximum|size"):
            validate_blob_input(blob)


class TestValidateBlobInputBlobName:
    """Test blob name validation."""

    def test_rejects_missing_kml_extension(self) -> None:
        """Reject blobs without .kml extension."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/test.txt",
            container_name="kml-input",
            blob_name="test.txt",
            content_length=1_000_000,
            content_type="text/plain",
        )
        with pytest.raises(ContractError, match=r"kml|extension|file type"):
            validate_blob_input(blob)

    def test_rejects_uppercase_kml_extension(self) -> None:
        """Reject blobs with uppercase .KML extension (case-insensitive check)."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/test.KML",
            container_name="kml-input",
            blob_name="test.KML",
            content_length=1_000_000,
            content_type="application/vnd.google-earth.kml+xml",
        )
        # Should accept (case-insensitive match for .kml)
        validate_blob_input(blob)

    def test_rejects_no_extension(self) -> None:
        """Reject blobs with no file extension."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/testfile",
            container_name="kml-input",
            blob_name="testfile",
            content_length=1_000_000,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"kml|extension"):
            validate_blob_input(blob)


class TestValidateBlobInputErrorMessages:
    """Test that error messages are clear and actionable."""

    def test_error_includes_blob_name_on_size_violation(self) -> None:
        """Error message includes blob name for debugging."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/huge.kml",
            container_name="kml-input",
            blob_name="huge.kml",
            content_length=15 * 1024 * 1024,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError) as exc_info:
            validate_blob_input(blob)
        assert "huge.kml" in str(exc_info.value)

    def test_error_includes_content_length_on_size_violation(self) -> None:
        """Error message includes actual content length for debugging."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/large.kml",
            container_name="kml-input",
            blob_name="large.kml",
            content_length=15 * 1024 * 1024,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError) as exc_info:
            validate_blob_input(blob)
        error_msg = str(exc_info.value)
        # Should mention the values for debugging
        assert "15" in error_msg or "large" in error_msg.lower()


class TestValidateBlobInputDefensiveValidation:
    """Test defensive validation against malformed inputs."""

    def test_handles_missing_blob_name_gracefully(self) -> None:
        """Reject blobs with empty blob name."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/kml-input/",
            container_name="kml-input",
            blob_name="",  # Empty blob name
            content_length=1_000_000,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"blob_name|empty|invalid"):
            validate_blob_input(blob)

    def test_handles_empty_container_name_gracefully(self) -> None:
        """Reject blobs with empty container name."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net//test.kml",
            container_name="",  # Empty container name
            blob_name="test.kml",
            content_length=1_000_000,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"container_name|empty|invalid"):
            validate_blob_input(blob)

    def test_rejects_unexpected_container_name(self) -> None:
        """Reject blobs from unexpected containers (not *-input)."""
        blob = BlobEvent(
            blob_url="https://example.blob.core.windows.net/audit-logs/test.kml",
            container_name="audit-logs",
            blob_name="test.kml",
            content_length=1_000_000,
            content_type="application/vnd.google-earth.kml+xml",
        )
        with pytest.raises(ContractError, match=r"container|input"):
            validate_blob_input(blob)
