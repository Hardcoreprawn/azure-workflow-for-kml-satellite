"""Shared helper functions used across multiple activity modules.

Centralises logic that was previously duplicated in ``download_imagery``,
``acquire_imagery``, and ``post_process_imagery``.

References:
    PID 7.4.5  (Explicit — no duplicated logic)
    Issue #52  (Centralise shared pipeline constants and helpers)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kml_satellite.models.imagery import ProviderConfig


def build_provider_config(
    provider_name: str,
    overrides: dict[str, Any] | None,
) -> ProviderConfig:
    """Build a ``ProviderConfig`` from the provider name and optional overrides.

    Args:
        provider_name: Name of the imagery provider.
        overrides: Optional dict of configuration overrides. If ``None``,
            returns a config with just the provider name.

    Returns:
        A populated ``ProviderConfig`` instance.
    """
    if overrides is None:
        return ProviderConfig(name=provider_name)

    return ProviderConfig(
        name=provider_name,
        api_base_url=str(overrides.get("api_base_url", "")),
        auth_mechanism=str(overrides.get("auth_mechanism", "none")),
        keyvault_secret_name=str(overrides.get("keyvault_secret_name", "")),
        extra_params={str(k): str(v) for k, v in overrides.get("extra_params", {}).items()},
    )


def parse_timestamp(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp string, defaulting to current UTC time.

    Args:
        timestamp: ISO 8601 timestamp string, or empty string.

    Returns:
        A timezone-aware ``datetime`` in UTC. Falls back to
        ``datetime.now(UTC)`` if the input is empty or unparseable.
    """
    if not timestamp:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return datetime.now(UTC)
