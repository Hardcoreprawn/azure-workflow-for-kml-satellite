"""Tests for health check endpoints (Issue #107).

These tests verify that:
1. The /health and /readiness endpoints are registered in function_app.py
2. The endpoints use correct HTTP methods (GET)
3. The endpoints check required dependencies

Full integration testing of HTTP responses happens in the Azure Functions
runtime and CI/CD deployment pipeline.

References:
    Issue #107  (Add health check endpoints)
    PID NFR-3   (99.5% uptime requirement)
"""

from __future__ import annotations

import ast
from pathlib import Path


class TestHealthEndpointsRegistration:
    """Test that health endpoints are properly registered."""

    def test_health_liveness_endpoint_exists(self) -> None:
        """Verify /health endpoint is registered."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Check that health_liveness function exists
        assert "def health_liveness" in content
        # Check decorator for GET method
        assert '@app.route(route="health"' in content
        assert 'methods=["GET"]' in content or "methods=['GET']" in content

    def test_health_readiness_endpoint_exists(self) -> None:
        """Verify /readiness endpoint is registered."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Check that health_readiness function exists
        assert "def health_readiness" in content
        # Check decorator for GET method
        assert '@app.route(route="readiness"' in content
        assert 'methods=["GET"]' in content or "methods=['GET']" in content

    def test_health_endpoints_validate_config(self) -> None:
        """Verify health endpoints check PipelineConfig."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Extract health_liveness function
        assert "PipelineConfig.from_env()" in content
        # Should appear at least twice (liveness and readiness)
        count = content.count("PipelineConfig.from_env()")
        assert count >= 2, "Config validation should be in both endpoints"

    def test_readiness_endpoint_checks_blob_storage(self) -> None:
        """Verify /readiness endpoint checks Blob Storage."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Find readiness function
        readiness_start = content.find("def health_readiness")
        readiness_end = content.find(
            "\n# ---------------------------------------------------------------------------",
            readiness_start,
        )
        readiness_func = content[readiness_start:readiness_end]

        # Verify Blob Storage check
        assert "get_blob_service_client()" in readiness_func
        assert "blob_storage" in readiness_func

    def test_endpoints_return_json_responses(self) -> None:
        """Verify endpoints return JSON responses."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Check that both endpoints return JSON
        assert 'mimetype="application/json"' in content
        count = content.count('mimetype="application/json"')
        # At least 2 for liveness and readiness
        assert count >= 2, "Both endpoints should return JSON"

    def test_liveness_returns_200_on_config_valid(self) -> None:
        """Verify liveness returns 200 when config is valid."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Find liveness function
        liveness_start = content.find("def health_liveness")
        liveness_end = content.find("def health_readiness")
        liveness_func = content[liveness_start:liveness_end]

        # Verify 200 response for success
        assert "status_code=200" in liveness_func
        assert '"alive"' in liveness_func or "'alive'" in liveness_func

    def test_liveness_returns_500_on_config_invalid(self) -> None:
        """Verify liveness returns 500 when config is invalid."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Find liveness function
        liveness_start = content.find("def health_liveness")
        liveness_end = content.find("def health_readiness")
        liveness_func = content[liveness_start:liveness_end]

        # Verify 500 response for failure
        assert "status_code=500" in liveness_func
        assert '"dead"' in liveness_func or "'dead'" in liveness_func

    def test_readiness_returns_200_when_ready(self) -> None:
        """Verify readiness returns 200 when all dependencies are ready."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Find readiness function
        readiness_start = content.find("def health_readiness")
        readiness_end = content.find(
            "\n# ---------------------------------------------------------------------------",
            readiness_start,
        )
        readiness_func = content[readiness_start:readiness_end]

        # Verify 200 response (check for variable assignment or literal)
        assert "status_code = 200" in readiness_func or "status_code=200" in readiness_func
        assert '"ready"' in readiness_func or "'ready'" in readiness_func

    def test_readiness_returns_503_when_not_ready(self) -> None:
        """Verify readiness returns 503 when dependencies unavailable."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Find readiness function
        readiness_start = content.find("def health_readiness")
        readiness_end = content.find(
            "\n# ---------------------------------------------------------------------------",
            readiness_start,
        )
        readiness_func = content[readiness_start:readiness_end]

        # Verify 503 response (check for variable assignment or literal)
        assert "status_code = 200 if dependencies_ok else 503" in readiness_func
        assert '"not_ready"' in readiness_func or "'not_ready'" in readiness_func

    def test_endpoints_use_async_def(self) -> None:
        """Verify health endpoints are async functions."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Parse the AST to find function definitions
        tree = ast.parse(content)

        health_funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in (
                "health_liveness",
                "health_readiness",
            ):
                health_funcs[node.name] = node

        assert "health_liveness" in health_funcs, "health_liveness should be async"
        assert "health_readiness" in health_funcs, "health_readiness should be async"

    def test_endpoints_handle_exceptions(self) -> None:
        """Verify health endpoints handle exceptions gracefully."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        # Check for exception handling in both endpoints
        assert "except Exception" in content
        count = content.count("except Exception")
        # At least 2-4 exception handlers (liveness has 1, readiness has 2)
        assert count >= 2, "Health endpoints should handle exceptions"

    def test_anonymous_health_does_not_expose_exception_details(self) -> None:
        """Verify anonymous health endpoints do not return raw exception text."""
        function_app_path = Path(__file__).parent.parent.parent / "function_app.py"
        content = function_app_path.read_text()

        assert '"error": f"{e!s}"' not in content
        assert 'dependency_status["config"] = f"error: {e!s}"' not in content
        assert 'dependency_status["blob_storage"] = f"error: {e!s}"' not in content
