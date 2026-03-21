"""Tests for valet token minting and verification (§4.7, §11.2)."""

from __future__ import annotations

import time

import pytest

from treesight.security.valet import (
    _replay_counts,
    mint_valet_token,
    verify_valet_token,
)

SECRET = "test-valet-secret-32chars-min!!"


@pytest.fixture(autouse=True)
def _clear_replay():
    """Reset replay counter between tests."""
    _replay_counts.clear()
    yield
    _replay_counts.clear()


class TestMintValetToken:
    def test_returns_string(self):
        token = mint_valet_token(
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
        import importlib

        import treesight.config
        import treesight.security.valet as valet_mod

        importlib.reload(treesight.config)
        importlib.reload(valet_mod)
        try:
            with pytest.raises(ValueError, match="not configured"):
                valet_mod.mint_valet_token(
                    submission_id="sub-1",
                    submission_blob_name="demo/sub-1.kml",
                    artifact_path="test.tif",
                    recipient_email="user@example.com",
                    output_container="kml-output",
                    secret="",
                )
        finally:
            monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret-key-for-unit-tests-only")
            importlib.reload(treesight.config)
            importlib.reload(valet_mod)


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
        return mint_valet_token(**defaults)

    def test_valid_token(self):
        token = self._mint()
        claims = verify_valet_token(token, secret=SECRET)
        assert claims["submission_id"] == "sub-1"
        assert claims["artifact_path"] == "imagery/raw/test.tif"

    def test_tampered_token_rejected(self):
        token = self._mint()
        # Corrupt the signature
        parts = token.split(".")
        tampered = parts[0] + ".AAAA" + parts[1][4:]
        with pytest.raises(ValueError):
            verify_valet_token(tampered, secret=SECRET)

    def test_wrong_secret_rejected(self):
        token = self._mint()
        with pytest.raises(ValueError, match="Invalid token signature"):
            verify_valet_token(token, secret="wrong-secret-entirely")

    def test_expired_token_rejected(self):
        token = self._mint(ttl_seconds=0)
        time.sleep(0.1)
        with pytest.raises(ValueError, match="expired"):
            verify_valet_token(token, secret=SECRET)

    def test_replay_limit(self):
        token = self._mint(max_uses=2)
        # First two uses succeed
        verify_valet_token(token, secret=SECRET)
        verify_valet_token(token, secret=SECRET)
        # Third use fails
        with pytest.raises(ValueError, match="replay limit"):
            verify_valet_token(token, secret=SECRET)

    def test_malformed_token(self):
        with pytest.raises(ValueError, match="Malformed"):
            verify_valet_token("no-dot-separator", secret=SECRET)

    def test_recipient_email_hashed(self):
        token = self._mint()
        claims = verify_valet_token(token, secret=SECRET)
        assert "recipient_hash" in claims
        assert "@" not in claims.get("recipient_hash", "")
