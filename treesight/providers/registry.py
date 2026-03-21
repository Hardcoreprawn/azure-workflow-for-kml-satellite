"""Provider registry with instance caching (§5.3)."""

from __future__ import annotations

from treesight.providers.base import ImageryProvider, ProviderConfig

_registry: dict[str, type[ImageryProvider]] = {}
_cache: dict[tuple[str, str, str, str, str], ImageryProvider] = {}


def register_provider(name: str, cls: type[ImageryProvider]) -> None:
    """Register an imagery provider class under *name*."""
    _registry[name] = cls


def get_provider(name: str, config: ProviderConfig | None = None) -> ImageryProvider:
    """Return a (cached) provider instance, creating it if necessary."""
    config = config or {}
    extra = config.get("extra_params")
    extra_key = str(sorted(extra.items())) if isinstance(extra, dict) else ""
    cache_key = (
        name,
        str(config.get("api_base_url", "")),
        str(config.get("auth_mechanism", "")),
        str(config.get("keyvault_secret", "")),
        extra_key,
    )
    if cache_key in _cache:
        return _cache[cache_key]

    if name not in _registry:
        # Lazy-import known providers
        if name == "planetary_computer":
            from treesight.providers.planetary_computer import PlanetaryComputerProvider

            register_provider("planetary_computer", PlanetaryComputerProvider)
        else:
            raise ValueError(f"Unknown imagery provider: {name}")

    provider = _registry[name](config)
    _cache[cache_key] = provider
    return provider


def list_providers() -> list[str]:
    """Return the names of all registered providers."""
    return list(_registry.keys())


def clear_provider_cache() -> None:
    """Drop all cached provider instances."""
    _cache.clear()
