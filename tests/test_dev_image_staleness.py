"""Unit tests for the dev-image staleness guard (scripts/check_dev_image_staleness.py)."""

from __future__ import annotations

import json

from scripts.check_dev_image_staleness import (
    LABEL_KEY,
    parse_image_label,
    staleness_reason,
    uv_lock_digest,
)


def _inspect_json(labels: dict[str, str] | None) -> str:
    config: dict[str, object] = {}
    if labels is not None:
        config["Labels"] = labels
    return json.dumps([{"Config": config}])


def test_uv_lock_digest_matches_hashlib(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"resolved deps\n")
    import hashlib

    assert uv_lock_digest(lock) == hashlib.sha256(b"resolved deps\n").hexdigest()


def test_parse_image_label_reads_value():
    payload = _inspect_json({LABEL_KEY: "abc123"})
    assert parse_image_label(payload) == "abc123"


def test_parse_image_label_missing_label_returns_none():
    assert parse_image_label(_inspect_json({"other": "x"})) is None


def test_parse_image_label_empty_value_returns_none():
    # An image built without --build-arg UVLOCK_SHA has an empty label.
    assert parse_image_label(_inspect_json({LABEL_KEY: ""})) is None


def test_parse_image_label_no_config_returns_none():
    assert parse_image_label(_inspect_json(None)) is None


def test_parse_image_label_empty_array_returns_none():
    assert parse_image_label("[]") is None


def test_parse_image_label_invalid_json_returns_none():
    assert parse_image_label("not json") is None


def test_staleness_reason_fresh_when_digests_match():
    digest = "a" * 64
    assert staleness_reason(digest, digest) is None


def test_staleness_reason_stale_when_digests_differ():
    reason = staleness_reason("a" * 64, "b" * 64)
    assert reason is not None
    assert "uv.lock has changed" in reason


def test_staleness_reason_stale_when_label_absent():
    reason = staleness_reason("a" * 64, None)
    assert reason is not None
    assert LABEL_KEY in reason
