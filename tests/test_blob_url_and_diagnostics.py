"""Coverage-focused tests for blob URL helpers and diagnostics endpoints."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import azure.functions as func
import pytest

from blueprints.pipeline import _blob_url
from blueprints.pipeline.diagnostics import (
    _build_analysis_history_route_response,
    _build_orchestrator_status_response,
)
from treesight.errors import ContractError


class TestBlobUrlHelpers:
    def test_expected_blob_host_prefers_development_storage(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("treesight.config.STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
        monkeypatch.setattr("treesight.config.STORAGE_ACCOUNT_NAME", "")
        assert _blob_url._expected_blob_host() == "devstoreaccount1.blob.core.windows.net"

    def test_expected_blob_host_from_blob_endpoint(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "treesight.config.STORAGE_CONNECTION_STRING",
            "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;AccountName=ignored;",
        )
        monkeypatch.setattr("treesight.config.STORAGE_ACCOUNT_NAME", "")
        assert _blob_url._expected_blob_host() == "127.0.0.1"

    def test_expected_blob_host_from_account_name_and_managed_identity(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("treesight.config.STORAGE_CONNECTION_STRING", "AccountName=MyAcct;")
        monkeypatch.setattr("treesight.config.STORAGE_ACCOUNT_NAME", "fallback")
        assert _blob_url._expected_blob_host() == "myacct.blob.core.windows.net"

        monkeypatch.setattr("treesight.config.STORAGE_CONNECTION_STRING", "")
        assert _blob_url._expected_blob_host() == "fallback.blob.core.windows.net"

    def test_is_trusted_blob_host_allows_expected_and_azurite_aliases(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(_blob_url, "_expected_blob_host", lambda: "acct.blob.core.windows.net")
        assert _blob_url._is_trusted_blob_host("acct.blob.core.windows.net") is True
        assert _blob_url._is_trusted_blob_host("localhost") is True
        assert _blob_url._is_trusted_blob_host("evil.example.com") is False

    def test_extract_container_and_blob_name_for_azure_and_azurite(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(_blob_url, "_is_trusted_blob_host", lambda _host: True)

        azure_url = "https://acct.blob.core.windows.net/kml-input/folder/file.kml"
        assert _blob_url._extract_container(azure_url) == "kml-input"
        assert _blob_url._extract_blob_name(azure_url) == "folder/file.kml"

        azurite_url = "http://127.0.0.1:10000/devstoreaccount1/kml-input/folder/file.kmz"
        assert _blob_url._extract_container(azurite_url) == "kml-input"
        assert _blob_url._extract_blob_name(azurite_url) == "folder/file.kmz"

    def test_extract_returns_empty_for_untrusted_host(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(_blob_url, "_is_trusted_blob_host", lambda _host: False)
        assert _blob_url._extract_container("https://evil/x/y") == ""
        assert _blob_url._extract_blob_name("https://evil/x/y") == ""

    @pytest.mark.parametrize(
        ("blob_name", "container_name", "content_length", "code"),
        [
            ("", "kml-input", 100, "EMPTY_BLOB_NAME"),
            ("file.txt", "kml-input", 100, "INVALID_FILE_TYPE"),
            ("file.kml", "", 100, "EMPTY_CONTAINER_NAME"),
            ("file.kml", "kml", 100, "INVALID_CONTAINER"),
            ("file.kml", "kml-input", -1, "INVALID_CONTENT_LENGTH"),
            ("file.kml", "kml-input", 0, "EMPTY_BLOB"),
        ],
    )
    def test_validate_blob_event_errors(self, blob_name, container_name, content_length, code):
        with pytest.raises(ContractError) as exc:
            _blob_url._validate_blob_event(blob_name, container_name, {"contentLength": content_length})
        assert exc.value.code == code


class _Client:
    def __init__(self, status):
        self._status = status

    async def get_status(self, _instance_id):
        return self._status


class TestDiagnostics:
    def _req(self, *, method="GET", route_params=None, url="/api/orchestrator/x"):
        return func.HttpRequest(
            method=method,
            url=url,
            headers={"Origin": "http://localhost:4280"},
            params={},
            route_params=route_params or {},
            body=b"",
        )

    def test_orchestrator_status_options(self):
        resp = asyncio.run(_build_orchestrator_status_response(self._req(method="OPTIONS"), _Client(None)))
        assert resp.status_code == 204

    def test_orchestrator_status_rate_limited(self):
        with patch("blueprints.pipeline.diagnostics.get_pipeline_limiter") as limiter:
            limiter.return_value.is_allowed.return_value = False
            resp = asyncio.run(
                _build_orchestrator_status_response(
                    self._req(route_params={"instance_id": "x"}),
                    _Client(None),
                )
            )
        assert resp.status_code == 429

    def test_orchestrator_status_missing_instance_id(self):
        with patch("blueprints.pipeline.diagnostics.get_pipeline_limiter") as limiter:
            limiter.return_value.is_allowed.return_value = True
            resp = asyncio.run(_build_orchestrator_status_response(self._req(route_params={}), _Client(None)))
        assert resp.status_code == 400

    def test_orchestrator_status_not_found(self):
        with patch("blueprints.pipeline.diagnostics.get_pipeline_limiter") as limiter:
            limiter.return_value.is_allowed.return_value = True
            resp = asyncio.run(
                _build_orchestrator_status_response(self._req(route_params={"instance_id": "missing"}), _Client(None))
            )
        assert resp.status_code == 404

    def test_analysis_history_auth_and_rate_limit_branches(self):
        req = self._req(route_params={}, url="/api/analysis/history")

        with patch("blueprints.pipeline.diagnostics.check_auth", side_effect=ValueError("bad token")):
            resp = asyncio.run(_build_analysis_history_route_response(req, SimpleNamespace()))
            assert resp.status_code == 401

        with patch("blueprints.pipeline.diagnostics.check_auth", return_value=({}, "anonymous")):
            resp = asyncio.run(_build_analysis_history_route_response(req, SimpleNamespace()))
            assert resp.status_code == 401

        with (
            patch("blueprints.pipeline.diagnostics.check_auth", return_value=({}, "user-1")),
            patch("blueprints.pipeline.diagnostics.get_pipeline_limiter") as limiter,
        ):
            limiter.return_value.is_allowed.return_value = False
            resp = asyncio.run(_build_analysis_history_route_response(req, SimpleNamespace()))
            assert resp.status_code == 429

    def test_analysis_history_success_calls_builder(self):
        req = self._req(route_params={}, url="/api/analysis/history")

        fake_resp = func.HttpResponse(json.dumps({"ok": True}), status_code=200, mimetype="application/json")
        with (
            patch("blueprints.pipeline.diagnostics.check_auth", return_value=({}, "user-1")),
            patch("blueprints.pipeline.diagnostics.get_pipeline_limiter") as limiter,
            patch(
                "blueprints.pipeline.diagnostics._build_analysis_history_response",
                return_value=fake_resp,
            ) as builder,
        ):
            limiter.return_value.is_allowed.return_value = True
            resp = asyncio.run(_build_analysis_history_route_response(req, SimpleNamespace()))

        assert resp.status_code == 200
        builder.assert_called_once()
