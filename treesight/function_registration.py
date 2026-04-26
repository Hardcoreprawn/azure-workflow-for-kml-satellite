"""Compatibility shim for shared function registration.

Use function_registration.register_function_blueprints from the repo root.
"""

from __future__ import annotations

from function_registration import register_function_blueprints

__all__ = ["register_function_blueprints"]
