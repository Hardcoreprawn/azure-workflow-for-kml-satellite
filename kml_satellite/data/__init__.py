"""Data access layer for Blob Storage JSON operations.

Phase 5 #71: Blob Storage JSON data layer (tenants + jobs).

This package provides repository pattern implementations for Blob Storage
JSON documents, encapsulating storage operations with type-safe Pydantic models.
"""

from __future__ import annotations

__all__ = ["JobRepository", "TenantRepository"]

from kml_satellite.data.job_repository import JobRepository
from kml_satellite.data.tenant_repository import TenantRepository
