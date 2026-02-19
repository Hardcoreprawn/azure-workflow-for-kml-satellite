"""Tests for the imagery provider factory.

Covers: get_provider, list_providers, register_provider, error handling,
lazy import behaviour, config-driven switching, and instance caching (Issue #63).

References:
    PID FR-3.1  (provider-agnostic abstraction)
    PID Section 7.6  (config-driven provider switching)
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from kml_satellite.models.imagery import ProviderConfig
from kml_satellite.providers.base import ImageryProvider, ProviderError
from kml_satellite.providers.factory import (
    _ADAPTER_REGISTRY,
    PLANETARY_COMPUTER,
    SKYWATCH,
    _ensure_registry,
    clear_provider_cache,
    get_provider,
    list_providers,
    register_provider,
)
from kml_satellite.providers.skywatch import SkyWatchNotImplementedError


class TestListProviders(unittest.TestCase):
    """list_providers returns known adapters."""

    def test_includes_builtin_providers(self) -> None:
        providers = list_providers()
        assert PLANETARY_COMPUTER in providers
        assert SKYWATCH in providers

    def test_returns_sorted(self) -> None:
        providers = list_providers()
        assert providers == sorted(providers)


class TestGetProvider(unittest.TestCase):
    """get_provider creates the correct adapter instance."""

    def setUp(self) -> None:
        clear_provider_cache()

    def tearDown(self) -> None:
        clear_provider_cache()

    def test_planetary_computer(self) -> None:
        provider = get_provider(PLANETARY_COMPUTER)
        assert isinstance(provider, ImageryProvider)
        assert provider.name == PLANETARY_COMPUTER

    def test_skywatch_blocked_until_implemented(self) -> None:
        """SkyWatch adapter blocks instantiation with an actionable error (Issue #44)."""
        with self.assertRaises(SkyWatchNotImplementedError) as ctx:
            get_provider(SKYWATCH)
        assert "not yet implemented" in str(ctx.exception).lower()
        assert ctx.exception.retryable is False

    def test_unknown_provider_raises(self) -> None:
        with self.assertRaises(ProviderError) as ctx:
            get_provider("nonexistent_provider")
        assert "nonexistent_provider" in str(ctx.exception)
        assert "Available:" in str(ctx.exception)

    def test_custom_config_passed(self) -> None:
        cfg = ProviderConfig(
            name=PLANETARY_COMPUTER,
            api_base_url="https://custom.stac.api/",
        )
        provider = get_provider(PLANETARY_COMPUTER, config=cfg)
        assert provider.config.api_base_url == "https://custom.stac.api/"

    def test_default_config_when_none(self) -> None:
        provider = get_provider(PLANETARY_COMPUTER)
        assert provider.config.name == PLANETARY_COMPUTER

    def test_config_name_mismatch_raises(self) -> None:
        """ProviderConfig.name must match the requested provider name."""
        cfg = ProviderConfig(name=SKYWATCH)
        with self.assertRaises(ProviderError) as ctx:
            get_provider(PLANETARY_COMPUTER, config=cfg)
        assert "does not match" in str(ctx.exception)


class TestRegisterProvider(unittest.TestCase):
    """register_provider adds custom adapters."""

    def setUp(self) -> None:
        """Ensure registry is initialised and remember state."""
        _ensure_registry()
        clear_provider_cache()
        # Remove our test adapter if it lingers from a previous run
        _ADAPTER_REGISTRY.pop("test_custom", None)

    def tearDown(self) -> None:
        """Clean up custom adapter."""
        _ADAPTER_REGISTRY.pop("test_custom", None)
        clear_provider_cache()

    def test_register_and_get(self) -> None:
        """Registered adapter can be retrieved via get_provider."""

        class _TestAdapter(ImageryProvider):
            def search(self, _aoi, _filters=None):  # type: ignore[override]
                return []

            def order(self, scene_id):  # type: ignore[override]
                raise NotImplementedError

            def poll(self, order_id):  # type: ignore[override]
                raise NotImplementedError

            def download(self, order_id):  # type: ignore[override]
                raise NotImplementedError

        register_provider("test_custom", lambda: _TestAdapter)
        assert "test_custom" in list_providers()

        provider = get_provider("test_custom")
        assert isinstance(provider, _TestAdapter)

    def test_register_empty_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            register_provider("", lambda: ImageryProvider)  # type: ignore[arg-type]


class TestProviderSwitching(unittest.TestCase):
    """Provider switching via config (PID 7.6)."""

    def setUp(self) -> None:
        clear_provider_cache()

    def tearDown(self) -> None:
        clear_provider_cache()

    def test_switch_by_name(self) -> None:
        """Different names are registered for different adapter types."""
        providers = list_providers()
        assert PLANETARY_COMPUTER in providers
        assert SKYWATCH in providers
        # Planetary Computer instantiates; SkyWatch blocks (Issue #44)
        pc = get_provider(PLANETARY_COMPUTER)
        assert pc.name == PLANETARY_COMPUTER

    @patch.dict("os.environ", {"IMAGERY_PROVIDER": SKYWATCH})
    def test_env_driven_selection_skywatch_blocked(self) -> None:
        """PipelineConfig.imagery_provider=skywatch is rejected until implemented."""
        from kml_satellite.core.config import PipelineConfig

        cfg = PipelineConfig.from_env()
        assert cfg.imagery_provider == SKYWATCH
        with self.assertRaises(SkyWatchNotImplementedError):
            get_provider(cfg.imagery_provider)


class TestProviderInstanceCache(unittest.TestCase):
    """Instance caching for session pooling (Issue #63)."""

    def setUp(self) -> None:
        clear_provider_cache()

    def tearDown(self) -> None:
        clear_provider_cache()

    def test_same_config_returns_cached_instance(self) -> None:
        """Repeated calls with the same config return the same object."""
        a = get_provider(PLANETARY_COMPUTER)
        b = get_provider(PLANETARY_COMPUTER)
        assert a is b

    def test_different_url_returns_new_instance(self) -> None:
        """Different api_base_url produces a distinct cached instance."""
        default = get_provider(PLANETARY_COMPUTER)
        custom_cfg = ProviderConfig(
            name=PLANETARY_COMPUTER,
            api_base_url="https://alt.stac.api/v1",
        )
        custom = get_provider(PLANETARY_COMPUTER, config=custom_cfg)
        assert default is not custom
        assert default.name == custom.name

    def test_clear_cache_forces_new_instance(self) -> None:
        """After clearing the cache, a fresh adapter is created."""
        first = get_provider(PLANETARY_COMPUTER)
        clear_provider_cache()
        second = get_provider(PLANETARY_COMPUTER)
        assert first is not second

    def test_failed_init_is_not_cached(self) -> None:
        """Adapters that raise in __init__ are not cached."""
        with self.assertRaises(SkyWatchNotImplementedError):
            get_provider(SKYWATCH)
        # Second call should also raise (not return a cached broken instance).
        with self.assertRaises(SkyWatchNotImplementedError):
            get_provider(SKYWATCH)

    def test_cache_is_thread_safe(self) -> None:
        """Concurrent get_provider calls do not produce duplicate instances."""
        import threading

        results: list[ImageryProvider] = []
        barrier = threading.Barrier(4)

        def _get() -> None:
            barrier.wait()
            results.append(get_provider(PLANETARY_COMPUTER))

        threads = [threading.Thread(target=_get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        assert all(r is results[0] for r in results)
