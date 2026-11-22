"""Include the portable council's behavioral tests in the repository gate."""

from pathlib import Path

from engineering_council.test_council import CouncilTests

__all__ = ["CouncilTests"]


def test_migrated_review_routes_resolve_to_installed_canonical_agents() -> None:
    root = Path(__file__).resolve().parents[1]
    definitions = root / ".github" / "agents"
    canonical = root / "engineering_council" / ".github" / "agents"
    names = {}
    for source in canonical.glob("*.agent.md"):
        installed = definitions / source.name
        assert installed.read_text() == source.read_text(), f"Installed agent drift: {installed}"
        name = next(
            line.split(":", 1)[1].strip() for line in source.read_text().splitlines() if line.startswith("name:")
        )
        names[name] = source
    prompts = root / ".github" / "prompts"
    for name in ("code-review-sweep", "persona-gap-audit", "release-gate-audit", "docs-drift-audit", "roadmap-slice"):
        source = prompts / f"{name}.prompt.md"
        route = next(
            line.split(":", 1)[1].strip().strip('"')
            for line in source.read_text().splitlines()
            if line.startswith("agent:")
        )
        assert route in names, f"Unresolved reviewer route: {source}: {route}"
