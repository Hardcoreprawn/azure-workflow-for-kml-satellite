"""Tests for structured logging (§10)."""

from __future__ import annotations

import json
import logging
import time

from treesight.log import (
    JsonFormatter,
    configure_logging,
    correlation_id,
    log_duration,
    log_error,
    log_phase,
)


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


class TestJsonFormatter:
    def test_formats_as_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="treesight",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        result = json.loads(formatter.format(record))
        assert result["level"] == "INFO"
        assert result["message"] == "hello"
        assert result["logger"] == "treesight"
        assert "timestamp" in result

    def test_includes_custom_properties(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="treesight",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.custom_properties = {"phase": "ingestion", "step": "parse"}  # type: ignore[attr-defined]
        result = json.loads(formatter.format(record))
        assert result["properties"]["phase"] == "ingestion"
        assert result["properties"]["step"] == "parse"

    def test_includes_correlation_id(self):
        formatter = JsonFormatter()
        token = correlation_id.set("req-abc-123")
        try:
            record = logging.LogRecord(
                name="treesight",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="test",
                args=(),
                exc_info=None,
            )
            result = json.loads(formatter.format(record))
            assert result["correlation_id"] == "req-abc-123"
        finally:
            correlation_id.reset(token)


class TestCorrelationId:
    def test_log_phase_includes_correlation_id(self, caplog):
        token = correlation_id.set("corr-456")
        try:
            with caplog.at_level(logging.INFO, logger="treesight"):
                log_phase("pipeline", "start")
            assert len(caplog.records) == 1
            props = caplog.records[0].custom_properties  # type: ignore[attr-defined]
            assert props["correlation_id"] == "corr-456"
        finally:
            correlation_id.reset(token)

    def test_log_error_includes_correlation_id(self, caplog):
        token = correlation_id.set("corr-789")
        try:
            with caplog.at_level(logging.ERROR, logger="treesight"):
                log_error("fulfilment", "fail", "boom")
            assert len(caplog.records) == 1
            props = caplog.records[0].custom_properties  # type: ignore[attr-defined]
            assert props["correlation_id"] == "corr-789"
        finally:
            correlation_id.reset(token)


class TestLogDuration:
    def test_includes_duration_ms(self, caplog):
        started = time.monotonic() - 0.150  # simulate 150ms ago
        with caplog.at_level(logging.INFO, logger="treesight"):
            msg = log_duration("enrichment", "ndvi", started)
        assert "duration_ms=" in msg
        props = caplog.records[0].custom_properties  # type: ignore[attr-defined]
        assert props["duration_ms"] >= 100  # at least ~150ms


class TestConfigureLogging:
    def test_installs_json_formatter(self):
        configure_logging(level=logging.DEBUG)
        root = logging.getLogger("treesight")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.DEBUG
        # Clean up
        root.handlers.clear()
