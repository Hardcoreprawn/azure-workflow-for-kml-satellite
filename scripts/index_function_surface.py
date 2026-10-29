"""Print the exact Python-indexed surface in a fresh role-specific process."""

from __future__ import annotations

import importlib
import json
import sys


def indexed_surface(entrypoint: str) -> dict[str, object]:
    """Return all function names and bindings, without normalizing away metadata."""
    app = importlib.import_module(entrypoint).app
    return {
        function.get_function_name(): json.loads(function.get_function_json())["bindings"]
        for function in app.get_functions()
    }


if __name__ == "__main__":
    print(json.dumps(indexed_surface(sys.argv[1]), sort_keys=True))
