"""Temporal catalogue — per-AOI acquisition history (§3.2, §3.3).

Provides three layers with clean separation of concerns:

- **contracts** — API request/response schemas (what the client sees)
- **models** — Cosmos DB document schema (how data is stored)
- **repository** — persistence operations (read/write to Cosmos)
"""

from treesight.catalogue.contracts import (
    CatalogueEntryResponse,
    CatalogueListResponse,
    CatalogueQueryParams,
)
from treesight.catalogue.models import CatalogueEntry
from treesight.catalogue.repository import (
    get_entry,
    list_entries,
    record_acquisition,
)

__all__ = [
    "CatalogueEntry",
    "CatalogueEntryResponse",
    "CatalogueListResponse",
    "CatalogueQueryParams",
    "get_entry",
    "list_entries",
    "record_acquisition",
]
