"""Unit tests for the shared Azurite configuration (`scripts/_azurite.py`).

The blob host is env-configurable so CI can run the integration gate *inside*
the dev container with Azurite as a `services:` container reachable by its
network alias (`AZURITE_BLOB_HOST=azurite`), while local dev keeps the
loopback default. See #1086.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _restore_azurite_defaults(monkeypatch: pytest.MonkeyPatch):
    """Reload `_azurite` with a clean env after each test.

    The module reads `AZURITE_BLOB_HOST` at import time and other test modules
    bind its constants by value, so restore the loopback default afterwards to
    avoid leaking an overridden host into later tests.
    """
    yield
    monkeypatch.delenv("AZURITE_BLOB_HOST", raising=False)
    import _azurite

    importlib.reload(_azurite)


def test_blob_host_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURITE_BLOB_HOST", raising=False)
    import _azurite

    mod = importlib.reload(_azurite)

    assert mod.AZURITE_BLOB_HOST == "127.0.0.1"
    assert mod.AZURITE_BLOB_BASE == "http://127.0.0.1:10000/devstoreaccount1"
    assert "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1" in mod.AZURITE_CONN_STR


def test_blob_host_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURITE_BLOB_HOST", "azurite")
    import _azurite

    mod = importlib.reload(_azurite)

    assert mod.AZURITE_BLOB_HOST == "azurite"
    assert mod.AZURITE_BLOB_BASE == "http://azurite:10000/devstoreaccount1"
    assert "BlobEndpoint=http://azurite:10000/devstoreaccount1" in mod.AZURITE_CONN_STR
    assert "QueueEndpoint=http://azurite:10001/devstoreaccount1" in mod.AZURITE_CONN_STR
    assert "TableEndpoint=http://azurite:10002/devstoreaccount1" in mod.AZURITE_CONN_STR


def _unused_local_port() -> int:
    """Bind then immediately release a port so nothing is listening on it."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_azurite_blob_reachable_returns_false_quickly_when_nothing_listening() -> None:
    """Must not retry/backoff like the Azure SDK client does — bounded and fast."""
    import time

    import _azurite

    closed_port = _unused_local_port()
    start = time.monotonic()
    result = _azurite.azurite_blob_reachable(host="127.0.0.1", port=closed_port, timeout=0.2)
    elapsed = time.monotonic() - start

    assert result is False
    assert elapsed < 1.0, f"reachability probe took {elapsed:.2f}s — should fail fast, not retry"


def test_azurite_blob_reachable_returns_true_when_listening() -> None:
    import socket

    import _azurite

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        assert _azurite.azurite_blob_reachable(host="127.0.0.1", port=port, timeout=0.5) is True
