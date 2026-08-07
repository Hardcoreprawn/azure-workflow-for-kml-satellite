"""Per-IP rate limiter for API endpoints.

Two implementations are provided:

* ``RateLimiter`` — in-memory sliding-window counter. Suitable for
  single-instance deployments and local development / tests.

* ``TableRateLimiter`` — fixed-window counter backed by Azure Table Storage.
  Survives restarts and works correctly across multiple instances.
  Swap in at startup via ``set_form_limiter`` / ``set_pipeline_limiter`` /
  ``set_demo_limiter`` once the storage connection is available.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from azure.data.tables import TableServiceClient

from treesight.constants import (
    RATE_LIMIT_DEMO_MAX,
    RATE_LIMIT_DEMO_WINDOW,
    RATE_LIMIT_FORM_MAX,
    RATE_LIMIT_FORM_WINDOW,
    RATE_LIMIT_PIPELINE_MAX,
    RATE_LIMIT_PIPELINE_WINDOW,
)

logger = logging.getLogger(__name__)

# Maximum optimistic-concurrency retries before giving up and allowing the
# request (fail-open keeps the API available even under extreme contention).
_MAX_RETRIES = 5


class RateLimiterProtocol(Protocol):
    """Common interface for both in-memory and distributed rate limiters."""

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit, False otherwise."""
        ...

    def reset(self) -> None:
        """Clear all rate limit state (for testing)."""
        ...


class RateLimiter:
    """Thread-safe sliding-window rate limiter keyed by arbitrary string (e.g. IP).

    Suitable for single-instance deployments and local development.  Does NOT
    survive process restarts or scale-out.  Use ``TableRateLimiter`` for
    distributed deployments.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit, False otherwise."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            timestamps = self._hits.get(key, [])
            # Prune expired entries
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._max:
                self._hits[key] = timestamps
                return False
            timestamps.append(now)
            self._hits[key] = timestamps
            return True

    def reset(self) -> None:
        """Clear all rate limit state (for testing)."""
        with self._lock:
            self._hits.clear()


class TableRateLimiter:
    """Distributed fixed-window rate limiter backed by Azure Table Storage.

    Survives function-app restarts and works correctly when multiple instances
    run concurrently.  Uses optimistic concurrency (ETag) to handle races.

    Table schema (one row per *limiter_name* + *key* pair):
      PartitionKey  — limiter_name (e.g. "form", "pipeline")
      RowKey        — the rate-limit key (typically the client IP address)
      count         — number of requests in the current window (int)
      window_end    — UTC datetime when the current window expires

    When ``window_end`` has passed, the counter resets to 1 for the new window.
    On ETag conflicts (concurrent updates), the operation is retried up to
    ``_MAX_RETRIES`` times.  If all retries are exhausted, the request is
    allowed (fail-open) to avoid blocking legitimate traffic.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        limiter_name: str,
        connection_string: str | None = None,
        table_name: str = "ratelimits",
        *,
        table_service_client: TableServiceClient | None = None,
    ) -> None:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]+", limiter_name):
            raise ValueError(
                f"limiter_name must contain only alphanumeric characters, hyphens, "
                f"and underscores; got: {limiter_name!r}"
            )
        if table_service_client is not None:
            self._service = table_service_client
        elif connection_string:
            from azure.data.tables import TableServiceClient

            self._service = TableServiceClient.from_connection_string(connection_string)
        else:
            raise ValueError("Either connection_string or table_service_client is required")
        self._max = max_requests
        self._window = window_seconds
        self._name = limiter_name
        self._table_name = table_name
        self._table_client = None
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._service.create_table_if_not_exists(self._table_name)
        except Exception:
            logger.warning("Could not ensure rate-limit table exists", exc_info=True)

    @property
    def _table(self):
        if self._table_client is None:
            self._table_client = self._service.get_table_client(self._table_name)
        return self._table_client

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit, False otherwise.

        Uses optimistic concurrency; fails open after ``_MAX_RETRIES`` retries.
        """
        import datetime

        from azure.core import MatchConditions
        from azure.core.exceptions import (
            AzureError,
            ResourceExistsError,
            ResourceModifiedError,
            ResourceNotFoundError,
        )
        from azure.data.tables import UpdateMode

        now = datetime.datetime.now(datetime.UTC)
        new_window_end = now + datetime.timedelta(seconds=self._window)
        partition_key = self._name
        row_key = key

        for _ in range(_MAX_RETRIES):
            try:
                entity = self._table.get_entity(
                    partition_key=partition_key, row_key=row_key
                )
                window_end = entity.get("window_end")
                count = int(entity.get("count", 0))

                if window_end is None or now >= window_end:
                    # Window expired — start a new window.
                    entity["count"] = 1
                    entity["window_end"] = new_window_end
                    self._table.update_entity(
                        entity,
                        mode=UpdateMode.REPLACE,
                        match_condition=MatchConditions.IfNotModified,
                    )
                    return True

                if count >= self._max:
                    return False

                entity["count"] = count + 1
                self._table.update_entity(
                    entity,
                    mode=UpdateMode.REPLACE,
                    match_condition=MatchConditions.IfNotModified,
                )
                return True

            except ResourceNotFoundError:
                # No entry yet — create the first one for this window.
                try:
                    self._table.create_entity(
                        {
                            "PartitionKey": partition_key,
                            "RowKey": row_key,
                            "count": 1,
                            "window_end": new_window_end,
                        }
                    )
                    return True
                except ResourceExistsError:
                    # Another instance created it first — retry the read/update.
                    continue

            except ResourceModifiedError:
                # ETag mismatch — another instance updated concurrently — retry.
                continue
            except AzureError:
                logger.warning(
                    "rate_limit: Azure Table error for key=%s limiter=%s; failing open",
                    key,
                    self._name,
                    exc_info=True,
                )
                return True

        # All retries exhausted — fail open to keep the service available.
        logger.warning(
            "rate_limit: all retries exhausted for key=%s limiter=%s; failing open",
            key,
            self._name,
        )
        return True

    def reset(self) -> None:
        """Delete all rate-limit entries for this limiter (for testing)."""
        try:
            entities = self._table.query_entities(
                f"PartitionKey eq '{self._name}'"
            )
            for entity in entities:
                self._table.delete_entity(
                    partition_key=entity["PartitionKey"],
                    row_key=entity["RowKey"],
                )
        except Exception:
            logger.warning("Could not reset rate-limit table entries", exc_info=True)


# ---------------------------------------------------------------------------
# Module-level limiter singletons (default: in-memory, suitable for local dev)
# ---------------------------------------------------------------------------

# Pre-configured limiters for different endpoint tiers
form_limiter: RateLimiterProtocol = RateLimiter(
    max_requests=RATE_LIMIT_FORM_MAX, window_seconds=RATE_LIMIT_FORM_WINDOW
)
pipeline_limiter: RateLimiterProtocol = RateLimiter(
    max_requests=RATE_LIMIT_PIPELINE_MAX, window_seconds=RATE_LIMIT_PIPELINE_WINDOW
)
demo_limiter: RateLimiterProtocol = RateLimiter(
    max_requests=RATE_LIMIT_DEMO_MAX, window_seconds=RATE_LIMIT_DEMO_WINDOW
)


def set_form_limiter(limiter: RateLimiterProtocol) -> None:
    """Replace the module-level form rate limiter (called at app startup)."""
    global form_limiter
    form_limiter = limiter


def set_pipeline_limiter(limiter: RateLimiterProtocol) -> None:
    """Replace the module-level pipeline rate limiter (called at app startup)."""
    global pipeline_limiter
    pipeline_limiter = limiter


def set_demo_limiter(limiter: RateLimiterProtocol) -> None:
    """Replace the module-level demo rate limiter (called at app startup)."""
    global demo_limiter
    demo_limiter = limiter


def wire_rate_limiters(
    connection_string: str | None = None,
    *,
    table_service_client: TableServiceClient | None = None,
) -> None:
    """Wire up distributed Table-backed rate limiters at app startup.

    Replaces the default in-memory singletons with ``TableRateLimiter``
    instances backed by Azure Table Storage.  Pass either *connection_string*
    (for ``AzureWebJobsStorage``) or a pre-built *table_service_client*
    (for managed-identity deployments).

    Called from ``function_app.py`` and ``function_app_orch.py`` once the
    storage connection is available.
    """
    kwargs: dict = {}
    if table_service_client is not None:
        kwargs["table_service_client"] = table_service_client
    elif connection_string:
        kwargs["connection_string"] = connection_string
    else:
        raise ValueError("Either connection_string or table_service_client is required")

    set_form_limiter(
        TableRateLimiter(RATE_LIMIT_FORM_MAX, RATE_LIMIT_FORM_WINDOW, "form", **kwargs)
    )
    set_pipeline_limiter(
        TableRateLimiter(
            RATE_LIMIT_PIPELINE_MAX, RATE_LIMIT_PIPELINE_WINDOW, "pipeline", **kwargs
        )
    )
    set_demo_limiter(
        TableRateLimiter(RATE_LIMIT_DEMO_MAX, RATE_LIMIT_DEMO_WINDOW, "demo", **kwargs)
    )


def get_client_ip(req) -> str:
    """Extract client IP from Azure Functions request headers.

    Prefers Azure-specific headers, then uses the rightmost
    X-Forwarded-For entry (set by the last trusted proxy) to
    resist header spoofing.  Falls back to ``unknown`` if no
    trusted header is available.
    """
    # Azure-specific header (set by SWA / Container Apps)
    azure_ip = req.headers.get("X-Azure-ClientIP", "")
    if azure_ip:
        return azure_ip.strip()

    forwarded = req.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Rightmost entry is set by the last trusted proxy (Azure
        # Container Apps / SWA append the real client IP as the final
        # entry).  This resists spoofing by ignoring client-supplied
        # entries earlier in the chain.
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]

    return "unknown"
