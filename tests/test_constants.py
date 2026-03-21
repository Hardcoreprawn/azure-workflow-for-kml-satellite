"""Tests for constants (Appendix A)."""

from __future__ import annotations

from treesight import constants


class TestConstants:
    def test_max_kml_size(self):
        assert constants.MAX_KML_FILE_SIZE_BYTES == 10 * 1024 * 1024

    def test_offload_threshold(self):
        assert constants.PAYLOAD_OFFLOAD_THRESHOLD_BYTES == 48 * 1024

    def test_api_contract_version_format(self):
        """Contract version must match YYYY-MM-DD.N pattern."""
        import re

        assert re.match(r"\d{4}-\d{2}-\d{2}\.\d+", constants.API_CONTRACT_VERSION)

    def test_default_containers(self):
        assert constants.DEFAULT_INPUT_CONTAINER == "kml-input"
        assert constants.DEFAULT_OUTPUT_CONTAINER == "kml-output"
        assert constants.PIPELINE_PAYLOADS_CONTAINER == "pipeline-payloads"

    def test_resolution_constraints(self):
        assert constants.MIN_RESOLUTION_M > 0
        assert constants.DEFAULT_IMAGERY_RESOLUTION_TARGET_M >= constants.MIN_RESOLUTION_M
