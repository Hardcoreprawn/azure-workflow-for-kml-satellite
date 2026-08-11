#!/usr/bin/env python3
"""Detect when the published dev image is stale relative to build inputs.

The dev image (``Dockerfile.dev``) bakes two OCI labels:

* ``org.canopex.uvlock-sha256``  — SHA-256 of ``uv.lock`` (dependency drift)
* ``org.canopex.build-inputs-sha256`` — combined SHA-256 of ``Dockerfile.dev``,
  ``pyproject.toml``, and all files under ``rust/`` (image-recipe drift)

This guard compares the repo's current digests against the labels on a given
image reference and fails loudly when either diverges. The comparison logic is
pure and unit-tested; only ``read_image_label`` touches Docker.

Usage:
    python scripts/check_dev_image_staleness.py --image ghcr.io/owner/treesight-dev:latest
    python scripts/check_dev_image_staleness.py --image <ref> --warn   # never exits non-zero
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

LABEL_KEY = "org.canopex.uvlock-sha256"
LABEL_KEY_BUILD = "org.canopex.build-inputs-sha256"
DEFAULT_LOCK = "uv.lock"
DEFAULT_DOCKERFILE = "Dockerfile.dev"
_BUILD_EXTRAS = ["pyproject.toml", "rust"]


def uv_lock_digest(lock_path: str | Path) -> str:
    """Return the SHA-256 hex digest of the ``uv.lock`` file at ``lock_path``."""
    data = Path(lock_path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def build_inputs_digest(dockerfile: str | Path, root: str | Path | None = None) -> str:
    """Return a combined SHA-256 digest of the image-recipe build inputs.

    Hashes ``Dockerfile.dev``, ``pyproject.toml``, and every source file under
    ``rust/`` (sorted for determinism), excluding ``rust/target/`` — that's
    Cargo's gitignored build-output directory, not a source input, and its
    contents vary by machine/build history rather than by recipe, which would
    make the digest neither deterministic nor comparable between a fresh CI
    checkout and a developer's already-built local tree.  ``root`` defaults to
    the directory containing ``dockerfile``; pass it explicitly in tests.
    """
    dockerfile = Path(dockerfile)
    root_dir = Path(root) if root is not None else dockerfile.parent

    h = hashlib.sha256()

    # Always hash Dockerfile.dev first.
    h.update(dockerfile.read_bytes())

    # Hash each extra path under root_dir.
    for extra in _BUILD_EXTRAS:
        extra_path = root_dir / extra
        if not extra_path.exists():
            continue
        if extra_path.is_file():
            h.update(extra_path.read_bytes())
        else:
            for path in sorted(extra_path.rglob("*")):
                if path.is_file() and "target" not in path.relative_to(extra_path).parts:
                    h.update(path.read_bytes())

    return h.hexdigest()


def parse_image_label(inspect_json: str, label_key: str = LABEL_KEY) -> str | None:
    """Extract a label value from ``docker image inspect`` JSON output.

    Returns ``None`` when the image or label is absent. Empty label values
    (an image built without ``--build-arg UVLOCK_SHA=...``) also return
    ``None`` so they are treated as "unknown / stale".
    """
    try:
        entries = json.loads(inspect_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(entries, list) or not entries:
        return None
    config = entries[0].get("Config") or {}
    labels = config.get("Labels") or {}
    value = labels.get(label_key)
    return value or None


def staleness_reason(
    repo_lock_digest: str,
    image_lock_label: str | None,
    repo_build_digest: str | None = None,
    image_build_label: str | None = None,
) -> str | None:
    """Return a human-readable reason if the image is stale, else ``None``.

    Checks the uv.lock digest first, then the build-inputs digest when both
    ``repo_build_digest`` and ``image_build_label`` are provided.
    """
    if image_lock_label is None:
        return f"image has no {LABEL_KEY} label (image not pulled, or built without the uv.lock digest)"
    if image_lock_label != repo_lock_digest:
        return (
            "uv.lock has changed since the dev image was built "
            f"(repo={repo_lock_digest[:12]}…, image={image_lock_label[:12]}…) — "
            "the dev-image workflow needs to rebuild/publish"
        )
    if repo_build_digest is not None and image_build_label is not None and image_build_label != repo_build_digest:
        return (
            "build inputs (Dockerfile.dev / pyproject.toml / rust/) have changed "
            "since the dev image was built "
            f"(repo={repo_build_digest[:12]}…, image={image_build_label[:12]}…) — "
            "the dev-image workflow needs to rebuild/publish"
        )
    return None


def read_image_label(image_ref: str, label_key: str = LABEL_KEY) -> str | None:
    """Inspect a local/pulled image and return its label value, or ``None``.

    Returns ``None`` when Docker is unavailable, the image is not present, or
    the label is absent — all "cannot confirm freshness" cases.
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_ref],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        # docker binary not on PATH — cannot determine freshness.
        return None
    if result.returncode != 0:
        return None
    return parse_image_label(result.stdout, label_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Image reference to inspect")
    parser.add_argument("--lock", default=DEFAULT_LOCK, help="Path to uv.lock")
    parser.add_argument(
        "--dockerfile",
        default=DEFAULT_DOCKERFILE,
        help="Path to Dockerfile.dev (used for build-inputs digest)",
    )
    parser.add_argument(
        "--warn",
        action="store_true",
        help="Report staleness but always exit 0 (advisory mode)",
    )
    parser.add_argument(
        "--print-build-digest",
        action="store_true",
        help="Print the build-inputs digest for the given --dockerfile and exit 0",
    )
    args = parser.parse_args(argv)

    if args.print_build_digest:
        dockerfile_path = Path(args.dockerfile)
        print(build_inputs_digest(dockerfile_path))
        return 0

    if not args.image:
        parser.error("--image is required unless --print-build-digest is set")

    repo_lock_digest = uv_lock_digest(args.lock)
    dockerfile_path = Path(args.dockerfile)
    if not dockerfile_path.exists():
        parser.error(
            f"--dockerfile {dockerfile_path} does not exist — cannot compute the "
            "build-inputs digest, so the freshness of Dockerfile.dev/pyproject.toml/"
            "rust/ cannot be verified. Failing fast instead of silently skipping "
            "that check and reporting 'in sync'."
        )
    repo_build_digest = build_inputs_digest(dockerfile_path)

    image_lock_label = read_image_label(args.image, LABEL_KEY)
    image_build_label = read_image_label(args.image, LABEL_KEY_BUILD)
    reason = staleness_reason(repo_lock_digest, image_lock_label, repo_build_digest, image_build_label)

    if reason is None:
        lock_short = repo_lock_digest[:12]
        build_short = repo_build_digest[:12] if repo_build_digest else "n/a"
        print(f"dev image is in sync with {args.lock} ({lock_short}…) and build inputs ({build_short}…)")
        return 0

    prefix = "warning" if args.warn else "error"
    print(f"::{prefix}::dev image is stale: {reason}", file=sys.stderr)
    return 0 if args.warn else 1


if __name__ == "__main__":
    raise SystemExit(main())
