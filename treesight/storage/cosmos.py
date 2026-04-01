"""Cosmos DB for NoSQL persistence layer (§6 storage).

Authentication: Uses DefaultAzureCredential (Managed Identity in Azure,
developer credentials locally). No keys are stored or transmitted.
The Function App's system-assigned MI is granted the Cosmos DB Built-in
Data Contributor role via OpenTofu.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

from treesight import config

logger = logging.getLogger("treesight.storage.cosmos")

_lock = threading.Lock()
_client: CosmosClient | None = None
_database: Any = None
_credential: DefaultAzureCredential | None = None


def _get_client() -> CosmosClient:
    """Lazily initialise a singleton CosmosClient with AAD auth."""
    global _client, _credential
    if _client is None:
        with _lock:
            if _client is None:
                endpoint = config.COSMOS_ENDPOINT
                if not endpoint:
                    raise RuntimeError("COSMOS_ENDPOINT is not configured")
                _credential = DefaultAzureCredential()
                _client = CosmosClient(endpoint, credential=_credential)
    return _client


def _get_database() -> Any:
    """Return the default database proxy."""
    global _database
    if _database is None:
        with _lock:
            if _database is None:
                db_name = config.COSMOS_DATABASE_NAME
                _database = _get_client().get_database_client(db_name)
    return _database


def get_container(name: str) -> Any:
    """Return a container proxy by name."""
    return _get_database().get_container_client(name)


def upsert_item(container_name: str, item: dict[str, Any]) -> dict[str, Any]:
    """Upsert a document into the specified container."""
    container = get_container(container_name)
    return container.upsert_item(item)


def read_item(container_name: str, item_id: str, partition_key: str) -> dict[str, Any] | None:
    """Read a single document by id and partition key. Returns None if not found."""
    container = get_container(container_name)
    try:
        return container.read_item(item=item_id, partition_key=partition_key)
    except CosmosResourceNotFoundError:
        return None


def query_items(
    container_name: str,
    query: str,
    parameters: list[dict[str, Any]] | None = None,
    partition_key: str | None = None,
) -> list[dict[str, Any]]:
    """Query documents. Returns a list of matching items."""
    container = get_container(container_name)
    kwargs: dict[str, Any] = {
        "query": query,
        "enable_cross_partition_query": partition_key is None,
    }
    if parameters:
        kwargs["parameters"] = parameters
    if partition_key is not None:
        kwargs["partition_key"] = partition_key
    return list(container.query_items(**kwargs))


def delete_item(container_name: str, item_id: str, partition_key: str) -> None:
    """Delete a document. No-op if not found."""
    container = get_container(container_name)
    with contextlib.suppress(CosmosResourceNotFoundError):
        container.delete_item(item=item_id, partition_key=partition_key)


def reset_client() -> None:
    """Reset singleton state (for testing)."""
    global _client, _database, _credential
    with _lock:
        if _client is not None:
            with contextlib.suppress(Exception):
                _client.__exit__(None, None, None)
        if _credential is not None:
            with contextlib.suppress(Exception):
                _credential.close()
        _client = None
        _database = None
        _credential = None
