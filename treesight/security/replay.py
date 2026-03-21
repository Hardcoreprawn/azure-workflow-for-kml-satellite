"""Distributed replay-count store for valet tokens (§11.2, M1.8).

In-memory store for local dev/tests. Azure Table Storage for production.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)


class ReplayStore(Protocol):
    """Interface for checking and incrementing token replay counts."""

    def get_and_increment(self, nonce: str, ttl_seconds: int) -> int:
        """Return the *previous* use count for *nonce*, then increment.

        Implementations should auto-expire entries after *ttl_seconds*.
        """
        ...


class InMemoryReplayStore:
    """Simple in-memory store — works for single-instance or tests."""

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}

    def get_and_increment(self, nonce: str, ttl_seconds: int) -> int:
        now = time.time()
        count, expires = self._counts.get(nonce, (0, 0.0))
        if expires and now > expires:
            count = 0
        prev = count
        self._counts[nonce] = (count + 1, now + ttl_seconds)
        return prev

    def clear(self) -> None:
        self._counts.clear()


class TableReplayStore:
    """Azure Table Storage backed replay store for distributed deployments."""

    def __init__(self, connection_string: str, table_name: str = "valetreplay") -> None:
        from azure.data.tables import TableServiceClient

        self._service = TableServiceClient.from_connection_string(connection_string)
        self._table_name = table_name
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._service.create_table_if_not_exists(self._table_name)
        except Exception:
            logger.warning("Could not ensure replay table exists", exc_info=True)

    @property
    def _table(self):
        return self._service.get_table_client(self._table_name)

    def get_and_increment(self, nonce: str, ttl_seconds: int) -> int:
        import datetime

        from azure.core.exceptions import ResourceNotFoundError

        now = datetime.datetime.now(datetime.UTC)
        expires = now + datetime.timedelta(seconds=ttl_seconds)

        partition_key = nonce[:8] if len(nonce) >= 8 else nonce
        row_key = nonce

        try:
            entity = self._table.get_entity(partition_key=partition_key, row_key=row_key)
            count = int(entity.get("use_count", 0))
            entity_expires = entity.get("expires")
            if entity_expires and entity_expires < now:
                count = 0
            prev = count
            entity["use_count"] = count + 1
            entity["expires"] = expires
            self._table.update_entity(entity, mode="merge")  # type: ignore[arg-type]
            return prev
        except ResourceNotFoundError:
            entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                "use_count": 1,
                "expires": expires,
            }
            self._table.create_entity(entity)
            return 0
