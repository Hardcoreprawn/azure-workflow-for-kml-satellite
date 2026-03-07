"""Tests for Blob Storage job repository.

Phase 5 #71: Blob Storage JSON data layer (tenants + jobs).

Tests CRUD operations for Job documents with mocked Blob Storage client.

References:
    PID § 7.6 (Tenant State - jobs tracking)
    ROADMAP Phase 5 #71 (Blob Storage MVP)
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ResourceNotFoundError

from kml_satellite.data.job_repository import JobRepository
from kml_satellite.models.tenants import Job, JobStatus


class TestJobRepository(unittest.TestCase):
    """Repository for Job CRUD operations via Blob Storage JSON."""

    def test_create_job(self) -> None:
        """Create a new job document."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = JobRepository(mock_container)
            job = Job(
                job_id="job-001",
                tenant_id="tenant-001",
                kml_filename="orchard.kml",
                status=JobStatus.PENDING,
                started_at=datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC),
            )

            repo.create(job)

            # Verify blob path includes tenant_id for partitioning
            mock_container.get_blob_client.assert_called_once_with("jobs/tenant-001/job-001.json")
            mock_blob_client.upload_blob.assert_called_once()

    def test_get_job_found(self) -> None:
        """Get an existing job by ID."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_blob_download = MagicMock()
            mock_blob_client.download_blob.return_value = mock_blob_download
            mock_blob_download.readall.return_value = json.dumps(
                {
                    "job_id": "job-001",
                    "tenant_id": "tenant-001",
                    "kml_filename": "test.kml",
                    "status": "running",
                    "started_at": "2026-03-07T10:00:00+00:00",
                    "completed_at": None,
                    "error_message": None,
                    "feature_count": None,
                }
            ).encode()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = JobRepository(mock_container)
            job = repo.get("tenant-001", "job-001")

            assert job is not None
            assert job.job_id == "job-001"
            assert job.tenant_id == "tenant-001"
            assert job.status == JobStatus.RUNNING

    def test_get_job_not_found(self) -> None:
        """Get returns None when job doesn't exist."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_blob_client.download_blob.side_effect = ResourceNotFoundError(message="Not found")
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = JobRepository(mock_container)
            job = repo.get("tenant-001", "nonexistent")

            assert job is None

    def test_update_job_status(self) -> None:
        """Update job status to completed."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = JobRepository(mock_container)
            job = Job(
                job_id="job-001",
                tenant_id="tenant-001",
                kml_filename="test.kml",
                status=JobStatus.COMPLETED,
                started_at=datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC),
                completed_at=datetime(2026, 3, 7, 10, 5, 0, tzinfo=UTC),
                feature_count=5,
            )

            repo.update(job)

            # Verify upload with overwrite
            call_args = mock_blob_client.upload_blob.call_args
            assert call_args[1].get("overwrite") is True

    def test_delete_job(self) -> None:
        """Delete a job by ID."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = JobRepository(mock_container)
            repo.delete("tenant-001", "job-001")

            mock_container.get_blob_client.assert_called_once_with("jobs/tenant-001/job-001.json")
            mock_blob_client.delete_blob.assert_called_once()

    def test_list_jobs_for_tenant(self) -> None:
        """List all jobs for a specific tenant."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            # Mock list_blobs to return tenant-specific jobs
            mock_blob1 = MagicMock()
            mock_blob1.name = "jobs/tenant-001/job-001.json"
            mock_blob2 = MagicMock()
            mock_blob2.name = "jobs/tenant-001/job-002.json"
            mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]

            # Mock get_blob_client for each blob
            mock_blob_client1 = MagicMock()
            mock_blob_download1 = MagicMock()
            mock_blob_client1.download_blob.return_value = mock_blob_download1
            mock_blob_download1.readall.return_value = json.dumps(
                {
                    "job_id": "job-001",
                    "tenant_id": "tenant-001",
                    "kml_filename": "file1.kml",
                    "status": "completed",
                    "started_at": "2026-03-07T10:00:00+00:00",
                    "completed_at": "2026-03-07T10:05:00+00:00",
                }
            ).encode()

            mock_blob_client2 = MagicMock()
            mock_blob_download2 = MagicMock()
            mock_blob_client2.download_blob.return_value = mock_blob_download2
            mock_blob_download2.readall.return_value = json.dumps(
                {
                    "job_id": "job-002",
                    "tenant_id": "tenant-001",
                    "kml_filename": "file2.kml",
                    "status": "running",
                    "started_at": "2026-03-07T11:00:00+00:00",
                }
            ).encode()

            def get_blob_side_effect(path: str) -> MagicMock:
                if "job-001" in path:
                    return mock_blob_client1
                return mock_blob_client2

            mock_container.get_blob_client.side_effect = get_blob_side_effect

            repo = JobRepository(mock_container)
            jobs = repo.list_for_tenant("tenant-001")

            assert len(jobs) == 2
            # Jobs sorted by started_at descending (newest first)
            assert jobs[0].job_id == "job-002"  # 11:00 - newer
            assert jobs[1].job_id == "job-001"  # 10:00 - older
            assert all(j.tenant_id == "tenant-001" for j in jobs)

            # Verify prefix-based listing
            mock_container.list_blobs.assert_called_once_with(name_starts_with="jobs/tenant-001/")

    def test_list_jobs_by_status(self) -> None:
        """List jobs for a tenant filtered by status."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob1 = MagicMock()
            mock_blob1.name = "jobs/tenant-001/job-001.json"
            mock_blob2 = MagicMock()
            mock_blob2.name = "jobs/tenant-001/job-002.json"
            mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]

            mock_blob_client1 = MagicMock()
            mock_blob_download1 = MagicMock()
            mock_blob_client1.download_blob.return_value = mock_blob_download1
            mock_blob_download1.readall.return_value = json.dumps(
                {
                    "job_id": "job-001",
                    "tenant_id": "tenant-001",
                    "kml_filename": "file1.kml",
                    "status": "failed",
                    "started_at": "2026-03-07T10:00:00+00:00",
                    "completed_at": "2026-03-07T10:01:00+00:00",
                    "error_message": "KML parse error",
                }
            ).encode()

            mock_blob_client2 = MagicMock()
            mock_blob_download2 = MagicMock()
            mock_blob_client2.download_blob.return_value = mock_blob_download2
            mock_blob_download2.readall.return_value = json.dumps(
                {
                    "job_id": "job-002",
                    "tenant_id": "tenant-001",
                    "kml_filename": "file2.kml",
                    "status": "completed",
                    "started_at": "2026-03-07T11:00:00+00:00",
                    "completed_at": "2026-03-07T11:05:00+00:00",
                }
            ).encode()

            def get_blob_side_effect(path: str) -> MagicMock:
                if "job-001" in path:
                    return mock_blob_client1
                return mock_blob_client2

            mock_container.get_blob_client.side_effect = get_blob_side_effect

            repo = JobRepository(mock_container)
            failed_jobs = repo.list_by_status("tenant-001", JobStatus.FAILED)

            assert len(failed_jobs) == 1
            assert failed_jobs[0].job_id == "job-001"
            assert failed_jobs[0].status == JobStatus.FAILED
            assert failed_jobs[0].error_message == "KML parse error"
