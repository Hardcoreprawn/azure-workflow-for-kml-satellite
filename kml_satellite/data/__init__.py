"""Data access layer for Cosmos DB operations.

Phase 5 #71: Cosmos DB data layer (tenants + jobs containers).

This package provides repository pattern implementations for Cosmos DB
containers, encapsulating SDK operations with type-safe Pydantic models.
"""

from __future__ import annotations

__all__ = ["TenantRepository"]

from kml_satellite.data.tenant_repository import TenantRepository
