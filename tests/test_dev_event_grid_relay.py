"""Tests for the local Event Grid relay (pure logic only, #1269 follow-up).

The polling loop itself talks to real Azurite/func over the network and is
exercised for real by `make dev-all`, not something worth mocking here —
only the decision logic (which blobs to relay, what's new) is unit-tested.
The one exception is TestRelayForeverSeedsExistingBlobs, which proves the
startup-replay regression with a fully faked BlobServiceClient.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.dev_event_grid_relay as dev_event_grid_relay
from scripts.dev_event_grid_relay import _extract_eventgrid_key, _is_relayable_blob, _new_blobs


class TestIsRelayableBlob:
    def test_kml_upload_is_relayable(self):
        assert _is_relayable_blob("analysis/abc123.kml") is True

    def test_kmz_upload_is_relayable(self):
        assert _is_relayable_blob("analysis/abc123.KMZ") is True

    def test_ticket_metadata_blob_is_not_relayable(self):
        """blueprints/upload.py's _write_ticket_and_mint_sas writes a JSON
        ticket to .tickets/{id}.json in the same container as the KML —
        that must never be sent to blob_trigger as if it were an upload."""
        assert _is_relayable_blob(".tickets/abc123.json") is False

    def test_unrelated_extension_is_not_relayable(self):
        assert _is_relayable_blob("analysis/readme.txt") is False


class TestNewBlobs:
    def test_returns_blobs_not_previously_seen(self):
        seen = {"a.kml"}
        current = {"a.kml", "b.kml"}
        assert _new_blobs(seen, current) == ["b.kml"]

    def test_returns_empty_when_nothing_new(self):
        seen = {"a.kml"}
        current = {"a.kml"}
        assert _new_blobs(seen, current) == []

    def test_returns_sorted_order_for_multiple_new_blobs(self):
        seen: set[str] = set()
        current = {"c.kml", "a.kml", "b.kml"}
        assert _new_blobs(seen, current) == ["a.kml", "b.kml", "c.kml"]


class TestExtractEventgridKey:
    """The func host stores its auto-generated keys as a plaintext blob in
    Azurite (azure-webjobs-secrets) locally -- there's no real identity to
    encrypt against. Regenerated on every func restart, so it's read fresh
    rather than hardcoded."""

    def test_returns_eventgrid_extension_key(self):
        host_json = json.dumps(
            {
                "systemKeys": [
                    {"name": "durabletask_extension", "value": "durable-key"},
                    {"name": "eventgrid_extension", "value": "eg-key"},
                ]
            }
        )
        assert _extract_eventgrid_key(host_json) == "eg-key"

    def test_returns_none_when_key_absent(self):
        host_json = json.dumps({"systemKeys": [{"name": "durabletask_extension", "value": "x"}]})
        assert _extract_eventgrid_key(host_json) is None

    def test_returns_none_for_invalid_json(self):
        assert _extract_eventgrid_key("not json") is None

    def test_returns_none_for_missing_system_keys(self):
        assert _extract_eventgrid_key(json.dumps({})) is None

    def test_returns_none_when_payload_is_not_a_dict(self):
        assert _extract_eventgrid_key(json.dumps(["not", "a", "dict"])) is None

    def test_returns_none_when_system_keys_is_not_a_list(self):
        assert _extract_eventgrid_key(json.dumps({"systemKeys": "oops"})) is None

    def test_skips_non_dict_entries_in_system_keys(self):
        host_json = json.dumps(
            {"systemKeys": ["oops", {"name": "eventgrid_extension", "value": "eg-key"}]}
        )
        assert _extract_eventgrid_key(host_json) == "eg-key"


class _FakeContainerClient:
    """Fake Azurite container client whose list_blobs() result changes per call."""

    def __init__(self, snapshots: list[set[str]]):
        self._snapshots = snapshots
        self._calls = 0

    def list_blobs(self):
        index = min(self._calls, len(self._snapshots) - 1)
        self._calls += 1
        return [SimpleNamespace(name=name) for name in self._snapshots[index]]

    def get_blob_client(self, _name):
        return SimpleNamespace(get_blob_properties=lambda: SimpleNamespace(size=1))


class _FakeBlobServiceClient:
    def __init__(self, container_client):
        self._container_client = container_client

    def get_container_client(self, _name):
        return self._container_client


class _StopRelayError(Exception):
    """Raised from a patched time.sleep to break relay_forever's infinite loop."""


class TestRelayForeverSeedsExistingBlobs:
    """A relay restart must not replay blobs that were already there — only
    genuinely new uploads (arriving after the relay starts watching) fire."""

    def test_does_not_replay_blob_present_before_startup(self, monkeypatch):
        # "old.kml" is already in the container when the relay starts polling;
        # "new.kml" only appears on the first poll after startup.
        container_client = _FakeContainerClient([{"old.kml"}, {"old.kml", "new.kml"}])
        fake_client = _FakeBlobServiceClient(container_client)
        monkeypatch.setattr(
            dev_event_grid_relay.BlobServiceClient,
            "from_connection_string",
            lambda _conn_str: fake_client,
        )
        monkeypatch.setattr(
            dev_event_grid_relay, "_fetch_eventgrid_key", lambda _client: "test-key"
        )
        relayed: list[str] = []
        monkeypatch.setattr(
            dev_event_grid_relay,
            "fire_event_grid",
            lambda **kwargs: relayed.append(kwargs["blob_name"]),
        )

        def _fake_sleep(_seconds):
            raise _StopRelayError

        monkeypatch.setattr(dev_event_grid_relay.time, "sleep", _fake_sleep)

        with pytest.raises(_StopRelayError):
            dev_event_grid_relay.relay_forever(poll_interval=0)

        assert relayed == ["new.kml"]
