"""Lightweight regression: documented API routes must not drift from live code.

Acceptance criterion 5 for issue #406.  Catches stale route references in
the canonical API reference and OpenAPI by comparing them against the actual HTTP
trigger routes registered in the Azure Functions app.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
REFERENCE = ROOT / "docs" / "API_INTERFACE_REFERENCE.md"
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


def _reference_routes() -> set[str]:
    """Extract route patterns from the canonical endpoint table."""
    text = REFERENCE.read_text()
    pattern = re.compile(r"^\|\s*[A-Z]+\s*\|\s*`?(/api/[^`\s|]+)`?\s*\|", re.MULTILINE)
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


def _markdown_anchors(text: str) -> set[str]:
    """Return GitHub-style anchors for ATX headings in a Markdown document."""
    anchors: set[str] = set()
    for match in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        heading = re.sub(r"[`*_~]", "", match.group(1)).lower()
        anchor = re.sub(r"[^a-z0-9 -]", "", heading)
        anchor = re.sub(r"\s+", "-", anchor).strip("-")
        if anchor:
            anchors.add(anchor)
    return anchors


def test_reference_routes_exist_in_live_code():
    """Every reference route should map to a live HTTP trigger."""
    live = {_normalise(r) for r in _live_routes()}
    documented = {_normalise(route) for route in _reference_routes()}
    assert documented, "API reference endpoint table must not be empty"
    missing = documented - live
    assert not missing, f"API reference routes not found in live code: {sorted(missing)}"


def test_api_reference_rejects_nonexistent_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reference = tmp_path / "reference.md"
    reference.write_text("| GET | /api/audit-nonexistent | anonymous |\n")
    monkeypatch.setattr(f"{__name__}.REFERENCE", reference)
    with pytest.raises(AssertionError, match="audit-nonexistent"):
        test_reference_routes_exist_in_live_code()


def test_api_reference_rejects_empty_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reference = tmp_path / "reference.md"
    reference.write_text("# Reference\n")
    monkeypatch.setattr(f"{__name__}.REFERENCE", reference)
    with pytest.raises(AssertionError, match="must not be empty"):
        test_reference_routes_exist_in_live_code()


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


def test_activity_reference_matches_registered_functions() -> None:
    tree = ast.parse((ROOT / "blueprints/pipeline/activities.py").read_text())
    registered = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "activity_trigger"
            for decorator in node.decorator_list
        )
    }
    reference = (ROOT / "docs/API_INTERFACE_REFERENCE.md").read_text()
    section = reference.split("## Activity Functions and Contracts", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE))
    assert documented == registered


@pytest.mark.parametrize("output", [None, {"status": "completed"}, {"status": "partial_imagery"}])
def test_openapi_describes_emitted_diagnostics_fields(output: dict[str, str] | None) -> None:
    from blueprints.pipeline._status import _durable_status_payload

    status = SimpleNamespace(
        instance_id="audit-run",
        name="treesight_orchestrator",
        runtime_status=SimpleNamespace(value="Completed"),
        created_time=datetime(2026, 9, 16, tzinfo=UTC),
        last_updated_time=datetime(2026, 9, 16, tzinfo=UTC),
        custom_status=None,
        output=output,
    )
    payload = _durable_status_payload(status)
    spec = yaml.safe_load(OPENAPI.read_text())
    schema = spec["paths"]["/orchestrator/{instance_id}"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert set(payload) == set(schema["properties"])
    assert set(payload) == set(schema["required"])
    assert "null" in schema["properties"]["customStatus"]["type"]
    output_schema = schema["properties"]["output"]
    assert {"type": "null"} in output_schema["oneOf"]
    if output is not None:
        summary = spec["components"]["schemas"]["PipelineSummary"]
        assert set(payload["output"]) <= set(summary["properties"])
        assert set(summary["required"]) <= set(payload["output"])


@pytest.mark.parametrize(
    "document",
    [
        "README.md",
        "docs/ARCHITECTURE_OVERVIEW.md",
        "docs/API_INTERFACE_REFERENCE.md",
        "docs/DATA_MODEL.md",
        "docs/ENRICHMENT_AOI_MODEL.md",
        "docs/SYSTEM_SPEC.md",
        "docs/3-tier-architecture.md",
        "docs/PRODUCTION_ROLLOUT_SPEC.md",
        "docs/OPERATIONS_RUNBOOK.md",
        "docs/adr/0003-three-bounded-contexts.md",
    ],
)
def test_canonical_document_links_resolve(document: str) -> None:
    path = ROOT / document
    destinations = re.findall(r"\[[^\]]+\]\(([^\s)]+)\)", path.read_text())
    missing = []
    for destination in destinations:
        parsed = urlsplit(destination)
        if parsed.scheme or parsed.netloc or (not parsed.path and not parsed.fragment):
            continue
        target = path if not parsed.path else path.parent / unquote(parsed.path)
        if not target.exists():
            missing.append(destination)
            continue
        if (
            parsed.fragment
            and target.suffix.lower() == ".md"
            and parsed.fragment not in _markdown_anchors(target.read_text())
        ):
            missing.append(destination)
    assert not missing, f"{document}: unresolved links {missing}"
