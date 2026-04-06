"""Tests for structured logging (§10)."""

from __future__ import annotations

import importlib
import io
import json
import logging
import os
import sys
import time

from treesight.log import (
    APP_LOGGER_NAMES,
    JsonFormatter,
    configure_logging,
    correlation_id,
    log_duration,
    log_error,
    log_phase,
)


def _capture_handler_payload(logger_name: str, emit: callable) -> dict[str, object]:
    logger = logging.getLogger(logger_name)
    handler = logger.handlers[0]
    stream = io.StringIO()
    previous_stream = handler.setStream(stream)
    try:
        emit()
        handler.flush()
    finally:
        handler.setStream(previous_stream)
    return json.loads(stream.getvalue().strip())


def _reset_configured_loggers() -> None:
    for logger_name in APP_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)


class TestLogPhase:
    def test_returns_message(self):
        msg = log_phase("ingestion", "parse_kml", feature_count=5)
        assert "phase=ingestion" in msg
        assert "step=parse_kml" in msg
        # Extras must NOT appear in the clear-text msg (security: CodeQL #2722)
        assert "feature_count" not in msg

    def test_extras_in_custom_properties(self, caplog):
        with caplog.at_level(logging.INFO, logger="treesight"):
            log_phase("ingestion", "parse_kml", feature_count=5)
        record = caplog.records[-1]
        props = record.custom_properties
        assert props["feature_count"] == 5

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
        # duration_ms is an extra — must NOT appear in clear-text msg
        assert "duration_ms=" not in msg
        props = caplog.records[0].custom_properties  # type: ignore[attr-defined]
        assert props["duration_ms"] >= 100  # at least ~150ms


class TestConfigureLogging:
    def teardown_method(self):
        _reset_configured_loggers()

    def test_installs_json_formatter(self):
        configure_logging(level=logging.DEBUG)
        for logger_name in APP_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            assert len(logger.handlers) == 1
            assert isinstance(logger.handlers[0].formatter, JsonFormatter)
            assert logger.level == logging.DEBUG
            assert logger.propagate is False

    def test_is_idempotent(self):
        configure_logging(level=logging.INFO)
        configure_logging(level=logging.INFO)

        for logger_name in APP_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            assert len(logger.handlers) == 1
            assert isinstance(logger.handlers[0].formatter, JsonFormatter)

    def test_child_loggers_emit_json_via_configured_family_handlers(self):
        configure_logging(level=logging.INFO)

        for family_logger, child_logger_name in (
            ("treesight", "treesight.pipeline.fulfilment"),
            ("blueprints", "blueprints.pipeline.activities"),
        ):
            payload = _capture_handler_payload(
                family_logger,
                lambda _name=child_logger_name: logging.getLogger(_name).info("child log message"),
            )
            assert payload["logger"] == child_logger_name
            assert payload["message"] == "child log message"
            assert payload["level"] == "INFO"


class TestFunctionAppStartupLogging:
    def teardown_method(self):
        sys.modules.pop("function_app", None)
        _reset_configured_loggers()

    def test_installs_json_logging_for_deployed_runtime(self, monkeypatch):
        monkeypatch.setenv(
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "InstrumentationKey=test-key;IngestionEndpoint=https://example.invalid/",
        )
        config_mod = importlib.import_module("treesight.config")
        importlib.reload(config_mod)

        sys.modules.pop("function_app", None)
        importlib.import_module("function_app")

        for logger_name in APP_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            assert len(logger.handlers) == 1
            assert isinstance(logger.handlers[0].formatter, JsonFormatter)
            assert logger.propagate is False

    def test_skips_json_logging_for_local_dev(self, monkeypatch):
        monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
        config_mod = importlib.import_module("treesight.config")
        importlib.reload(config_mod)

        sys.modules.pop("function_app", None)
        importlib.import_module("function_app")

        for logger_name in APP_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            assert logger.handlers == []
            assert logger.propagate is True

    def test_start_up_warning_emits_json_when_replay_store_initialisation_fails(self, monkeypatch):
        original_appinsights = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        original_storage = os.environ.get("AzureWebJobsStorage")  # noqa: SIM112

        monkeypatch.setenv(
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "InstrumentationKey=test-key;IngestionEndpoint=https://example.invalid/",
        )
        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")

        config_mod = importlib.import_module("treesight.config")
        log_mod = importlib.import_module("treesight.log")
        security_mod = importlib.import_module("treesight.security")

        importlib.reload(config_mod)

        stream = io.StringIO()
        real_stream_handler = logging.StreamHandler
        monkeypatch.setattr(
            log_mod.logging,
            "StreamHandler",
            lambda *args, **kwargs: real_stream_handler(stream),
        )

        class BoomReplayStore:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(security_mod, "TableReplayStore", BoomReplayStore)

        sys.modules.pop("function_app", None)
        importlib.import_module("function_app")

        payloads = [
            json.loads(line)
            for line in stream.getvalue().splitlines()
            if "Could not initialise Table replay store" in line
        ]
        assert len(payloads) == 1
        assert payloads[0]["logger"] == "function_app"
        assert payloads[0]["level"] == "WARNING"
        assert "exception" in payloads[0]

        if original_appinsights is None:
            monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
        else:
            monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", original_appinsights)
        if original_storage is None:
            monkeypatch.delenv("AzureWebJobsStorage", raising=False)
        else:
            monkeypatch.setenv("AzureWebJobsStorage", original_storage)
        importlib.reload(config_mod)
