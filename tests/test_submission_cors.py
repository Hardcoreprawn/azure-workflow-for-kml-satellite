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

from tests.conftest import TEST_ORIGIN


def _make_request(
    body: dict[str, Any] | None = None,
    *,
    origin: str = TEST_ORIGIN,
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


class TestSubmissionCORSPreflight:
    """Both submission endpoints must respond to OPTIONS preflight requests.

    The ``@bp.durable_client_input`` decorator makes it hard to call the
    endpoint directly in tests, so we verify:
      1. cors_preflight produces the expected 204 with full CORS headers,
      2. the route source contains the OPTIONS guard (structural assertion).
    """

    def test_cors_preflight_returns_204_with_headers(self):
        from blueprints._helpers import cors_preflight

        req = MagicMock()
        req.headers = {"Origin": TEST_ORIGIN}

        resp = cors_preflight(req)

        assert resp.status_code == 204
        assert resp.headers["Access-Control-Allow-Origin"] == TEST_ORIGIN
        assert "POST" in resp.headers["Access-Control-Allow-Methods"]
        assert "Authorization" in resp.headers["Access-Control-Allow-Headers"]

    def test_analysis_submit_has_options_guard(self):
        import inspect

        import blueprints.pipeline.submission as mod

        src = inspect.getsource(mod)
        # Route must accept OPTIONS
        assert 'methods=["POST", "OPTIONS"]' in src or "methods=['POST', 'OPTIONS']" in src, (
            "analysis/submit route must accept OPTIONS for CORS preflight"
        )

    def test_demo_process_has_options_guard(self):
        import inspect

        import blueprints.pipeline.submission as mod

        src = inspect.getsource(mod)
        # Both routes must call cors_preflight on OPTIONS
        assert "cors_preflight" in src, "submission endpoints must call cors_preflight"


class TestAnalysisSubmitCORS:
    """_submit_analysis_request must include CORS headers on every response."""

    @patch("blueprints.pipeline.submission._persist_submission_record")
    @patch("blueprints.pipeline.submission.consume_quota", return_value=5)
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
        assert resp.headers["Access-Control-Allow-Origin"] == TEST_ORIGIN

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
        side_effect=ValueError("Quota exhausted"),
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
    @patch("blueprints.pipeline.submission.consume_quota", return_value=5)
    @patch("blueprints.pipeline.submission.release_quota")
    @pytest.mark.asyncio
    async def test_invalid_json_error_has_cors_headers(self, mock_release, mock_quota, mock_auth):
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
    @patch("blueprints.pipeline.submission.consume_quota", return_value=5)
    @patch("blueprints.pipeline.submission.release_quota")
    @pytest.mark.asyncio
    async def test_missing_kml_error_has_cors_headers(self, mock_release, mock_quota, mock_auth):
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
    """error_response must include CORS headers when a request is available."""

    def test_error_response_without_req_has_no_cors(self):
        """Baseline: plain error_response (no req) has no CORS — this is expected."""
        from blueprints._helpers import error_response

        resp = error_response(400, "bad request")
        assert resp.status_code == 400
        # Without a request object, there's no Origin to reflect
        assert "Access-Control-Allow-Origin" not in resp.headers


class TestSubmissionResilience:
    """Submission must handle transient infrastructure failures gracefully."""

    @patch("blueprints.pipeline.submission._persist_submission_record")
    @patch(
        "blueprints.pipeline.submission.consume_quota",
        side_effect=ConnectionError("Cosmos unavailable"),
    )
    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_quota_storage_error_still_allows_submission(
        self, mock_storage_cls, mock_auth, mock_quota, mock_persist
    ):
        """If quota storage is transiently unavailable, submit anyway."""
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 202, "Transient quota storage error should not block submission"

    @patch(
        "blueprints.pipeline.submission.consume_quota",
        return_value=5,
    )
    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch(
        "treesight.storage.client.BlobStorageClient",
        side_effect=ConnectionError("Storage down"),
    )
    @patch("blueprints.pipeline.submission.release_quota")
    @pytest.mark.asyncio
    async def test_storage_failure_returns_502_and_refunds_quota(
        self, mock_release, mock_storage_cls, mock_auth, mock_quota
    ):
        """If KML upload fails, return 502 with CORS and refund quota."""
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        req = _make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 502
        assert "Access-Control-Allow-Origin" in resp.headers
        mock_release.assert_called_once_with("user-1")

    @patch("blueprints.pipeline.submission._persist_submission_record")
    @patch(
        "blueprints.pipeline.submission.consume_quota",
        return_value=5,
    )
    @patch(
        "blueprints.pipeline.submission.check_auth",
        return_value=({"sub": "user-1"}, "user-1"),
    )
    @patch("treesight.storage.client.BlobStorageClient")
    @patch("blueprints.pipeline.submission.release_quota")
    @pytest.mark.asyncio
    async def test_orchestrator_failure_returns_502_and_refunds_quota(
        self, mock_release, mock_storage_cls, mock_auth, mock_quota, mock_persist
    ):
        """If orchestrator start fails, return 502 with CORS and refund quota."""
        from blueprints.pipeline.submission import _submit_analysis_request

        client = AsyncMock()
        client.start_new.side_effect = RuntimeError("Durable runtime unavailable")
        req = _make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req, client, blob_prefix="analysis")

        assert resp.status_code == 502
        assert "Access-Control-Allow-Origin" in resp.headers
        mock_release.assert_called_once_with("user-1")
