"""Tests for the Cosmos DB persistence layer (treesight.storage.cosmos)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from treesight.storage import cosmos


@pytest.fixture(autouse=True)
def _reset_cosmos_singletons():
    """Reset module-level singletons before and after each test."""
    cosmos.reset_client()
    yield
    cosmos.reset_client()


@pytest.fixture()
def mock_cosmos_env(monkeypatch):
    """Set minimal Cosmos config env vars."""
    monkeypatch.setattr(
        "treesight.config.COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/"
    )
    monkeypatch.setattr("treesight.config.COSMOS_DATABASE_NAME", "treesight")


# --- Client initialisation ---


class TestGetClient:
    def test_raises_when_endpoint_missing(self, monkeypatch):
        monkeypatch.setattr("treesight.config.COSMOS_ENDPOINT", "")
        with pytest.raises(RuntimeError, match="COSMOS_ENDPOINT is not configured"):
            cosmos._get_client()

    @patch("treesight.storage.cosmos.DefaultAzureCredential")
    @patch("treesight.storage.cosmos.CosmosClient")
    def test_creates_client_with_default_credential(
        self, mock_client_cls, mock_cred_cls, mock_cosmos_env
    ):
        mock_cred = MagicMock()
        mock_cred_cls.return_value = mock_cred

        cosmos._get_client()

        mock_cred_cls.assert_called_once()
        mock_client_cls.assert_called_once_with(
            "https://cosmos-test.documents.azure.com:443/",
            credential=mock_cred,
        )

    @patch("treesight.storage.cosmos.DefaultAzureCredential")
    @patch("treesight.storage.cosmos.CosmosClient")
    def test_singleton_returns_same_client(self, mock_client_cls, mock_cred_cls, mock_cosmos_env):
        client1 = cosmos._get_client()
        client2 = cosmos._get_client()
        assert client1 is client2
        assert mock_client_cls.call_count == 1


# --- CRUD operations ---


class TestUpsertItem:
    @patch("treesight.storage.cosmos.get_container")
    def test_upserts_document(self, mock_get_container):
        mock_container = MagicMock()
        mock_container.upsert_item.return_value = {"id": "doc1", "user_id": "u1"}
        mock_get_container.return_value = mock_container

        result = cosmos.upsert_item("runs", {"id": "doc1", "user_id": "u1"})

        mock_container.upsert_item.assert_called_once_with({"id": "doc1", "user_id": "u1"})
        assert result["id"] == "doc1"


class TestReadItem:
    @patch("treesight.storage.cosmos.get_container")
    def test_reads_existing_item(self, mock_get_container):
        mock_container = MagicMock()
        mock_container.read_item.return_value = {"id": "doc1", "user_id": "u1"}
        mock_get_container.return_value = mock_container

        result = cosmos.read_item("runs", "doc1", "u1")

        mock_container.read_item.assert_called_once_with(item="doc1", partition_key="u1")
        assert result is not None
        assert result["id"] == "doc1"

    @patch("treesight.storage.cosmos.get_container")
    def test_returns_none_for_missing_item(self, mock_get_container):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        mock_container = MagicMock()
        mock_container.read_item.side_effect = CosmosResourceNotFoundError(
            status_code=404, message="Not found"
        )
        mock_get_container.return_value = mock_container

        result = cosmos.read_item("runs", "missing", "u1")
        assert result is None


class TestQueryItems:
    @patch("treesight.storage.cosmos.get_container")
    def test_query_with_partition_key(self, mock_get_container):
        mock_container = MagicMock()
        mock_container.query_items.return_value = iter([{"id": "d1"}, {"id": "d2"}])
        mock_get_container.return_value = mock_container

        results = cosmos.query_items(
            "runs",
            "SELECT * FROM c WHERE c.status = @status",
            parameters=[{"name": "@status", "value": "completed"}],
            partition_key="u1",
        )

        assert len(results) == 2
        call_kwargs = mock_container.query_items.call_args[1]
        assert call_kwargs["partition_key"] == "u1"
        assert call_kwargs["enable_cross_partition_query"] is False

    @patch("treesight.storage.cosmos.get_container")
    def test_cross_partition_query(self, mock_get_container):
        mock_container = MagicMock()
        mock_container.query_items.return_value = iter([])
        mock_get_container.return_value = mock_container

        cosmos.query_items("runs", "SELECT * FROM c")

        call_kwargs = mock_container.query_items.call_args[1]
        assert call_kwargs["enable_cross_partition_query"] is True


class TestDeleteItem:
    @patch("treesight.storage.cosmos.get_container")
    def test_deletes_existing_item(self, mock_get_container):
        mock_container = MagicMock()
        mock_get_container.return_value = mock_container

        cosmos.delete_item("runs", "doc1", "u1")

        mock_container.delete_item.assert_called_once_with(item="doc1", partition_key="u1")

    @patch("treesight.storage.cosmos.get_container")
    def test_noop_for_missing_item(self, mock_get_container):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        mock_container = MagicMock()
        mock_container.delete_item.side_effect = CosmosResourceNotFoundError(
            status_code=404, message="Not found"
        )
        mock_get_container.return_value = mock_container

        # Should not raise
        cosmos.delete_item("runs", "missing", "u1")


# --- Reset ---


class TestResetClient:
    @patch("treesight.storage.cosmos.DefaultAzureCredential")
    @patch("treesight.storage.cosmos.CosmosClient")
    def test_reset_clears_singletons(self, mock_client_cls, mock_cred_cls, mock_cosmos_env):
        cosmos._get_client()
        assert cosmos._client is not None

        cosmos.reset_client()
        assert cosmos._client is None
        assert cosmos._database is None
        assert cosmos._credential is None


# --- Security: no key auth ---


class TestNoKeyAuth:
    """Verify the module never uses key-based authentication."""

    def test_no_cosmos_key_in_config(self):
        """COSMOS_KEY should not exist as a config attribute."""
        import treesight.config as cfg

        assert not hasattr(cfg, "COSMOS_KEY"), (
            "COSMOS_KEY should be removed — use DefaultAzureCredential instead"
        )
