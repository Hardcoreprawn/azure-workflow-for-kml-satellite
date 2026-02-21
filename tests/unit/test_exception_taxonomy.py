"""Tests for the unified exception taxonomy (Issue #58).

Validates:
- PipelineError hierarchy and structured attributes
- Category classification (validation, transient, permanent, contract)
- ``to_error_dict()`` produces stable payload keys
- Retry semantics are consistent with taxonomy class
- All activity/provider exceptions are PipelineError subclasses
"""

from __future__ import annotations

from typing import ClassVar

from kml_satellite.activities.acquire_imagery import ImageryAcquisitionError
from kml_satellite.activities.download_imagery import DownloadError
from kml_satellite.activities.parse_kml import (
    InvalidCoordinateError,
    KmlParseError,
    KmlValidationError,
)
from kml_satellite.activities.poll_order import PollError
from kml_satellite.activities.post_process_imagery import PostProcessError
from kml_satellite.activities.prepare_aoi import AOIError
from kml_satellite.activities.write_metadata import MetadataWriteError
from kml_satellite.core.config import ConfigValidationError
from kml_satellite.core.exceptions import (
    ContractError,
    PermanentError,
    PipelineError,
    TransientError,
    ValidationError,
)
from kml_satellite.models.imagery import ModelValidationError
from kml_satellite.providers.base import (
    ProviderAuthError,
    ProviderDownloadError,
    ProviderError,
    ProviderOrderError,
    ProviderSearchError,
)


class TestPipelineErrorBase:
    """PipelineError base class behavior."""

    def test_default_attributes(self) -> None:
        err = PipelineError("boom")
        assert err.message == "boom"
        assert err.stage == ""
        assert err.code == ""
        assert err.retryable is False
        assert err.correlation_id == ""

    def test_custom_attributes(self) -> None:
        err = PipelineError(
            "fail",
            stage="download_imagery",
            code="DOWNLOAD_FAILED",
            retryable=True,
            correlation_id="abc-123",
        )
        assert err.stage == "download_imagery"
        assert err.code == "DOWNLOAD_FAILED"
        assert err.retryable is True
        assert err.correlation_id == "abc-123"

    def test_str_is_message(self) -> None:
        err = PipelineError("human-readable error")
        assert str(err) == "human-readable error"

    def test_to_error_dict_keys(self) -> None:
        err = PipelineError("x", stage="s", code="C", retryable=True, correlation_id="id")
        d = err.to_error_dict()
        assert set(d.keys()) == {
            "category",
            "code",
            "stage",
            "message",
            "retryable",
            "correlation_id",
        }
        assert d["message"] == "x"
        assert d["stage"] == "s"
        assert d["code"] == "C"
        assert d["retryable"] is True
        assert d["correlation_id"] == "id"


class TestCategoryBases:
    """Category base classes set correct defaults."""

    def test_validation_error_not_retryable(self) -> None:
        err = ValidationError("bad input")
        assert err.retryable is False
        assert err.category == "validation"

    def test_transient_error_retryable(self) -> None:
        err = TransientError("timeout")
        assert err.retryable is True
        assert err.category == "transient"

    def test_permanent_error_not_retryable(self) -> None:
        err = PermanentError("gone")
        assert err.retryable is False
        assert err.category == "permanent"

    def test_contract_error_not_retryable(self) -> None:
        err = ContractError("schema drift")
        assert err.retryable is False
        assert err.category == "contract"

    def test_dynamic_category_from_retryable(self) -> None:
        retryable = PipelineError("x", retryable=True)
        assert retryable.category == "transient"
        not_retryable = PipelineError("x", retryable=False)
        assert not_retryable.category == "permanent"


class TestAllExceptionsArePipelineError:
    """Every custom exception inherits from PipelineError."""

    EXCEPTION_CLASSES: ClassVar[list[type[PipelineError]]] = [
        ImageryAcquisitionError,
        PollError,
        DownloadError,
        PostProcessError,
        MetadataWriteError,
        AOIError,
        KmlParseError,
        KmlValidationError,
        InvalidCoordinateError,
        ConfigValidationError,
        ModelValidationError,
        ProviderError,
        ProviderAuthError,
        ProviderSearchError,
        ProviderOrderError,
        ProviderDownloadError,
    ]

    def test_all_subclass_pipeline_error(self) -> None:
        for cls in self.EXCEPTION_CLASSES:
            assert issubclass(cls, PipelineError), f"{cls.__name__} is not a PipelineError"


class TestActivityExceptionStageAndCode:
    """Every activity exception has a default stage and code."""

    def test_kml_parse_error(self) -> None:
        err = KmlParseError("bad xml")
        assert err.stage == "parse_kml"
        assert err.code == "KML_PARSE_FAILED"

    def test_kml_validation_error_inherits_stage(self) -> None:
        err = KmlValidationError("bad data")
        assert err.stage == "parse_kml"
        assert err.code == "KML_VALIDATION_FAILED"

    def test_invalid_coordinate_error(self) -> None:
        err = InvalidCoordinateError("lon out of range")
        assert err.stage == "parse_kml"
        assert err.code == "KML_COORDINATE_INVALID"

    def test_aoi_error(self) -> None:
        err = AOIError("degenerate polygon")
        assert err.stage == "prepare_aoi"
        assert err.code == "AOI_PROCESSING_FAILED"

    def test_imagery_acquisition_error(self) -> None:
        err = ImageryAcquisitionError("no scenes", retryable=False)
        assert err.stage == "acquire_imagery"
        assert err.code == "IMAGERY_ACQUISITION_FAILED"

    def test_poll_error(self) -> None:
        err = PollError("provider 500", retryable=True)
        assert err.stage == "poll_order"
        assert err.code == "POLL_FAILED"
        assert err.retryable is True

    def test_download_error(self) -> None:
        err = DownloadError("timeout", retryable=True)
        assert err.stage == "download_imagery"
        assert err.code == "DOWNLOAD_FAILED"

    def test_post_process_error(self) -> None:
        err = PostProcessError("GDAL crash")
        assert err.stage == "post_process_imagery"
        assert err.code == "POST_PROCESS_FAILED"

    def test_metadata_write_error(self) -> None:
        err = MetadataWriteError("blob 403")
        assert err.stage == "write_metadata"
        assert err.code == "METADATA_WRITE_FAILED"

    def test_config_validation_error(self) -> None:
        err = ConfigValidationError("CLOUD_COVER", 200, "must be 0-100")
        assert err.stage == "config"
        assert err.code == "CONFIG_VALIDATION_FAILED"
        assert err.key == "CLOUD_COVER"
        assert err.value == 200

    def test_model_validation_error(self) -> None:
        err = ModelValidationError("ImageryFilters", "cloud_cover", 150, "too high")
        assert err.stage == "model_validation"
        assert err.code == "MODEL_VALIDATION_FAILED"
        assert isinstance(err, ValueError)
        assert isinstance(err, PipelineError)


class TestProviderExceptionTaxonomy:
    """Provider exceptions carry stage, code, and provider info."""

    def test_provider_error(self) -> None:
        err = ProviderError("pc", "STAC down", retryable=True)
        assert err.provider == "pc"
        assert err.message == "STAC down"
        assert err.retryable is True
        assert err.stage == "provider"
        assert err.code == "PROVIDER_ERROR"

    def test_provider_auth_error(self) -> None:
        err = ProviderAuthError("skywatch", "bad key")
        assert err.retryable is False
        assert err.code == "PROVIDER_AUTH_FAILED"
        assert isinstance(err, ProviderError)

    def test_provider_search_error(self) -> None:
        err = ProviderSearchError("pc", "timeout", retryable=True)
        assert err.code == "PROVIDER_SEARCH_FAILED"
        assert err.retryable is True

    def test_provider_order_error(self) -> None:
        err = ProviderOrderError("pc", "rejected")
        assert err.code == "PROVIDER_ORDER_FAILED"

    def test_provider_download_error(self) -> None:
        err = ProviderDownloadError("pc", "404")
        assert err.code == "PROVIDER_DOWNLOAD_FAILED"


class TestRetrySemantics:
    """Retry decisions aligned to taxonomy classes."""

    def test_retryable_errors_report_transient_category(self) -> None:
        errors = [
            ImageryAcquisitionError("x", retryable=True),
            PollError("x", retryable=True),
            DownloadError("x", retryable=True),
            PostProcessError("x", retryable=True),
            ProviderError("p", "x", retryable=True),
        ]
        for err in errors:
            assert err.category == "transient", f"{type(err).__name__} should be transient"
            assert err.retryable is True

    def test_non_retryable_errors_report_permanent_category(self) -> None:
        errors = [
            ImageryAcquisitionError("x", retryable=False),
            PollError("x", retryable=False),
            DownloadError("x", retryable=False),
            PostProcessError("x"),
            AOIError("x"),
            MetadataWriteError("x"),
            KmlParseError("x"),
        ]
        for err in errors:
            assert err.category == "permanent", f"{type(err).__name__} should be permanent"
            assert err.retryable is False


class TestErrorDictStability:
    """to_error_dict() always includes required keys regardless of exception type."""

    REQUIRED_KEYS: ClassVar[set[str]] = {
        "category",
        "code",
        "stage",
        "message",
        "retryable",
        "correlation_id",
    }

    def test_activity_error_dict(self) -> None:
        err = DownloadError("timeout", retryable=True)
        d = err.to_error_dict()
        assert set(d.keys()) >= self.REQUIRED_KEYS
        assert d["stage"] == "download_imagery"
        assert d["code"] == "DOWNLOAD_FAILED"

    def test_provider_error_dict(self) -> None:
        err = ProviderSearchError("pc", "STAC down", retryable=True)
        d = err.to_error_dict()
        assert set(d.keys()) >= self.REQUIRED_KEYS
        assert d["code"] == "PROVIDER_SEARCH_FAILED"

    def test_correlation_id_propagated(self) -> None:
        err = PipelineError("x", correlation_id="corr-xyz")
        assert err.to_error_dict()["correlation_id"] == "corr-xyz"
