"""Tests for valet token minting and verification (§4.7, §11.2)."""

from __future__ import annotations

import importlib
import time

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
