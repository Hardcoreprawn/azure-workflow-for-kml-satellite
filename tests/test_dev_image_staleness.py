"""Unit tests for the dev-image staleness guard (scripts/check_dev_image_staleness.py)."""

from __future__ import annotations

import json

from scripts.check_dev_image_staleness import (
    LABEL_KEY,
    main,
    parse_image_label,
    read_image_label,
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


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def test_read_image_label_returns_none_when_docker_missing(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("scripts.check_dev_image_staleness.subprocess.run", _raise)
    assert read_image_label("any:ref") is None


def test_read_image_label_returns_none_on_inspect_failure(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.subprocess.run",
        lambda *a, **k: _FakeCompleted(returncode=1),
    )
    assert read_image_label("missing:ref") is None


def test_read_image_label_parses_label_on_success(monkeypatch):
    payload = _inspect_json({LABEL_KEY: "abc"})
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.subprocess.run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout=payload),
    )
    assert read_image_label("ok:ref") == "abc"


def _write_lock(tmp_path) -> tuple[str, str]:
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"deps\n")
    return str(lock), uv_lock_digest(lock)


def test_main_fresh_returns_zero(tmp_path, monkeypatch, capsys):
    lock_path, digest = _write_lock(tmp_path)
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.read_image_label", lambda *_a, **_k: digest
    )
    assert main(["--image", "x:latest", "--lock", lock_path]) == 0
    assert "in sync" in capsys.readouterr().out


def test_main_stale_returns_one(tmp_path, monkeypatch):
    lock_path, _ = _write_lock(tmp_path)
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.read_image_label",
        lambda *_a, **_k: "b" * 64,
    )
    assert main(["--image", "x:latest", "--lock", lock_path]) == 1


def test_main_stale_with_warn_returns_zero(tmp_path, monkeypatch):
    lock_path, _ = _write_lock(tmp_path)
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.read_image_label",
        lambda *_a, **_k: None,
    )
    assert main(["--image", "x:latest", "--lock", lock_path, "--warn"]) == 0
