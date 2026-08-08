"""Tests for the local Event Grid relay (pure logic only, #1269 follow-up).

The polling loop itself talks to real Azurite/func over the network and is
exercised for real by `make dev-all`, not something worth mocking here —
only the decision logic (which blobs to relay, what's new) is unit-tested.
"""

from __future__ import annotations

import json

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
