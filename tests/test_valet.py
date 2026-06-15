"""Tests for valet token minting and verification (§4.7, §11.2)."""

from __future__ import annotations

import datetime
import importlib
import time
from unittest.mock import MagicMock

import pytest

import treesight.security.replay as replay_mod
import treesight.security.valet as valet_mod

SECRET = "test-valet-secret-32chars-min!!"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _clear_replay():
    """Reset replay store to a fresh InMemoryReplayStore between tests."""
    store = replay_mod.InMemoryReplayStore()
    valet_mod.set_replay_store(store)
    yield
    valet_mod.set_replay_store(replay_mod.InMemoryReplayStore())


class TestMintValetToken:
    def test_returns_string(self):
        token = valet_mod.mint_valet_token(
            submission_id="sub-1",
            submission_blob_name="demo/sub-1.kml",
            artifact_path="imagery/raw/test.tif",
            recipient_email="user@example.com",
            output_container="kml-output",
            secret=SECRET,
        )
        assert isinstance(token, str)
        assert "." in token

    def test_no_secret_raises(self, monkeypatch):
        monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "")
        config_mod = importlib.import_module("treesight.config")
        reloaded_valet = importlib.import_module("treesight.security.valet")

        importlib.reload(config_mod)
        importlib.reload(reloaded_valet)
        try:
            with pytest.raises(ValueError, match="not configured"):
                reloaded_valet.mint_valet_token(
                    submission_id="sub-1",
                    submission_blob_name="demo/sub-1.kml",
                    artifact_path="test.tif",
                    recipient_email="user@example.com",
                    output_container="kml-output",
                    secret="",
                )
        finally:
            monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret-key-for-unit-tests-only")
            importlib.reload(config_mod)
            importlib.reload(reloaded_valet)


class TestVerifyValetToken:
    def _mint(self, **kwargs) -> str:
        defaults = {
            "submission_id": "sub-1",
            "submission_blob_name": "demo/sub-1.kml",
            "artifact_path": "imagery/raw/test.tif",
            "recipient_email": "user@example.com",
            "output_container": "kml-output",
            "secret": SECRET,
        }
        defaults.update(kwargs)
        return valet_mod.mint_valet_token(**defaults)

    def test_valid_token(self):
        token = self._mint()
        claims = valet_mod.verify_valet_token(token, secret=SECRET)
        assert claims["submission_id"] == "sub-1"
        assert claims["artifact_path"] == "imagery/raw/test.tif"

    def test_tampered_token_rejected(self):
        token = self._mint()
        # Corrupt the signature
        parts = token.split(".")
        tampered = parts[0] + ".AAAA" + parts[1][4:]
        with pytest.raises(ValueError):
            valet_mod.verify_valet_token(tampered, secret=SECRET)

    def test_wrong_secret_rejected(self):
        token = self._mint()
        wrong = "wrong-secret-entirely"  # pragma: allowlist secret
        with pytest.raises(ValueError, match="Invalid token signature"):
            valet_mod.verify_valet_token(token, secret=wrong)

    def test_expired_token_rejected(self):
        token = self._mint(ttl_seconds=0)
        time.sleep(0.1)
        with pytest.raises(ValueError, match="expired"):
            valet_mod.verify_valet_token(token, secret=SECRET)

    def test_replay_limit(self):
        token = self._mint(max_uses=2)
        # First two uses succeed
        valet_mod.verify_valet_token(token, secret=SECRET)
        valet_mod.verify_valet_token(token, secret=SECRET)
        # Third use fails
        with pytest.raises(ValueError, match="replay limit"):
            valet_mod.verify_valet_token(token, secret=SECRET)

    def test_malformed_token(self):
        with pytest.raises(ValueError, match="Malformed"):
            valet_mod.verify_valet_token("no-dot-separator", secret=SECRET)

    def test_recipient_email_hashed(self):
        token = self._mint()
        claims = valet_mod.verify_valet_token(token, secret=SECRET)
        assert "recipient_hash" in claims
        assert "@" not in claims.get("recipient_hash", "")


# ---------------------------------------------------------------------------
# TableReplayStore — ETag-based optimistic concurrency (§11.2 M1.8)
# ---------------------------------------------------------------------------


def _make_table_store(table_client: MagicMock) -> replay_mod.TableReplayStore:
    """Build a TableReplayStore backed by a mock table client."""
    store = replay_mod.TableReplayStore.__new__(replay_mod.TableReplayStore)
    store._table_name = "valetreplay"
    store._table_client = table_client
    return store


def _future_entity(use_count: int = 1) -> dict:
    """Return a table entity with a future expiry."""
    return {
        "PartitionKey": "testnon",
        "RowKey": "testnonce123456",
        "use_count": use_count,
        "expires": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    }


class TestTableReplayStore:
    """TableReplayStore with ETag-based optimistic concurrency (§11.2 M1.8)."""

    def test_first_use_creates_entity_and_returns_zero(self):
        from azure.core.exceptions import ResourceNotFoundError

        table = MagicMock()
        table.get_entity.side_effect = ResourceNotFoundError()

        store = _make_table_store(table)
        result = store.get_and_increment("testnonce123456", 60)

        assert result == 0
        table.create_entity.assert_called_once()
        created = table.create_entity.call_args[0][0]
        assert created["use_count"] == 1

    def test_subsequent_use_increments_and_returns_previous_count(self):
        table = MagicMock()
        table.get_entity.return_value = _future_entity(use_count=1)

        store = _make_table_store(table)
        result = store.get_and_increment("testnonce123456", 60)

        assert result == 1
        table.update_entity.assert_called_once()

    def test_etag_conflict_retries_and_succeeds(self):
        """One ETag conflict is transparently retried."""
        from azure.core.exceptions import ResourceModifiedError

        table = MagicMock()
        # Return a fresh copy each call so mutation from attempt 1 doesn't leak.
        table.get_entity.side_effect = [_future_entity(use_count=2), _future_entity(use_count=2)]
        # First update conflicts; second succeeds.
        table.update_entity.side_effect = [ResourceModifiedError(), None]

        store = _make_table_store(table)
        result = store.get_and_increment("testnonce123456", 60)

        assert result == 2
        assert table.get_entity.call_count == 2
        assert table.update_entity.call_count == 2

    def test_max_retries_exceeded_raises_runtime_error(self):
        from azure.core.exceptions import ResourceModifiedError

        table = MagicMock()
        table.get_entity.return_value = _future_entity(use_count=1)
        table.update_entity.side_effect = ResourceModifiedError()

        store = _make_table_store(table)
        with pytest.raises(RuntimeError, match="max retries"):
            store.get_and_increment("testnonce123456", 60)

        assert table.update_entity.call_count == replay_mod._MAX_RETRIES

    def test_creation_race_retries_and_succeeds(self):
        """When another instance creates the entity first, the loser retries the read."""
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        table = MagicMock()
        # First read: not found; after failed create, second read returns entity.
        table.get_entity.side_effect = [ResourceNotFoundError(), _future_entity(use_count=1)]
        table.create_entity.side_effect = ResourceExistsError()

        store = _make_table_store(table)
        result = store.get_and_increment("testnonce123456", 60)

        assert result == 1
        assert table.get_entity.call_count == 2
        table.update_entity.assert_called_once()

    def test_expired_entity_resets_count_to_zero(self):
        """An entry whose 'expires' is in the past is treated as a fresh start."""
        table = MagicMock()
        expired = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
        table.get_entity.return_value = {
            "PartitionKey": "testnon",
            "RowKey": "testnonce123456",
            "use_count": 5,
            "expires": expired,
        }

        store = _make_table_store(table)
        result = store.get_and_increment("testnonce123456", 3600)

        # Expired entry resets — previous count returned as 0.
        assert result == 0
        table.update_entity.assert_called_once()

    def test_update_called_with_match_condition(self):
        """update_entity must be called with IfNotModified to enforce ETag safety."""
        from azure.core import MatchConditions

        table = MagicMock()
        table.get_entity.return_value = _future_entity(use_count=0)

        store = _make_table_store(table)
        store.get_and_increment("testnonce123456", 60)

        _args, kwargs = table.update_entity.call_args
        assert kwargs.get("match_condition") == MatchConditions.IfNotModified
