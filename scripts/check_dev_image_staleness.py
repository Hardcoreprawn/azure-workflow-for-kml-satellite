#!/usr/bin/env python3
"""Detect when the published dev image is stale relative to ``uv.lock``.

The dev image (``Dockerfile.dev``) bakes the digest of the ``uv.lock`` it was
built from into the ``org.canopex.uvlock-sha256`` OCI label. If ``uv.lock``
changes on ``main`` but the dev-image publish workflow has not rebuilt the
image, CI (and developers) would run against an out-of-date dependency layer.

This guard compares the repo's current ``uv.lock`` digest against the label on
a given image reference and fails loudly when they diverge. The comparison
logic is pure and unit-tested; only ``read_image_label`` touches Docker.

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
DEFAULT_LOCK = "uv.lock"


def uv_lock_digest(lock_path: str | Path) -> str:
    """Return the SHA-256 hex digest of the ``uv.lock`` file at ``lock_path``."""
    data = Path(lock_path).read_bytes()
    return hashlib.sha256(data).hexdigest()


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


def staleness_reason(repo_digest: str, image_label: str | None) -> str | None:
    """Return a human-readable reason if the image is stale, else ``None``.

    The image is fresh only when its baked label exactly matches the repo's
    current ``uv.lock`` digest.
    """
    if image_label is None:
        return (
            f"image has no {LABEL_KEY} label "
            "(image not pulled, or built without the uv.lock digest)"
        )
    if image_label != repo_digest:
        return (
            "uv.lock has changed since the dev image was built "
            f"(repo={repo_digest[:12]}…, image={image_label[:12]}…) — "
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
    parser.add_argument("--image", required=True, help="Image reference to inspect")
    parser.add_argument("--lock", default=DEFAULT_LOCK, help="Path to uv.lock")
    parser.add_argument(
        "--warn",
        action="store_true",
        help="Report staleness but always exit 0 (advisory mode)",
    )
    args = parser.parse_args(argv)

    repo_digest = uv_lock_digest(args.lock)
    image_label = read_image_label(args.image)
    reason = staleness_reason(repo_digest, image_label)

    if reason is None:
        print(f"dev image is in sync with {args.lock} ({repo_digest[:12]}…)")
        return 0

    prefix = "warning" if args.warn else "error"
    print(f"::{prefix}::dev image is stale: {reason}", file=sys.stderr)
    return 0 if args.warn else 1


if __name__ == "__main__":
    raise SystemExit(main())
