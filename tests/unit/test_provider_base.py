"""Tests for ImageryProvider ABC and exception hierarchy.

Covers: ABC enforcement, ProviderError tree, exception attributes,
and the stub adapters' NotImplementedError behaviour.

References:
    PID Section 7.3  (Provider Adapter Layer)
    PID Section 7.4.2 (Fail Loudly — explicit exception types)
"""

from __future__ import annotations

import unittest

from kml_satellite.models.imagery import ProviderConfig
from kml_satellite.providers.base import (
    ImageryProvider,
    ProviderAuthError,
    ProviderDownloadError,
    ProviderError,
    ProviderOrderError,
    ProviderSearchError,
)
from kml_satellite.providers.planetary_computer import PlanetaryComputerAdapter
from kml_satellite.providers.skywatch import SkyWatchAdapter, SkyWatchNotImplementedError

# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


class TestABCEnforcement(unittest.TestCase):
    """ImageryProvider cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self) -> None:
        with self.assertRaises(TypeError):
            ImageryProvider(ProviderConfig(name="test"))  # type: ignore[abstract]

    def test_incomplete_subclass_raises(self) -> None:
        """Subclass missing any abstract method cannot be instantiated."""

        class _Partial(ImageryProvider):
            def search(self, _aoi, _filters=None):  # type: ignore[override]
                return []

            # Missing: order, poll, download

        with self.assertRaises(TypeError):
            _Partial(ProviderConfig(name="partial"))  # type: ignore[abstract]

    def test_complete_subclass_works(self) -> None:
        """Subclass implementing all methods can be instantiated."""

        class _Complete(ImageryProvider):
            def search(self, _aoi, _filters=None):  # type: ignore[override]
                return []

            def order(self, scene_id):  # type: ignore[override]
                raise NotImplementedError

            def poll(self, order_id):  # type: ignore[override]
                raise NotImplementedError

            def download(self, order_id):  # type: ignore[override]
                raise NotImplementedError

        provider = _Complete(ProviderConfig(name="complete"))
        assert provider.name == "complete"
        assert provider.config.name == "complete"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestProviderExceptions(unittest.TestCase):
    """Exception types and attributes."""

    def test_provider_error_attributes(self) -> None:
        e = ProviderError("test_prov", "Something went wrong")
        assert e.provider == "test_prov"
        assert e.message == "Something went wrong"
        assert e.retryable is False
        assert "[test_prov]" in str(e)
        assert "Something went wrong" in str(e)

    def test_provider_error_retryable(self) -> None:
        e = ProviderError("test_prov", "Timeout", retryable=True)
        assert e.retryable is True

    def test_auth_error_is_provider_error(self) -> None:
        e = ProviderAuthError("skywatch", "Invalid API key")
        assert isinstance(e, ProviderError)
        assert e.retryable is False

    def test_search_error_is_provider_error(self) -> None:
        e = ProviderSearchError("pc", "STAC timeout", retryable=True)
        assert isinstance(e, ProviderError)
        assert e.retryable is True

    def test_order_error_is_provider_error(self) -> None:
        e = ProviderOrderError("pc", "Scene unavailable")
        assert isinstance(e, ProviderError)

    def test_download_error_is_provider_error(self) -> None:
        e = ProviderDownloadError("pc", "HTTP 503", retryable=True)
        assert isinstance(e, ProviderError)
        assert e.retryable is True

    def test_exception_hierarchy(self) -> None:
        """All provider exceptions are catchable as ProviderError."""
        exceptions = [
            ProviderAuthError("p", "auth"),
            ProviderSearchError("p", "search"),
            ProviderOrderError("p", "order"),
            ProviderDownloadError("p", "download"),
        ]
        for exc in exceptions:
            assert isinstance(exc, ProviderError)
            assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# Concrete adapter — PlanetaryComputerAdapter is now fully implemented
# ---------------------------------------------------------------------------


class TestPlanetaryComputerIsProvider(unittest.TestCase):
    """PlanetaryComputerAdapter is a concrete ImageryProvider."""

    def setUp(self) -> None:
        self.adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))

    def test_is_imagery_provider(self) -> None:
        assert isinstance(self.adapter, ImageryProvider)

    def test_name(self) -> None:
        assert self.adapter.name == "planetary_computer"

    def test_has_search_method(self) -> None:
        assert callable(self.adapter.search)

    def test_has_order_method(self) -> None:
        assert callable(self.adapter.order)

    def test_has_poll_method(self) -> None:
        assert callable(self.adapter.poll)

    def test_has_download_method(self) -> None:
        assert callable(self.adapter.download)


class TestSkyWatchBlockedUntilImplemented(unittest.TestCase):
    """SkyWatchAdapter blocks instantiation with SkyWatchNotImplementedError (Issue #44)."""

    def test_instantiation_raises(self) -> None:
        """Constructing SkyWatchAdapter raises SkyWatchNotImplementedError."""
        with self.assertRaises(SkyWatchNotImplementedError) as ctx:
            SkyWatchAdapter(ProviderConfig(name="skywatch"))
        assert ctx.exception.retryable is False
        assert "not yet implemented" in str(ctx.exception).lower()

    def test_error_is_provider_error(self) -> None:
        """SkyWatchNotImplementedError is a ProviderError subclass."""
        with self.assertRaises(ProviderError):
            SkyWatchAdapter(ProviderConfig(name="skywatch"))
