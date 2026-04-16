"""Lightweight regression: documented API routes must not drift from live code.

Acceptance criterion 5 for issue #406.  Catches stale route references in
README.md and docs/openapi.yaml by comparing them against the actual HTTP
trigger routes registered in the Azure Functions app.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OPENAPI = ROOT / "docs" / "openapi.yaml"


def _live_routes() -> set[str]:
    """Return the set of route patterns from all registered HTTP functions."""
    from function_app import app

    # Clear stale state so get_functions() succeeds across test modules
    app.functions_bindings = {}
    routes: set[str] = set()
    for fn_info in app.get_functions():
        for binding in fn_info.get_bindings():
            if binding.type in ("httpTrigger",):
                route = getattr(binding, "route", None)
                if route:
                    routes.add(f"/api/{route}")
    return routes


def _readme_routes() -> set[str]:
    """Extract route patterns from the README endpoint table."""
    text = README.read_text()
    # Match table rows: | METHOD | `/api/...` | ...
    pattern = re.compile(r"\|\s*\S+\s*\|\s*`(/api/[^`]+)`")
    return {m.group(1) for m in pattern.finditer(text)}


def _openapi_routes() -> set[str]:
    """Extract path patterns from openapi.yaml."""
    with OPENAPI.open() as f:
        spec = yaml.safe_load(f)
    paths = spec.get("paths", {})
    return {f"/api{p}" for p in paths}


def _normalise(route: str) -> str:
    """Collapse path parameters to a canonical placeholder."""
    return re.sub(r"\{[^}]+\}", "{_}", route)


def test_readme_routes_exist_in_live_code():
    """Every route listed in README.md should map to a live HTTP trigger."""
    live = {_normalise(r) for r in _live_routes()}
    readme = {_normalise(r) for r in _readme_routes()}
    missing = readme - live
    assert not missing, f"README references routes not found in live code: {sorted(missing)}"


def test_openapi_routes_exist_in_live_code():
    """Every path in openapi.yaml should map to a live HTTP trigger."""
    live = {_normalise(r) for r in _live_routes()}
    openapi = {_normalise(r) for r in _openapi_routes()}
    missing = openapi - live
    assert not missing, f"openapi.yaml references routes not found in live code: {sorted(missing)}"


def test_no_legacy_module_names_in_docs():
    """Docs must not reference the old kml_satellite package name."""
    legacy_pattern = re.compile(r"kml_satellite/")
    docs_dir = ROOT / "docs"
    violations: list[str] = []
    for md_file in docs_dir.glob("*.md"):
        text = md_file.read_text()
        matches = legacy_pattern.findall(text)
        if matches:
            violations.append(f"{md_file.name}: {len(matches)} occurrence(s)")
    # Also check README
    readme_text = README.read_text()
    readme_matches = legacy_pattern.findall(readme_text)
    if readme_matches:
        violations.append(f"README.md: {len(readme_matches)} occurrence(s)")
    assert not violations, f"Legacy 'kml_satellite/' references found: {violations}"
