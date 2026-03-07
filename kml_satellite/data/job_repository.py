"""Job repository for Blob Storage JSON operations.

Phase 5 #71: Blob Storage JSON data layer (tenants + jobs).

Stores job documents as JSON blobs in Azure Blob Storage.
Jobs track pipeline execution status from KML upload to completion.

Blob organization:
    {container}/jobs/{tenant_id}/{job_id}.json

This naturally partitions jobs by tenant for isolation and efficient listing.

Margaret Hamilton principles:
- Explicit error handling for Blob Storage exceptions
- Defensive JSON parsing with fallback defaults
- Minimal dependencies (no extra Azure services)
- Tenant-partitioned paths for isolation

References:
    PID § 7.6 (Tenant State - jobs tracking)
    ROADMAP Phase 5 #71 (Blob Storage MVP)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from azure.core.exceptions import ResourceNotFoundError

from kml_satellite.models.tenants import Job, JobStatus

if TYPE_CHECKING:
    from azure.storage.blob import ContainerClient

logger = logging.getLogger(__name__)


class JobRepository:
    """Repository for Job CRUD operations in Blob Storage JSON.

    Encapsulates blob storage operations with type-safe Pydantic model conversion.
    Job documents stored at: {container}/jobs/{tenant_id}/{job_id}.json

    Args:
        container: Blob ContainerClient for the data container.
    """

    _JOBS_PREFIX = "jobs"

    def __init__(self, container: ContainerClient) -> None:
        self._container = container

    def _job_blob_path(self, tenant_id: str, job_id: str) -> str:
        """Generate blob path for a job document.

        Args:
            tenant_id: Tenant identifier (partition key).
            job_id: Job identifier.

        Returns:
            Blob path (e.g., "jobs/tenant-001/job-abc123.json").
        """
        return f"{self._JOBS_PREFIX}/{tenant_id}/{job_id}.json"

    def create(self, job: Job) -> None:
        """Create a new job document.

        Args:
            job: Job model to persist.

        Raises:
            Exception: On blob upload failure (retryable).
        """
        blob_path = self._job_blob_path(job.tenant_id, job.job_id)
        payload = job.model_dump_json()
        try:
            blob_client = self._container.get_blob_client(blob_path)
            blob_client.upload_blob(payload, overwrite=False)
            logger.info(
                "Job created: %s (tenant=%s, status=%s) → %s",
                job.job_id,
                job.tenant_id,
                job.status.value,
                blob_path,
            )
        except Exception as exc:
            logger.error("Failed to create job %s: %s", job.job_id, exc)
            raise

    def get(self, tenant_id: str, job_id: str) -> Job | None:
        """Retrieve a job by ID.

        Args:
            tenant_id: Tenant identifier (partition key).
            job_id: Job identifier.

        Returns:
            Job model if found, None otherwise.

        Raises:
            Exception: On blob download failure (retryable, except 404).
        """
        blob_path = self._job_blob_path(tenant_id, job_id)
        try:
            blob_client = self._container.get_blob_client(blob_path)
            payload = blob_client.download_blob().readall()
            doc = json.loads(payload)
            return Job.model_validate(doc)
        except ResourceNotFoundError:
            logger.debug("Job not found: %s (tenant=%s, blob=%s)", job_id, tenant_id, blob_path)
            return None
        except json.JSONDecodeError as exc:
            logger.error("Corrupt job blob %s: %s", blob_path, exc)
            return None
        except Exception as exc:
            logger.error("Failed to get job %s: %s", job_id, exc)
            raise

    def update(self, job: Job) -> None:
        """Update an existing job document.

        Uses overwrite=True, so creates if missing.

        Args:
            job: Job model with updated fields.

        Raises:
            Exception: On blob upload failure (retryable).
        """
        blob_path = self._job_blob_path(job.tenant_id, job.job_id)
        payload = job.model_dump_json()
        try:
            blob_client = self._container.get_blob_client(blob_path)
            blob_client.upload_blob(payload, overwrite=True)
            logger.info(
                "Job updated: %s (tenant=%s, status=%s) → %s",
                job.job_id,
                job.tenant_id,
                job.status.value,
                blob_path,
            )
        except Exception as exc:
            logger.error("Failed to update job %s: %s", job.job_id, exc)
            raise

    def delete(self, tenant_id: str, job_id: str) -> None:
        """Delete a job by ID.

        Margaret Hamilton: This is a destructive operation. Used for cleanup
        or tenant offboarding.

        Args:
            tenant_id: Tenant identifier (partition key).
            job_id: Job identifier.

        Raises:
            Exception: On blob delete failure (retryable, except 404).
        """
        blob_path = self._job_blob_path(tenant_id, job_id)
        try:
            blob_client = self._container.get_blob_client(blob_path)
            blob_client.delete_blob()
            logger.info("Job deleted: %s (tenant=%s, blob=%s)", job_id, tenant_id, blob_path)
        except ResourceNotFoundError:
            logger.warning(
                "Attempted to delete nonexistent job: %s (tenant=%s)", job_id, tenant_id
            )
        except Exception as exc:
            logger.error("Failed to delete job %s: %s", job_id, exc)
            raise

    def list_for_tenant(self, tenant_id: str) -> list[Job]:
        """List all jobs for a specific tenant.

        Uses tenant-partitioned blob prefix for efficient listing.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            List of Job models for the tenant, sorted by started_at (newest first).

        Raises:
            Exception: On blob listing failure (retryable).
        """
        try:
            jobs: list[Job] = []
            prefix = f"{self._JOBS_PREFIX}/{tenant_id}/"
            blobs = self._container.list_blobs(name_starts_with=prefix)
            for blob in blobs:
                try:
                    blob_client = self._container.get_blob_client(blob.name)
                    payload = blob_client.download_blob().readall()
                    doc = json.loads(payload)
                    job = Job.model_validate(doc)
                    jobs.append(job)
                except (json.JSONDecodeError, ValueError):
                    logger.warning("Skipping corrupt job blob: %s", blob.name)
                    continue

            # Sort by started_at descending (newest first)
            jobs.sort(key=lambda j: j.started_at, reverse=True)

            logger.debug("Listed %d jobs for tenant=%s", len(jobs), tenant_id)
            return jobs
        except Exception as exc:
            logger.error("Failed to list jobs for tenant %s: %s", tenant_id, exc)
            raise

    def list_by_status(self, tenant_id: str, status: JobStatus) -> list[Job]:
        """List jobs for a tenant filtered by status.

        Scans tenant's jobs and filters in-memory (no server-side query).

        Args:
            tenant_id: Tenant identifier.
            status: Job status to filter by.

        Returns:
            List of Job models matching the status.

        Raises:
            Exception: On blob listing failure (retryable).
        """
        all_jobs = self.list_for_tenant(tenant_id)
        filtered = [j for j in all_jobs if j.status == status]
        logger.debug(
            "Listed %d jobs for tenant=%s with status=%s",
            len(filtered),
            tenant_id,
            status.value,
        )
        return filtered
