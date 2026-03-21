"""Tests for structured logging (§10)."""

from __future__ import annotations

import logging

from treesight.log import log_error, log_phase


class TestLogPhase:
    def test_returns_message(self):
        msg = log_phase("ingestion", "parse_kml", feature_count=5)
        assert "phase=ingestion" in msg
        assert "step=parse_kml" in msg
        assert "feature_count=5" in msg

    def test_includes_instance_id(self):
        msg = log_phase("pipeline", "start", instance_id="abc-123")
        assert "instance=abc-123" in msg

    def test_includes_blob_name(self):
        msg = log_phase("ingestion", "parse", blob_name="test.kml")
        assert "blob=test.kml" in msg


class TestLogError:
    def test_logs_at_error_level(self, caplog):
        with caplog.at_level(logging.ERROR, logger="treesight"):
            log_error("fulfilment", "download_failed", "connection reset")
        assert "error=connection reset" in caplog.text
