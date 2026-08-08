"""Unit tests for the dev-image staleness guard (scripts/check_dev_image_staleness.py)."""

from __future__ import annotations

import json

from scripts.check_dev_image_staleness import (
    LABEL_KEY,
    LABEL_KEY_BUILD,
    build_inputs_digest,
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


# ── build_inputs_digest ────────────────────────────────────────────────────


def test_build_inputs_digest_deterministic(tmp_path):
    df = tmp_path / "Dockerfile.dev"
    df.write_bytes(b"FROM base\n")
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\nname='t'\n")
    rust_dir = tmp_path / "rust"
    rust_dir.mkdir()
    (rust_dir / "lib.rs").write_bytes(b"fn main() {}\n")
    d1 = build_inputs_digest(df, root=tmp_path)
    d2 = build_inputs_digest(df, root=tmp_path)
    assert d1 == d2
    assert len(d1) == 64


def test_build_inputs_digest_changes_when_dockerfile_changes(tmp_path):
    df = tmp_path / "Dockerfile.dev"
    df.write_bytes(b"FROM base\n")
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\n")
    d1 = build_inputs_digest(df, root=tmp_path)
    df.write_bytes(b"FROM base\nRUN apt-get install -y make\n")
    d2 = build_inputs_digest(df, root=tmp_path)
    assert d1 != d2


def test_build_inputs_digest_changes_when_pyproject_changes(tmp_path):
    df = tmp_path / "Dockerfile.dev"
    df.write_bytes(b"FROM base\n")
    pf = tmp_path / "pyproject.toml"
    pf.write_bytes(b"[project]\nname='t'\n")
    d1 = build_inputs_digest(df, root=tmp_path)
    pf.write_bytes(b"[project]\nname='t'\nversion='2'\n")
    d2 = build_inputs_digest(df, root=tmp_path)
    assert d1 != d2


def test_build_inputs_digest_missing_extras_ok(tmp_path):
    df = tmp_path / "Dockerfile.dev"
    df.write_bytes(b"FROM base\n")
    # pyproject.toml and rust/ absent — should not raise.
    digest = build_inputs_digest(df, root=tmp_path)
    assert len(digest) == 64


# ── parse_image_label ──────────────────────────────────────────────────────


def test_parse_image_label_reads_value():
    payload = _inspect_json({LABEL_KEY: "abc123"})
    assert parse_image_label(payload) == "abc123"


def test_parse_image_label_reads_build_label():
    payload = _inspect_json({LABEL_KEY_BUILD: "def456"})
    assert parse_image_label(payload, LABEL_KEY_BUILD) == "def456"


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


# ── staleness_reason ───────────────────────────────────────────────────────


def test_staleness_reason_fresh_when_both_digests_match():
    lock_digest = "a" * 64
    build_digest = "c" * 64
    assert staleness_reason(lock_digest, lock_digest, build_digest, build_digest) is None


def test_staleness_reason_fresh_lock_only_no_build_label():
    digest = "a" * 64
    assert staleness_reason(digest, digest) is None


def test_staleness_reason_stale_when_lock_digests_differ():
    reason = staleness_reason("a" * 64, "b" * 64)
    assert reason is not None
    assert "uv.lock has changed" in reason


def test_staleness_reason_stale_when_label_absent():
    reason = staleness_reason("a" * 64, None)
    assert reason is not None
    assert LABEL_KEY in reason


def test_staleness_reason_stale_when_build_inputs_differ():
    lock_digest = "a" * 64
    reason = staleness_reason(lock_digest, lock_digest, "c" * 64, "d" * 64)
    assert reason is not None
    assert "build inputs" in reason


def test_staleness_reason_fresh_when_build_label_absent_but_lock_matches():
    # image built before the build-inputs label was introduced — treat as fresh
    # (no build label = no new check, not stale).
    lock_digest = "a" * 64
    build_digest = "c" * 64
    assert staleness_reason(lock_digest, lock_digest, build_digest, None) is None


# ── read_image_label ───────────────────────────────────────────────────────


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


# ── main ───────────────────────────────────────────────────────────────────


def _write_lock(tmp_path) -> tuple[str, str]:
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"deps\n")
    return str(lock), uv_lock_digest(lock)


def _write_dockerfile(tmp_path) -> str:
    df = tmp_path / "Dockerfile.dev"
    df.write_bytes(b"FROM base\n")
    return str(df)


def test_main_print_build_digest_outputs_hex(tmp_path, capsys):
    df = tmp_path / "Dockerfile.dev"
    df.write_bytes(b"FROM base\n")
    result = main(["--print-build-digest", "--dockerfile", str(df)])
    assert result == 0
    out = capsys.readouterr().out.strip()
    assert len(out) == 64
    assert out == build_inputs_digest(df, root=tmp_path)


    lock_path, lock_digest = _write_lock(tmp_path)
    dockerfile_path = _write_dockerfile(tmp_path)
    expected_build = build_inputs_digest(dockerfile_path, root=tmp_path)

    def _fake_read(image_ref, label_key=LABEL_KEY):
        return lock_digest if label_key == LABEL_KEY else expected_build

    monkeypatch.setattr("scripts.check_dev_image_staleness.read_image_label", _fake_read)
    assert main(["--image", "x:latest", "--lock", lock_path, "--dockerfile", dockerfile_path]) == 0
    assert "in sync" in capsys.readouterr().out


def test_main_stale_returns_one(tmp_path, monkeypatch):
    lock_path, _ = _write_lock(tmp_path)
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.read_image_label",
        lambda *_a, **_k: "b" * 64,
    )
    assert main(["--image", "x:latest", "--lock", lock_path]) == 1


def test_main_stale_build_inputs_returns_one(tmp_path, monkeypatch):
    lock_path, lock_digest = _write_lock(tmp_path)
    dockerfile_path = _write_dockerfile(tmp_path)

    def _fake_read(image_ref, label_key=LABEL_KEY):
        if label_key == LABEL_KEY:
            return lock_digest
        return "stale_build" + "0" * 58  # wrong build hash

    monkeypatch.setattr("scripts.check_dev_image_staleness.read_image_label", _fake_read)
    assert main(["--image", "x:latest", "--lock", lock_path, "--dockerfile", dockerfile_path]) == 1


def test_main_stale_with_warn_returns_zero(tmp_path, monkeypatch):
    lock_path, _ = _write_lock(tmp_path)
    monkeypatch.setattr(
        "scripts.check_dev_image_staleness.read_image_label",
        lambda *_a, **_k: None,
    )
    assert main(["--image", "x:latest", "--lock", lock_path, "--warn"]) == 0

