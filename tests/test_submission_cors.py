"""Regression tests for submission endpoint CORS headers.

Bug: _submit_analysis_request and _error_response did not include CORS
headers, causing browsers to block cross-origin responses and hiding
the actual error message from the frontend.

See also: the pipeline progress animation must be reset on API error
(frontend bug tracked separately in app-shell.js).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_request(
    body: dict[str, Any] | None = None,
    *,
    origin: str = "https://treesight.hrdcrprwn.com",
    auth_header: str | None = "Bearer fake-jwt",
) -> MagicMock:
    """Build a mock HttpRequest with Origin and optional auth."""
    req = MagicMock()
    req.method = "POST"
    headers: dict[str, str] = {"Origin": origin}
    if auth_header:
        headers["Authorization"] = auth_header
    req.headers = headers
    if body is not None:
        req.get_json.return_value = body
    else:
        req.get_json.side_effect = ValueError("no json")
    return req


class TestAnalysisSubmitCORS:
    """_submit_analysis_request must include CORS headers on every response."""

    @patch("blueprints.pipeline.submission._persist_submission_record")
    @patch("blueprints.pipeline.submission.consume_quota")
    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_success_response_has_cors_headers(
        self, mock_storage_cls, mock_auth, mock_quota, mock_persist
    ):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 202
        assert "Access-Control-Allow-Origin" in resp.headers, (
            "CORS headers missing on 202 success response — browser will block it"
        )
        assert resp.headers["Access-Control-Allow-Origin"] == "https://treesight.hrdcrprwn.com"

    @patch(
        "blueprints.pipeline.submission.check_auth",
        side_effect=ValueError("Missing or malformed Authorization header"),
    )
    @pytest.mark.asyncio
    async def test_auth_error_has_cors_headers(self, mock_auth):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 401
        assert "Access-Control-Allow-Origin" in resp.headers, (
            "CORS headers missing on 401 error — browser hides the error from JS"
        )

    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch(
        "blueprints.pipeline.submission.consume_quota",
        side_effect=ValueError("Quota exceeded"),
    )
    @pytest.mark.asyncio
    async def test_quota_error_has_cors_headers(self, mock_quota, mock_auth):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 403
        assert "Access-Control-Allow-Origin" in resp.headers, (
            "CORS headers missing on 403 quota error"
        )

    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch("blueprints.pipeline.submission.consume_quota")
    @pytest.mark.asyncio
    async def test_invalid_json_error_has_cors_headers(self, mock_quota, mock_auth):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request()  # no body → ValueError

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 400
        assert "Access-Control-Allow-Origin" in resp.headers, (
            "CORS headers missing on 400 JSON parse error"
        )

    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch("blueprints.pipeline.submission.consume_quota")
    @pytest.mark.asyncio
    async def test_missing_kml_error_has_cors_headers(self, mock_quota, mock_auth):
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request({"kml_content": ""})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 400
        assert "Access-Control-Allow-Origin" in resp.headers, (
            "CORS headers missing on 400 missing kml_content"
        )


class TestDemoSubmitCORSParity:
    """Demo endpoint already has CORS — verify it stays that way (regression guard)."""

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="127.0.0.1")
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_demo_success_has_cors_headers(self, mock_storage_cls, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = True

        client = AsyncMock()
        req = _make_request({"kml_content": "<kml>test</kml>"}, auth_header=None)

        resp = await _submit_demo_request(req, client)

        assert resp.status_code == 202
        assert "Access-Control-Allow-Origin" in resp.headers


class TestErrorResponseCORS:
    """_error_response must include CORS headers when a request is available."""

    def test_error_response_without_req_has_no_cors(self):
        """Baseline: plain _error_response (no req) has no CORS — this is expected."""
        from blueprints.pipeline._helpers import _error_response

        resp = _error_response(400, "bad request")
        assert resp.status_code == 400
        # Without a request object, there's no Origin to reflect
        assert "Access-Control-Allow-Origin" not in resp.headers
