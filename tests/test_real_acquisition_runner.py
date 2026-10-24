"""Offline decision and export-boundary tests for the real-acquisition runner."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import real_acquisition_runner as runner
from fpdf import FPDF
from real_acquisition_runner import (
    DEFAULT_FORMATS,
    _build_run_summary,
    _configure_real_acquisition_environment,
    _test_principal_header,
    _wdpa_configuration_warning,
)

from treesight.exports.csv import _build_eudr_csv
from treesight.exports.geojson import _build_eudr_geojson


class TestTestPrincipalHeader:
    def test_round_trips_the_given_user_id(self):
        """_fetch_export authenticates its own export-fetch calls as the same
        identity the ticket was uploaded under (CANOPEX_ALLOW_TEST_PRINCIPAL,
        #1379) — must decode back to exactly that user_id."""
        header = _test_principal_header("real-acquisition-runner")
        principal = json.loads(base64.b64decode(header))
        assert principal["userId"] == "real-acquisition-runner"

    def test_produces_valid_base64(self):
        header = _test_principal_header("some-user")
        # Raises if not valid base64 — validate=True matches the server-side decoder.
        base64.b64decode(header, validate=True)


class TestBuildRunSummary:
    def test_extracts_all_fields_from_a_completed_run(self):
        payload = {
            "runtimeStatus": "Completed",
            "output": {
                "aoiCount": 2,
                "downloadsCompleted": 4,
                "artifacts": {"rawImageryPaths": ["a.tif", "b.tif", "c.tif", "d.tif"]},
            },
        }
        summary = _build_run_summary(payload)
        assert summary == {
            "runtimeStatus": "Completed",
            "aoiCount": 2,
            "downloadsCompleted": 4,
            "rawImageryPathCount": 4,
        }

    def test_handles_missing_output(self):
        summary = _build_run_summary({"runtimeStatus": "Failed"})
        assert summary["aoiCount"] == 0
        assert summary["downloadsCompleted"] == 0
        assert summary["rawImageryPathCount"] == 0

    def test_handles_none_artifacts(self):
        payload = {"runtimeStatus": "Completed", "output": {"downloadsCompleted": 1, "artifacts": None}}
        summary = _build_run_summary(payload)
        assert summary["rawImageryPathCount"] == 0

    def test_handles_empty_raw_paths(self):
        payload = {
            "runtimeStatus": "Completed",
            "output": {"downloadsCompleted": 1, "artifacts": {"rawImageryPaths": []}},
        }
        summary = _build_run_summary(payload)
        assert summary["rawImageryPathCount"] == 0


class TestDefaultFormats:
    def test_defaults_cover_all_three_eudr_export_formats(self):
        assert set(DEFAULT_FORMATS) == {"eudr-pdf", "eudr-geojson", "eudr-csv"}


@pytest.mark.parametrize(
    ("fmt", "body"),
    [
        ("eudr-csv", b"<html>private-response-token</html>"),
        ("eudr-csv", b'parcel_name,determination_status\n"unterminated'),
        ("eudr-csv", b"parcel_name,determination_status\none,two,three\n"),
        ("eudr-csv", b"parcel_name,determination_status\n\xff,unknown\n"),
        ("eudr-csv", b"parcel_name,determination_status\n"),
        ("eudr-geojson", b'{"type":"FeatureCollection","features":'),
        ("eudr-geojson", b'{"type":"FeatureCollection","features":[42]}'),
        ("eudr-geojson", b'{"type":"FeatureCollection","features":[]}'),
        ("eudr-geojson", b'{"type":"FeatureCollection","features":[{"type":"Feature"}]}'),
        (
            "eudr-geojson",
            b'{"type":"FeatureCollection","features":[{"type":"Feature",'
            b'"properties":{},"geometry":{"type":"Polygon","coordinates":"invalid"}}]}',
        ),
        ("eudr-pdf", b"%PDF-1.7\nprivate-response-token\n%%EOF"),
    ],
)
def test_malformed_200_export_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fmt: str,
    body: bytes,
) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
        monkeypatch.setattr(runner.httpx, "get", client.get)
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        result = runner._fetch_export("current-run", fmt, tmp_path)

    assert result.status == "invalid_content"
    assert result.http_status == 200
    assert result.path is None
    assert not list(tmp_path.iterdir())
    captured = capsys.readouterr()
    assert "private-response-token" not in captured.out + captured.err


@pytest.fixture
def readable_exports() -> dict[str, bytes]:
    manifest = {"per_aoi_enrichment": [{"name": "Plot", "coords": [[0, 0], [1, 0], [1, 1], [0, 0]]}]}
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(text="EUDR proof for Plot")
    return {
        "eudr-csv": _build_eudr_csv(manifest).encode(),
        "eudr-geojson": json.dumps(_build_eudr_geojson(manifest)).encode(),
        "eudr-pdf": bytes(pdf.output()),
    }


@pytest.fixture
def proof_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(runner, "upload_kml", Mock(return_value=("plot.kml", "https://example.test/plot.kml", 10)))
    monkeypatch.setattr(runner, "_upload_ticket", Mock())
    monkeypatch.setattr(runner, "fire_event_grid", Mock(return_value="current-run"))
    monkeypatch.setattr(runner, "poll_orchestration", Mock(return_value={"runtimeStatus": "Completed"}))
    monkeypatch.setattr(runner, "assert_pipeline_succeeded", Mock())
    return tmp_path / "plot.kml"


@pytest.mark.parametrize("fmt", DEFAULT_FORMATS)
def test_readable_exports_are_saved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, readable_exports: dict[str, bytes], fmt: str
) -> None:
    body = readable_exports[fmt]
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        result = runner._fetch_export("current-run", fmt, tmp_path)
    assert result.status == "passed"
    assert result.bytes_received == len(body)
    assert result.http_status == 200
    assert result.path is not None
    assert Path(result.path).read_bytes() == body


@pytest.mark.parametrize("status_code", [401, 403, 404, 500, 302])
def test_http_failures_have_body_free_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], status_code: int
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code, text="private-response-token"))
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        result = runner._fetch_export("current-run", "eudr-pdf", tmp_path)
    assert result.status == "http_error"
    assert result.http_status == status_code
    assert result.path is None
    assert not list(tmp_path.iterdir())
    captured = capsys.readouterr()
    assert "private-response-token" not in repr(result) + captured.out + captured.err


@pytest.mark.parametrize(("body", "status"), [(b"", "missing"), (b"x" * 65, "too_large")])
def test_empty_and_oversized_exports_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes, status: str
) -> None:
    monkeypatch.setattr(runner, "LOCAL_AUDIT_MAX_ARTIFACT_BYTES", 64)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        result = runner._fetch_export("current-run", "eudr-pdf", tmp_path)
    assert result.status == status
    assert result.path is None
    assert not list(tmp_path.iterdir())


def test_transport_failure_does_not_disclose_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner.httpx, "stream", Mock(side_effect=httpx.ReadTimeout("private-response-token")))
    result = runner._fetch_export("current-run", "eudr-pdf", tmp_path)
    assert result.status == "transport_error"
    assert result.path is None
    captured = capsys.readouterr()
    assert "private-response-token" not in repr(result) + captured.out + captured.err


def test_pdf_parser_logs_do_not_disclose_rejected_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject_pdf(*args: object, **kwargs: object) -> None:
        logging.getLogger("pypdf._reader").warning("private-response-token")
        raise ValueError("private-response-token")

    monkeypatch.setattr("pypdf.PdfReader", reject_pdf)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"%PDF-1.7\n"))
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        result = runner._fetch_export("current-run", "eudr-pdf", tmp_path)
    assert result.status == "invalid_content"
    captured = capsys.readouterr()
    assert "private-response-token" not in captured.out + captured.err + caplog.text + repr(result)


def test_export_write_failure_returns_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, readable_exports: dict[str, bytes]
) -> None:
    monkeypatch.setattr(Path, "write_bytes", Mock(side_effect=OSError("private-response-token")))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=readable_exports["eudr-csv"]))
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        result = runner._fetch_export("current-run", "eudr-csv", tmp_path)
    assert result.status == "write_error"
    assert result.http_status == 200
    assert result.path is None
    assert "private-response-token" not in repr(result)


@pytest.mark.parametrize("failure", ["timeout", "pipeline_failure"])
def test_pipeline_failure_preserves_instance_and_unattempted_export_diagnostics(
    monkeypatch: pytest.MonkeyPatch, proof_run: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    if failure == "timeout":
        monkeypatch.setattr(runner, "poll_orchestration", Mock(side_effect=TimeoutError("private-response-token")))
    else:
        monkeypatch.setattr(
            runner, "assert_pipeline_succeeded", Mock(side_effect=AssertionError("private-response-token"))
        )
    fetch = Mock()
    monkeypatch.setattr(runner, "_fetch_export", fetch)
    assert not runner.run_fixture(proof_run, formats=DEFAULT_FORMATS)
    result = json.loads((runner.OUTPUT_DIR / proof_run.stem / "current-run" / "result.json").read_text())
    assert result["instance_id"] == "current-run"
    assert result["success"] is False
    assert result["status"] == failure
    assert [export["format"] for export in result["exports"]] == list(DEFAULT_FORMATS)
    assert all(export["status"] == "not_attempted" and export["path"] is None for export in result["exports"])
    fetch.assert_not_called()
    captured = capsys.readouterr()
    assert "current-run" in captured.out + captured.err
    assert "private-response-token" not in captured.out + captured.err + json.dumps(result)


def test_result_write_failure_prevents_success(
    monkeypatch: pytest.MonkeyPatch, proof_run: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "_fetch_export", Mock(return_value=runner.ExportResult("eudr-csv", "passed")))
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("private-response-token")))
    assert not runner.run_fixture(proof_run, formats=("eudr-csv",))
    captured = capsys.readouterr()
    assert "result_write_error" in captured.err
    assert "PASS (mechanical)" not in captured.out
    assert "private-response-token" not in captured.out + captured.err


@pytest.mark.parametrize("failed_body", [None, b"", b"%PDF-1.7\nprivate-response-token\n%%EOF"])
def test_failed_run_records_identity_and_every_export_without_reusing_stale_files(
    monkeypatch: pytest.MonkeyPatch,
    proof_run: Path,
    readable_exports: dict[str, bytes],
    capsys: pytest.CaptureFixture[str],
    failed_body: bytes | None,
) -> None:
    old_dir = runner.OUTPUT_DIR / proof_run.stem / "previous-run"
    old_dir.mkdir(parents=True)
    old_pdf = old_dir / "eudr-pdf.pdf"
    old_pdf.write_bytes(readable_exports["eudr-pdf"])
    current_dir = old_dir.parent / "current-run"
    current_dir.mkdir()
    (current_dir / "eudr-pdf.pdf").write_bytes(readable_exports["eudr-pdf"])

    def respond(request: httpx.Request) -> httpx.Response:
        fmt = request.url.path.rsplit("/", 1)[-1]
        if fmt == "eudr-pdf":
            return httpx.Response(404 if failed_body is None else 200, content=failed_body or b"")
        return httpx.Response(200, content=readable_exports[fmt])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        assert not runner.run_fixture(proof_run, formats=DEFAULT_FORMATS)

    result = json.loads((current_dir / "result.json").read_text())
    assert result["schema_version"] == 1
    assert result["fixture"] == str(proof_run)
    assert result["instance_id"] == "current-run"
    assert result["success"] is False
    assert result["status"] == "export_failure"
    assert [export["format"] for export in result["exports"]] == list(DEFAULT_FORMATS)
    assert [export["status"] for export in result["exports"]] == [
        "http_error" if failed_body is None else "missing" if not failed_body else "invalid_content",
        "passed",
        "passed",
    ]
    assert result["exports"][0]["path"] is None
    assert all(export["http_status"] == 200 for export in result["exports"][1:])
    assert old_pdf.read_bytes() == readable_exports["eudr-pdf"]
    captured = capsys.readouterr()
    assert "private-response-token" not in json.dumps(result) + captured.out + captured.err
    assert "PASS (mechanical)" not in captured.out


def test_successful_run_records_readable_exports_for_current_identity(
    monkeypatch: pytest.MonkeyPatch, proof_run: Path, readable_exports: dict[str, bytes]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=readable_exports[request.url.path.rsplit("/", 1)[-1]])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        assert runner.run_fixture(proof_run, formats=DEFAULT_FORMATS)
    result = json.loads((runner.OUTPUT_DIR / proof_run.stem / "current-run" / "result.json").read_text())
    assert result["success"] is True
    assert result["status"] == "passed"
    assert result["instance_id"] == "current-run"
    assert len(result["exports"]) == 3
    for export in result["exports"]:
        assert export["status"] == "passed"
        assert Path(export["path"]).parent.name == "current-run"
        assert Path(export["path"]).read_bytes() == readable_exports[export["format"]]


def test_cli_continues_after_failure_but_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner.sys, "argv", ["runner", "failed.kml", "passed.kml"])
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "OUTPUT_DIR", tmp_path / "outputs")
    run = Mock(side_effect=[False, True])
    stop = Mock()
    monkeypatch.setattr(runner, "run_fixture", run)
    monkeypatch.setattr(runner, "start_func_host", Mock(return_value="host"))
    monkeypatch.setattr(runner, "wait_for_func_host", Mock())
    monkeypatch.setattr(runner, "stop_func_host", stop)
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 1
    assert run.call_count == 2
    stop.assert_called_once_with("host")
    assert "1 passed, 1 failed out of 2" in capsys.readouterr().out


def test_required_export_failure_fails_fixture(
    monkeypatch: pytest.MonkeyPatch, proof_run: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        monkeypatch.setattr(runner.httpx, "stream", client.stream)
        assert not runner.run_fixture(proof_run, formats=DEFAULT_FORMATS)
    captured = capsys.readouterr()
    assert "PASS (mechanical)" not in captured.out
    assert "current-run" in captured.out + captured.err


class TestWdpaConfiguration:
    def test_warns_when_token_is_missing(self, monkeypatch):
        monkeypatch.delenv("WDPA_API_TOKEN", raising=False)
        warning = _wdpa_configuration_warning()
        assert warning is not None
        assert "WDPA_API_TOKEN" in warning

    def test_does_not_warn_when_token_is_configured(self, monkeypatch):
        monkeypatch.setenv("WDPA_API_TOKEN", "configured")
        assert _wdpa_configuration_warning() is None

    def test_sets_conservative_frame_concurrency_by_default(self, monkeypatch):
        monkeypatch.delenv("ENRICHMENT_FRAME_CONCURRENCY", raising=False)
        _configure_real_acquisition_environment()
        assert os.environ["ENRICHMENT_FRAME_CONCURRENCY"] == "1"

    def test_preserves_explicit_frame_concurrency(self, monkeypatch):
        monkeypatch.setenv("ENRICHMENT_FRAME_CONCURRENCY", "2")
        _configure_real_acquisition_environment()
        assert os.environ["ENRICHMENT_FRAME_CONCURRENCY"] == "2"
