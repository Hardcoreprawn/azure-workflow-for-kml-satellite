"""Tests for Dockerfile container image build configuration.

Validates that the Dockerfile correctly builds a containerized Azure Functions
app with Python v2 programming model requirements for Azure Container Apps:

1. Installs Azure Functions Core Tools from the base image's existing Microsoft
   APT repository (avoiding duplicate repo conflicts).

2. Runs `func build --python` in the builder stage to generate the
   `.azurefunctions/` metadata directory required by Python v2.

3. Copies the generated metadata from builder to runtime stage so functions
   are discoverable by the Functions host.

4. Includes GDAL and geospatial libraries for KML/raster processing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DOCKERFILE_PATH = Path(__file__).resolve().parent.parent.parent / "Dockerfile"


@pytest.fixture(scope="module")
def dockerfile_content() -> str:
    """Read Dockerfile content as string."""
    assert DOCKERFILE_PATH.exists(), f"Dockerfile not found at {DOCKERFILE_PATH}"
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test: Multi-stage build structure
# ---------------------------------------------------------------------------


class TestMultiStageBuild:
    """Verify Dockerfile uses multi-stage build for smaller runtime image."""

    def test_has_builder_stage(self, dockerfile_content: str) -> None:
        """Dockerfile must have a builder stage."""
        assert "FROM " in dockerfile_content
        assert " AS builder" in dockerfile_content, (
            "Dockerfile must have a builder stage for compilation/metadata generation"
        )

    def test_has_runtime_stage(self, dockerfile_content: str) -> None:
        """Dockerfile must have a separate runtime stage."""
        lines = dockerfile_content.split("\n")
        from_count = sum(1 for line in lines if line.strip().startswith("FROM "))
        assert from_count >= 2, "Dockerfile must have at least 2 FROM statements (multi-stage)"

    def test_uses_azure_functions_base_image(self, dockerfile_content: str) -> None:
        """Dockerfile must use official Azure Functions Python base image."""
        assert "mcr.microsoft.com/azure-functions/python:4-python3.12" in dockerfile_content, (
            "Dockerfile must use mcr.microsoft.com/azure-functions/python:4-python3.12 base image"
        )


# ---------------------------------------------------------------------------
# Test: Azure Functions Core Tools installation
# ---------------------------------------------------------------------------


class TestCoreFunctionsTools:
    """Verify Azure Functions Core Tools installation for func build."""

    def test_installs_core_tools(self, dockerfile_content: str) -> None:
        """Builder stage must install azure-functions-core-tools-4."""
        assert "azure-functions-core-tools-4" in dockerfile_content, (
            "Dockerfile must install azure-functions-core-tools-4 for metadata generation"
        )

    def test_uses_existing_microsoft_repo(self, dockerfile_content: str) -> None:
        """Core Tools installation must NOT add duplicate Microsoft APT repository.

        The base image already has packages.microsoft.com configured. Adding
        a duplicate repository entry with a different signing key causes:

        E: Conflicting values set for option Signed-By regarding source
        https://packages.microsoft.com/debian/12/prod/ bookworm:
        /usr/share/keyrings/microsoft-archive-keyring.gpg !=
        /usr/share/keyrings/microsoft-prod.gpg
        """
        # Find the Core Tools installation line
        lines = dockerfile_content.split("\n")
        core_tools_line_idx = None
        for idx, line in enumerate(lines):
            if "azure-functions-core-tools-4" in line:
                core_tools_line_idx = idx
                break

        assert core_tools_line_idx is not None, "Core Tools installation not found"

        # Check surrounding lines (within same RUN block) for repository setup
        run_block = []
        in_run_block = False
        for idx in range(
            max(0, core_tools_line_idx - 20), min(len(lines), core_tools_line_idx + 5)
        ):
            line = lines[idx]
            if "RUN " in line or (in_run_block and line.strip().startswith("&&")):
                in_run_block = True
                run_block.append(line)
            elif in_run_block and not line.strip().endswith("\\"):
                run_block.append(line)
                break

        run_block_text = " ".join(run_block)

        # Must NOT add repository manually
        assert "microsoft-archive-keyring.gpg" not in run_block_text, (
            "Dockerfile must NOT add Microsoft repo manually — base image already has it"
        )
        assert "microsoft-prod.list" not in run_block_text, (
            "Dockerfile must NOT create /etc/apt/sources.list.d/microsoft-prod.list"
        )
        assert "packages.microsoft.com/keys/microsoft.asc" not in run_block_text, (
            "Dockerfile must NOT download Microsoft signing key — use existing repo"
        )

    def test_core_tools_in_builder_stage(self, dockerfile_content: str) -> None:
        """Core Tools must be installed in builder stage (not runtime)."""
        lines = dockerfile_content.split("\n")

        # Find builder stage and runtime stage boundaries
        builder_start = None
        runtime_start = None
        for idx, line in enumerate(lines):
            if " AS builder" in line:
                builder_start = idx
            elif (
                builder_start is not None
                and runtime_start is None
                and line.strip().startswith("FROM ")
                and " AS builder" not in line
            ):
                runtime_start = idx

        assert builder_start is not None, "Builder stage not found"

        # Find Core Tools installation
        core_tools_line = None
        for idx, line in enumerate(lines):
            if "azure-functions-core-tools-4" in line:
                core_tools_line = idx
                break

        assert core_tools_line is not None, "Core Tools installation not found"

        if runtime_start is not None:
            assert builder_start < core_tools_line < runtime_start, (
                "azure-functions-core-tools-4 must be installed in builder stage (before runtime FROM)"
            )
        else:
            assert core_tools_line > builder_start, (
                "azure-functions-core-tools-4 must be installed after builder stage starts"
            )


# ---------------------------------------------------------------------------
# Test: Python v2 function metadata generation
# ---------------------------------------------------------------------------


class TestFunctionMetadataGeneration:
    """Verify func build generates .azurefunctions/ metadata for Python v2."""

    def test_runs_func_build(self, dockerfile_content: str) -> None:
        """Builder stage must run 'func build --python'."""
        lines = dockerfile_content.split("\n")
        has_func_build = any(
            line.strip().startswith("RUN") and "func build" in line and "--python" in line
            for line in lines
        )
        assert has_func_build, (
            "Dockerfile must run 'func build --python' to generate .azurefunctions/ metadata"
        )

    def test_copies_application_code_to_builder(self, dockerfile_content: str) -> None:
        """Builder stage must copy application code before running func build."""
        lines = dockerfile_content.split("\n")

        # Find builder stage start
        builder_start = None
        for idx, line in enumerate(lines):
            if " AS builder" in line:
                builder_start = idx
                break

        assert builder_start is not None

        # Find func build command (RUN statement, not comment)
        func_build_line = None
        for idx, line in enumerate(lines[builder_start:], start=builder_start):
            if "func build" in line and line.strip().startswith("RUN"):
                func_build_line = idx
                break

        assert func_build_line is not None, "RUN func build command not found"

        # Extract the section from builder to func build (inclusive)
        builder_section = "\n".join(lines[builder_start : func_build_line + 1])

        # Before func build, must copy function_app.py and kml_satellite/
        assert "function_app.py" in builder_section and "COPY" in builder_section, (
            f"Must copy function_app.py to builder before func build. Section:\n{builder_section[:500]}"
        )
        assert "kml_satellite" in builder_section, (
            "Must copy kml_satellite/ directory to builder before func build"
        )
        assert "host.json" in builder_section, "Must copy host.json to builder before func build"

    def test_copies_metadata_to_runtime(self, dockerfile_content: str) -> None:
        """Runtime stage must copy .azurefunctions/ from builder."""
        assert ".azurefunctions" in dockerfile_content, (
            "Dockerfile must reference .azurefunctions/ directory"
        )

        # Check COPY --from=builder includes .azurefunctions
        lines = dockerfile_content.split("\n")
        runtime_stage = []
        in_runtime = False

        for line in lines:
            if in_runtime:
                runtime_stage.append(line)
            elif line.strip().startswith("FROM ") and " AS builder" not in line:
                in_runtime = True

        runtime_text = "\n".join(runtime_stage)
        assert "COPY --from=builder" in runtime_text, "Runtime must copy from builder"
        assert ".azurefunctions" in runtime_text, (
            "Runtime stage must copy .azurefunctions/ from builder"
        )

    def test_verifies_metadata_generation(self, dockerfile_content: str) -> None:
        """func build command should verify .azurefunctions/ was created."""
        # Look for ls or test after func build
        lines = dockerfile_content.split("\n")
        func_build_line = None

        for idx, line in enumerate(lines):
            if "func build" in line and line.strip().startswith("RUN"):
                func_build_line = idx
                break

        assert func_build_line is not None, "RUN func build command not found"

        # Check same RUN command (continuation lines with &&) for verification
        verification_context = []
        for idx in range(func_build_line, min(len(lines), func_build_line + 5)):
            verification_context.append(lines[idx])
            # Stop if we hit a line that doesn't continue
            if not lines[idx].rstrip().endswith("\\") and not (
                idx > func_build_line and "&&" in lines[idx]
            ):
                break

        verification_text = "\n".join(verification_context)
        has_verification = (
            "ls" in verification_text or "test -d" in verification_text
        ) and ".azurefunctions" in verification_text

        assert has_verification, (
            "func build should include verification step (e.g., ls -la .azurefunctions/) "
            "to confirm metadata was generated"
        )


# ---------------------------------------------------------------------------
# Test: GDAL and geospatial dependencies
# ---------------------------------------------------------------------------


class TestGeospatialDependencies:
    """Verify GDAL/GEOS/PROJ libraries for KML/raster processing."""

    def test_installs_gdal_dev_in_builder(self, dockerfile_content: str) -> None:
        """Builder stage must install libgdal-dev for building rasterio/Fiona."""
        assert "libgdal-dev" in dockerfile_content, (
            "Builder stage must install libgdal-dev for building geospatial wheels"
        )

    def test_installs_gdal_bin_in_runtime(self, dockerfile_content: str) -> None:
        """Runtime stage must install gdal-bin for runtime GDAL libraries."""
        lines = dockerfile_content.split("\n")
        runtime_section = []
        in_runtime = False

        for line in lines:
            if in_runtime:
                runtime_section.append(line)
            elif line.strip().startswith("FROM ") and " AS builder" not in line:
                in_runtime = True

        runtime_text = "\n".join(runtime_section)
        assert "gdal-bin" in runtime_text, (
            "Runtime stage must install gdal-bin for runtime libraries"
        )

    def test_sets_gdal_config_env(self, dockerfile_content: str) -> None:
        """Builder must set GDAL_CONFIG for pip to find GDAL during wheel builds."""
        assert "GDAL_CONFIG" in dockerfile_content, (
            "Dockerfile must set GDAL_CONFIG environment variable for pip"
        )
        assert "gdal-config" in dockerfile_content, "GDAL_CONFIG must point to gdal-config binary"
