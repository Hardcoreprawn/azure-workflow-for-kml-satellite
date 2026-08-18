"""Tests for the local blueprint-parity validator's pure decision logic (#1407).

Live HTTP behaviour (hitting real compute/orchestrator containers) is
exercised by running `scripts/validate_blueprint_parity.py` itself against
`make dev-all` — not something worth mocking in unit tests, matching the
convention in tests/test_corpus_runner.py / tests/test_e2e_local.py.
"""

from __future__ import annotations

import httpx
from validate_blueprint_parity import ROUTES, _is_registered


class TestIsRegistered:
    def test_non_404_is_registered(self):
        resp = httpx.Response(200, request=httpx.Request("GET", "http://x/api/health"))
        assert _is_registered(resp) is True

    def test_404_with_body_is_registered(self):
        """A route can be reached and still 404 for business reasons (#1407) —
        e.g. export/{instance_id}/{format} when the instance doesn't exist."""
        resp = httpx.Response(
            404,
            json={"error": "Pipeline not found or not complete"},
            request=httpx.Request("GET", "http://x/api/export/x/eudr-pdf"),
        )
        assert _is_registered(resp) is True

    def test_404_with_empty_body_is_not_registered(self):
        """Azure Functions' own unregistered-route 404 has an empty body."""
        resp = httpx.Response(404, request=httpx.Request("GET", "http://x/api/nope"))
        assert _is_registered(resp) is False

    def test_404_with_whitespace_only_body_is_not_registered(self):
        resp = httpx.Response(404, content=b"   \n", request=httpx.Request("GET", "http://x/api/nope"))
        assert _is_registered(resp) is False


class TestRoutes:
    def test_every_route_has_a_blueprint_label(self):
        assert all(route.blueprint for route in ROUTES)

    def test_every_route_path_is_absolute_api_path(self):
        for route in ROUTES:
            assert route.path.startswith("/api/"), f"{route.path!r} must start with /api/"

    def test_covers_every_registered_http_blueprint(self):
        """ROUTES must cover every blueprint function_registration._http_blueprints()
        actually registers on both roles — not a hand-copied duplicate list, which
        can silently drift out of sync with the real registration set (missed
        the whole `pipeline` blueprint, including /api/analysis/submit and
        /api/orchestrator/{id}, until this test was added). Blueprint objects
        don't expose their registration name, so this compares counts rather
        than names: a mismatch means at least one blueprint has zero route
        coverage here.
        """
        from function_registration import _http_blueprints

        covered = {route.blueprint for route in ROUTES}
        expected_count = len(_http_blueprints())
        assert len(covered) == expected_count, (
            f"ROUTES covers {len(covered)} distinct blueprints "
            f"({sorted(covered)}) but _http_blueprints() registers "
            f"{expected_count} — every blueprint needs at least one route in ROUTES"
        )
