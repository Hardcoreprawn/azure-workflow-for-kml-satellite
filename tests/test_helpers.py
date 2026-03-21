"""Tests for shared helpers (blueprints._helpers) and parsers.ensure_closed."""

from __future__ import annotations

import json

import azure.functions as func
import pytest

from blueprints._helpers import (
    CORS_HEADERS,
    EMAIL_RE,
    MAX_FIELD_LEN,
    cors_preflight,
    error_response,
    sanitise,
)
from treesight.parsers import ensure_closed

# ---------------------------------------------------------------------------
# ensure_closed
# ---------------------------------------------------------------------------


class TestEnsureClosed:
    """Coordinate ring closure utility."""

    def test_already_closed_ring_unchanged(self):
        ring = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
        result = ensure_closed(ring)
        assert result == ring
        assert len(result) == 4

    def test_open_ring_gets_closed(self):
        ring = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
        result = ensure_closed(ring)
        assert result[0] == result[-1]
        assert len(result) == 4

    def test_two_point_ring_not_modified(self):
        ring = [[0.0, 0.0], [1.0, 0.0]]
        result = ensure_closed(ring)
        assert len(result) == 2

    def test_empty_ring_not_modified(self):
        ring: list[list[float]] = []
        result = ensure_closed(ring)
        assert result == []

    def test_closing_appends_copy_not_reference(self):
        ring = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
        ensure_closed(ring)
        ring[0][0] = 999.0
        assert ring[-1][0] == 0.0  # appended copy is independent


# ---------------------------------------------------------------------------
# sanitise
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_strips_whitespace(self):
        assert sanitise("  hello  ") == "hello"

    def test_truncates_to_max_len(self):
        long = "x" * (MAX_FIELD_LEN + 100)
        assert len(sanitise(long)) == MAX_FIELD_LEN

    def test_non_string_returns_empty(self):
        assert sanitise(42) == ""  # type: ignore[arg-type]
        assert sanitise(None) == ""  # type: ignore[arg-type]

    def test_empty_string_returns_empty(self):
        assert sanitise("") == ""


# ---------------------------------------------------------------------------
# error_response
# ---------------------------------------------------------------------------


class TestErrorResponse:
    def test_returns_http_response(self):
        resp = error_response(400, "bad")
        assert isinstance(resp, func.HttpResponse)

    def test_status_code(self):
        resp = error_response(404, "not found")
        assert resp.status_code == 404

    def test_body_is_json(self):
        resp = error_response(500, "oops")
        body = json.loads(resp.get_body())
        assert body == {"error": "oops"}

    def test_mimetype(self):
        resp = error_response(400, "bad")
        assert resp.mimetype == "application/json"


# ---------------------------------------------------------------------------
# cors_preflight
# ---------------------------------------------------------------------------


class TestCorsPreflight:
    def test_returns_204(self):
        resp = cors_preflight()
        assert resp.status_code == 204

    def test_cors_headers_present(self):
        resp = cors_preflight()
        for key, value in CORS_HEADERS.items():
            assert resp.headers.get(key) == value


# ---------------------------------------------------------------------------
# EMAIL_RE
# ---------------------------------------------------------------------------


class TestEmailRegex:
    @pytest.mark.parametrize(
        "email",
        [
            "user@example.com",
            "a@b.co",
            "foo.bar+tag@domain.org",
        ],
    )
    def test_valid_emails(self, email: str):
        assert EMAIL_RE.match(email)

    @pytest.mark.parametrize(
        "email",
        [
            "",
            "no-at-sign",
            "@missing-local.com",
            "spaces in@email.com",
            "user@",
        ],
    )
    def test_invalid_emails(self, email: str):
        assert not EMAIL_RE.match(email)
