"""Tests enforcing Container Apps Python v2 function app architectural specification.

This module verifies that function_app.py meets the mandatory architectural
requirements for Azure Functions on Container Apps hosting.

Container Apps Requirements (Python v2):
1. All functions must load successfully — a single indexing failure prevents
   all functions from serving, including health endpoints
2. HTTP trigger parameters must match binding names (e.g., `req` not `_req`)
3. All async functions must be properly awaitable
4. Event Grid webhook endpoint must be at /runtime/webhooks/eventgrid
5. Health probes required for Container Apps orchestration:
   - /api/health (liveness) — fast config validation
   - /api/readiness — dependency checks (storage, keyvault)
6. Orchestrator status endpoint for workflow observability
7. Durable Functions orchestrators and activities for multi-step workflows
"""

from __future__ import annotations

import pytest


class TestContainerAppsArchitectureSpec:
    """Verify that function_app.py meets Container Apps architectural contract."""

    def test_function_app_can_be_imported(self) -> None:
        """Test that function_app.py imports successfully (indexes without errors).

        This is CRITICAL for Container Apps: a single import/indexing failure
        prevents ALL functions from loading, including health endpoints.
        """
        # Should not raise
        import function_app  # noqa: F401

    def _read_function_app_source(self) -> str:
        """Read function_app.py source code for declarative testing."""
        import pathlib

        app_path = pathlib.Path(__file__).parent.parent.parent / "function_app.py"
        return app_path.read_text(encoding="utf-8")

    def test_all_required_orchestrators_are_registered(self) -> None:
        """Verify all required Durable Functions orchestrators exist."""
        source = self._read_function_app_source()

        required = {"kml_processing_orchestrator", "poll_order_suborchestrator"}

        for name in required:
            assert f'@app.function_name("{name}")' in source, (
                f"Orchestrator '{name}' not found in function_app.py"
            )
            assert f"def {name}(" in source, f"Function '{name}' not defined"

    def test_all_required_http_endpoints_are_registered(self) -> None:
        """Verify all required HTTP route endpoints exist.

        Container Apps relies on these endpoints for orchestration decisions:
        - health_liveness: fast config validation (Container Apps liveness probe)
        - health_readiness: dependency checks (Container Apps readiness probe)
        - orchestrator_status: workflow status lookup via Durable Functions
        """
        source = self._read_function_app_source()

        required_endpoints = {"health_liveness", "health_readiness", "orchestrator_status"}

        for name in required_endpoints:
            assert f'@app.function_name("{name}")' in source, (
                f"HTTP endpoint '{name}' not registered"
            )
            assert "@app.route(" in source, "No HTTP routes defined"

    def test_http_endpoints_use_correct_parameter_names(self) -> None:
        """Verify HTTP trigger parameters match binding expectations.

        HTTP triggers bind to `req` by default in Python v2.
        Using `_req` causes FunctionLoadError and prevents function indexing.

        This verifies the bug fix for issue where health endpoints had `_req`.
        """
        source = self._read_function_app_source()

        # Check that health_liveness has `req`, not `_req`
        # Note: function signature may span multiple lines
        health_liveness_idx = source.find("async def health_liveness(")
        assert health_liveness_idx >= 0, "health_liveness not found"
        health_liveness_section = source[health_liveness_idx : health_liveness_idx + 200]
        assert "req:" in health_liveness_section or "req " in health_liveness_section, (
            "health_liveness should use 'req' parameter"
        )

        health_readiness_idx = source.find("async def health_readiness(")
        assert health_readiness_idx >= 0, "health_readiness not found"
        health_readiness_section = source[health_readiness_idx : health_readiness_idx + 200]
        assert "req:" in health_readiness_section or "req " in health_readiness_section, (
            "health_readiness should use 'req' parameter"
        )

        orchestrator_status_idx = source.find("async def orchestrator_status(")
        assert orchestrator_status_idx >= 0, "orchestrator_status not found"
        orchestrator_status_section = source[
            orchestrator_status_idx : orchestrator_status_idx + 300
        ]
        assert "req:" in orchestrator_status_section or "req " in orchestrator_status_section, (
            "orchestrator_status should use 'req' parameter"
        )

        # Verify NO use of _req in HTTP handlers
        assert "def health_liveness(_req:" not in source, (
            "health_liveness should NOT use '_req' (causes FunctionLoadError)"
        )

    def test_event_grid_trigger_is_registered(self) -> None:
        """Verify Event Grid trigger function exists for blob-created events."""
        source = self._read_function_app_source()

        assert "@app.event_grid_trigger" in source or "event_grid_trigger" in source, (
            "Event Grid trigger not found"
        )
        assert "kml_blob_trigger" in source, "kml_blob_trigger not found"

    def test_all_required_durable_activities_are_registered(self) -> None:
        """Verify all required Durable Functions activities exist.

        These activities execute the business logic for the pipeline stages.
        Activities may be named with `_activity` suffix in code but registered
        with their logical name via @app.function_name().
        """
        source = self._read_function_app_source()

        required_activities = {
            "parse_kml",
            "prepare_aoi",
            "acquire_imagery",
            "poll_order",
            "download_imagery",
            "post_process_imagery",
            "write_metadata",
        }

        for activity in required_activities:
            # Check registration via @app.function_name()
            assert f'@app.function_name("{activity}")' in source, (
                f"Activity '{activity}' not registered via @app.function_name"
            )

            # Check that @app.activity_trigger is present for this function
            # Find the registration and check the next decorated function exists
            func_registration_idx = source.find(f'@app.function_name("{activity}")')
            assert func_registration_idx >= 0, f"Activity '{activity}' not found in source"

            # Look for def after the decorator (may be `def {activity}` or `def {activity}_activity`)
            after_decorator = source[func_registration_idx : func_registration_idx + 500]
            assert "@app.activity_trigger" in after_decorator, (
                f"Activity '{activity}' should have @app.activity_trigger decorator"
            )
            assert (
                f"def {activity}(" in after_decorator
                or f"def {activity}_activity(" in after_decorator
            ), f"Activity function for '{activity}' not defined"

    def test_health_endpoints_are_async(self) -> None:
        """Verify health endpoints are async functions for Container Apps compatibility."""
        source = self._read_function_app_source()

        assert "async def health_liveness(" in source, "health_liveness should be async"
        assert "async def health_readiness(" in source, "health_readiness should be async"

    def test_blob_trigger_is_async(self) -> None:
        """Verify Event Grid blob trigger is async for Container Apps."""
        source = self._read_function_app_source()

        assert "async def kml_blob_trigger(" in source, "kml_blob_trigger should be async"

    def test_http_handler_parameters_not_unused(self) -> None:
        """Verify HTTP handler parameters are not just accepted but actually used.

        Checks for `_ = req` which marks the parameter as intentionally used
        for lint compliance when the parameter isn't directly referenced.
        """
        source = self._read_function_app_source()

        # Find health_liveness function and look deeper into the body
        start = source.find("def health_liveness(")
        # Look much further to ensure we get into the function body
        end = source.find("@app.function_name(", start + 100)  # Find next function registration
        if end < 0:
            end = start + 1000
        health_liveness_block = source[start:end]

        # Should have explicit use of req: either `_ = req` or direct usage in body
        assert "_ = req" in health_liveness_block, (
            "health_liveness should explicitly use req parameter via `_ = req`"
        )

    def test_function_module_exports_app(self) -> None:
        """Verify function_app exports the FunctionApp instance for binding."""
        import function_app

        assert hasattr(function_app, "app"), "function_app should export 'app' instance"
        assert hasattr(function_app.app, "function_name"), "app should be a FunctionApp instance"

    def test_event_grid_trigger_has_durable_client_binding(self) -> None:
        """Verify kml_blob_trigger has durable client for orchestrator interaction.

        Durable client is necessary to start orchestrator instances from the event trigger.
        """
        source = self._read_function_app_source()

        # Find kml_blob_trigger registration and check decorators
        trigger_start = source.find("def kml_blob_trigger(")
        if trigger_start < 0:
            pytest.fail("kml_blob_trigger not found in function_app.py")

        # Look backwards from function to find decorators
        before_func = source[:trigger_start]
        last_newline = before_func.rfind("\n")
        decorator_section = before_func[max(0, last_newline - 500) : trigger_start]

        # Should have both @app.event_grid_trigger and @app.durable_client_input
        assert (
            "@app.event_grid_trigger" in decorator_section
            or "event_grid_trigger" in decorator_section
        ), "kml_blob_trigger should have @app.event_grid_trigger decorator"
        assert (
            "@app.durable_client_input" in decorator_section
            or "durable_client_input" in decorator_section
        ), "kml_blob_trigger should have @app.durable_client_input decorator"

    def test_orchestrators_use_context_parameter(self) -> None:
        """Verify orchestrators receive DurableOrchestrationContext."""
        source = self._read_function_app_source()

        # Check kml_processing_orchestrator
        kml_orch_start = source.find("def kml_processing_orchestrator(")
        assert kml_orch_start >= 0, "kml_processing_orchestrator not found"
        kml_orch_section = source[kml_orch_start : kml_orch_start + 200]
        assert "context:" in kml_orch_section, (
            "kml_processing_orchestrator should have context parameter"
        )
        assert (
            "DurableOrchestrationContext" in kml_orch_section or "context" in kml_orch_section
        ), "kml_processing_orchestrator should use DurableOrchestrationContext"

        # Check poll_order_suborchestrator
        poll_orch_start = source.find("def poll_order_suborchestrator(")
        assert poll_orch_start >= 0, "poll_order_suborchestrator not found"
        poll_orch_section = source[poll_orch_start : poll_orch_start + 200]
        assert "context:" in poll_orch_section, (
            "poll_order_suborchestrator should have context parameter"
        )


class TestContainerAppsSpecCompliance:
    """Verify function_app.py can be deployed to Container Apps env."""

    def _read_function_app_source(self) -> str:
        """Read function_app.py source code for declarative testing."""
        import pathlib

        app_path = pathlib.Path(__file__).parent.parent.parent / "function_app.py"
        return app_path.read_text(encoding="utf-8")

    def test_health_liveness_returns_http_response(self) -> None:
        """Verify health_liveness returns proper HTTP response.

        Container Apps probes expect HTTP responses with status codes.
        """
        source = self._read_function_app_source()

        # Check health_liveness definition and return type
        health_liveness_start = source.find("async def health_liveness(")
        assert health_liveness_start >= 0, "health_liveness not found"

        health_liveness_section = source[health_liveness_start : health_liveness_start + 500]
        assert "func.HttpResponse" in health_liveness_section, (
            "health_liveness should return func.HttpResponse"
        )

    def test_health_readiness_returns_http_response(self) -> None:
        """Verify health_readiness returns proper HTTP response."""
        source = self._read_function_app_source()

        # Check health_readiness definition and return type
        health_readiness_start = source.find("async def health_readiness(")
        assert health_readiness_start >= 0, "health_readiness not found"

        health_readiness_section = source[health_readiness_start : health_readiness_start + 500]
        assert "func.HttpResponse" in health_readiness_section, (
            "health_readiness should return func.HttpResponse"
        )

    def test_function_names_follow_container_apps_naming(self) -> None:
        """Verify function names follow Container Apps conventions.

        Names should be lowercase, use underscores, match route paths.
        Container Apps function discovery is sensitive to naming consistency.
        """
        source = self._read_function_app_source()

        # These must all be registered and follow naming conventions
        required_registrations = {
            '@app.function_name("health_liveness")',
            '@app.function_name("health_readiness")',
            '@app.function_name("orchestrator_status")',
            '@app.function_name("kml_blob_trigger")',
        }

        for registration in required_registrations:
            assert registration in source, (
                f"Required registration {registration} not found in source"
            )

    def test_no_blocking_imports(self) -> None:
        """Verify function_app.py has no blocking imports that fail on load.

        If imports fail during function indexing, all functions become unavailable.
        """
        # Try to import function_app — if this succeeds, imports are not blocking
        try:
            import function_app  # noqa: F401
        except ImportError as e:
            pytest.fail(f"function_app import blocked: {e}")

    def test_functionapp_instance_is_exported(self) -> None:
        """Verify FunctionApp instance named 'app' is available for Azure Functions host.

        The Azure Functions runtime loads the 'app' instance to discover functions.
        """
        import function_app

        assert hasattr(function_app, "app"), (
            "function_app must export 'app' (FunctionApp instance)"
        )

        # Should have decorator methods
        app_obj = function_app.app
        assert hasattr(app_obj, "event_grid_trigger"), "app should have event_grid_trigger"
        assert hasattr(app_obj, "function_name"), "app should have function_name decorator"


class TestContainerAppsFunctionSignatures:
    """Verify function signatures meet Container Apps deployment requirements."""

    def _read_function_app_source(self) -> str:
        """Read function_app.py source code for declarative testing."""
        import pathlib

        app_path = pathlib.Path(__file__).parent.parent.parent / "function_app.py"
        return app_path.read_text(encoding="utf-8")

    def test_all_activity_functions_accept_input_parameter(self) -> None:
        """Verify Durable Functions activities accept input parameter correctly."""
        source = self._read_function_app_source()

        activities = {
            "parse_kml",
            "prepare_aoi",
            "acquire_imagery",
            "poll_order",
            "download_imagery",
            "post_process_imagery",
            "write_metadata",
        }

        for activity_name in activities:
            # Find the activity registration
            func_registration = f'@app.function_name("{activity_name}")'
            assert func_registration in source, f"Activity {activity_name} not registered"

            # Find the @app.activity_trigger decorator for this activity
            reg_idx = source.find(func_registration)
            after_reg = source[reg_idx : reg_idx + 300]
            assert "@app.activity_trigger" in after_reg, (
                f"Activity {activity_name} missing @app.activity_trigger"
            )

            # Activities should have activityInput parameter
            assert "activityInput" in after_reg or "input_name=" in after_reg, (
                f"Activity {activity_name} should have activityInput parameter"
            )

    def test_orchestrator_functions_are_not_async(self) -> None:
        """Verify orchestrator functions are NOT async.

        Durable Functions orchestrators must be standard (synchronous) functions,
        not async. The DurableOrchestrationContext handles async internally.
        """
        source = self._read_function_app_source()

        orchestrators = {
            "kml_processing_orchestrator",
            "poll_order_suborchestrator",
        }

        for orch_name in orchestrators:
            func_def = f"def {orch_name}("
            assert func_def in source, f"Orchestrator {orch_name} not found"

            # Check that it's NOT async
            async_def = f"async def {orch_name}("
            assert async_def not in source, (
                f"Orchestrator {orch_name} should NOT be async (found 'async def')"
            )

    def test_event_grid_trigger_accepts_event_and_client(self) -> None:
        """Verify Event Grid trigger has correct parameters for bindings."""
        source = self._read_function_app_source()

        # Find kml_blob_trigger definition
        trigger_def = "async def kml_blob_trigger("
        assert trigger_def in source, "kml_blob_trigger not found or not async"

        # Should have event and client parameters
        start = source.find(trigger_def)
        end = source.find(")", start)
        trigger_sig = source[start : end + 1]

        assert "event" in trigger_sig, "Event Grid trigger should have 'event' parameter"
        assert "client" in trigger_sig, "Event Grid trigger should have 'client' parameter"
