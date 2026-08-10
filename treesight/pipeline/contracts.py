from __future__ import annotations

from typing import Any


def ensure_nonempty_str_field(value: Any, *, name: str, field: str, index: int | None = None) -> str:
    """Validate a single field value is a non-empty str; raise TypeError otherwise."""
    if isinstance(value, str) and value:
        return value
    where = f"item {index} " if index is not None else ""
    got = type(value).__name__
    raise TypeError(f"{name} activity output {where}key '{field}' must be non-empty str, got {got}")


def ensure_dict_with_keys(value: Any, *, name: str, required: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Validate dict-shaped activity output with required keys."""
    if not isinstance(value, dict):
        raise TypeError(f"{name} activity output must be dict, got {type(value).__name__}")

    missing = [key for key in required if key not in value]
    if missing:
        missing_keys = ", ".join(missing)
        raise ValueError(f"{name} activity output missing required keys: {missing_keys}")

    return value


def ensure_list_of_dicts(
    value: Any,
    *,
    name: str,
    required_item_keys: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    """Validate list[dict] activity output and optional per-item required keys."""
    if not isinstance(value, list):
        raise TypeError(f"{name} activity output must be list[dict], got {type(value).__name__}")

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise TypeError(f"{name} activity output item {index} must be dict, got {type(item).__name__}")

        missing = [key for key in required_item_keys if key not in item]
        if missing:
            missing_keys = ", ".join(missing)
            raise ValueError(f"{name} activity output item {index} missing required keys: {missing_keys}")

    return value


def ensure_parse_kml_output(value: Any) -> list[dict[str, Any]] | dict[str, Any]:
    """Validate parse_kml's bifurcated output (inline list or offloaded ref dict)."""
    if isinstance(value, list):
        return ensure_list_of_dicts(value, name="parse_kml")
    if isinstance(value, dict):
        out = ensure_dict_with_keys(value, name="parse_kml", required=("ref",))
        ensure_nonempty_str_field(out["ref"], name="parse_kml", field="ref")
        return out
    raise TypeError("parse_kml activity output must be list[dict] or dict with required keys: ref")
